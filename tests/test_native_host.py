import asyncio
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents import space_runtime as runtime
from coopagents.space_bridge import Bridge
from coopagents.space_connect import connect
from coopagents.spaces import private_write, read_profile


class NativeHost(unittest.TestCase):
    def setUp(self):
        self.directory = (Path('.local/native-host-tests') / uuid4().hex).resolve()
        created = runtime.create('Native host recovery', 'Owner', self.directory / 'owner', network='local')
        self.path = Path(created['profile'])
        self.profile = read_profile(self.path)

    def tearDown(self):
        if runtime.status(self.path)['status'] == 'running':
            runtime.stop(self.path)

    def configure(self):
        fake = str(Path(__file__).with_name('fake_mcp_cli.py').resolve())
        with patch.dict(os.environ, {'FAKE_TOOL': 'codex', 'FAKE_MCP_STATE': str(self.directory / 'native.json')}):
            return connect('codex', self.path, cli=[sys.executable, fake], skills=self.directory / 'skills')

    def lose_supervisor(self):
        # Simulate process loss without invoking the user's explicit stop command.
        runtime.request(self.profile['control_origin'], '/stop', token=self.profile['control_token'], data={})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if runtime.runtime_unlocked(self.path) and runtime.status(self.path)['status'] == 'unreachable':
                return
            time.sleep(.1)
        self.fail('Synthetic supervisor did not exit')

    def verify(self, path=None):
        return asyncio.run(Bridge(path or self.path).verified_profile())

    def test_native_owner_recovers_original_runtime_after_command_process_loss(self):
        result = self.configure()
        original = self.path.read_bytes()
        task = runtime.request(self.profile['origin'], '/api/operations/create_task',
                               token=self.profile['web_token'],
                               data={'intent_key': 'retained-task', 'title': 'Keep this task', 'scope': 'Synthetic lifecycle regression'})
        host = self.path.with_name('host.json').read_bytes()
        self.lose_supervisor()
        recovered = self.verify()
        self.assertTrue(result['host_lifecycle']['enabled'])
        self.assertEqual(recovered['room_id'], self.profile['room_id'])
        self.assertEqual(recovered['member_id'], self.profile['member_id'])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.with_name('host.json').read_bytes(), host)
        self.assertEqual(runtime.status(self.path)['status'], 'running')
        snapshot = runtime.request(self.profile['origin'], '/api/snapshot', token=self.profile['web_token'])
        self.assertIn(task, snapshot['tasks'])

    def test_explicit_stop_survives_reconnect_until_explicit_start(self):
        self.configure()
        runtime.stop(self.path)
        self.configure()  # Re-registering a connection must not unpause it.
        with self.assertRaisesRegex(ValueError, 'stopped'):
            self.verify()
        self.assertEqual(runtime.status(self.path)['status'], 'unreachable')
        self.assertEqual(runtime.stop(self.path)['status'], 'stopped')
        runtime.start(self.path)
        self.assertEqual(self.verify()['member_id'], self.profile['member_id'])

    def test_concurrent_native_sessions_start_one_supervisor(self):
        self.configure()
        self.lose_supervisor()
        before = set(self.path.parent.glob('runtime-*.log'))
        script = ('import asyncio,sys; from coopagents.space_bridge import Bridge; '
                  'print(asyncio.run(Bridge(sys.argv[1]).verified_profile())["member_id"])')
        processes = [subprocess.Popen([sys.executable, '-c', script, str(self.path)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        identities = []
        for process in processes:
            output, error = process.communicate(timeout=90)
            self.assertEqual(process.returncode, 0, error)
            identities.append(output.strip())
        self.assertEqual(identities, [self.profile['member_id']] * 2)
        self.assertEqual(len(set(self.path.parent.glob('runtime-*.log')) - before), 1)

    def test_unconfigured_owner_and_member_do_not_start_hosts(self):
        invitation = runtime.invite(self.path)
        member = runtime.join(invitation['invitation_file'], 'Member', self.directory / 'member')
        self.lose_supervisor()
        with patch.object(runtime, '_start', side_effect=AssertionError('Not authorized to auto-start')):
            for path in (self.path, member['profile']):
                with self.assertRaises((OSError, ValueError)):
                    self.verify(path)
        self.assertEqual(runtime.status(self.path)['status'], 'unreachable')

    def test_registered_quick_and_external_owners_do_not_opt_into_recovery(self):
        from coopagents.spaces import read_json
        host_path = self.path.with_name('host.json')
        host = read_json(host_path)
        for network in ('quick', 'external'):
            with self.subTest(network=network):
                private_write(host_path, dict(host, network=network), update=True)
                self.assertFalse(self.configure()['host_lifecycle']['enabled'])
                self.assertFalse(self.path.with_name('native-host.json').exists())
        private_write(host_path, host, update=True)

    def test_failed_recovery_is_bounded_until_explicit_start(self):
        self.configure()
        self.lose_supervisor()
        with patch.object(runtime, '_start', side_effect=RuntimeError('Synthetic startup failure')) as start:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'retry explicitly'):
                    self.verify()
            self.assertEqual(start.call_count, 1)
        self.configure()  # Reconnecting cannot clear the failure lock.
        with self.assertRaisesRegex(ValueError, 'retry explicitly'):
            self.verify()
        runtime.start(self.path)
        self.assertEqual(self.verify()['member_id'], self.profile['member_id'])

    def test_doctor_explains_dormant_host_without_starting_it(self):
        from coopagents.onboarding_doctor import profile_checks
        self.configure()
        self.lose_supervisor()
        with patch.object(runtime, '_start', side_effect=AssertionError('Doctor must remain read-only')):
            checks = profile_checks(self.path)['checks']
        reachability = next(c for c in checks if c['id'] == 'runtime_reachability')
        self.assertEqual(reachability['status'], 'needs_user')
        self.assertEqual(reachability['evidence']['reason'], 'awaiting_native_session')
        self.assertEqual(runtime.status(self.path)['status'], 'unreachable')

    def test_recovery_record_is_bound_to_identity(self):
        self.configure()
        policy = self.path.with_name('native-host.json')
        document = json.loads(policy.read_text())
        document['member_id'] = 'different-member'
        private_write(policy, document, update=True)
        self.lose_supervisor()
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.verify()
        self.assertEqual(runtime.status(self.path)['status'], 'unreachable')


if __name__ == '__main__':
    unittest.main()
