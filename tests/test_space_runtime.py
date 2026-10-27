import json
from pathlib import Path
import unittest
from uuid import uuid4
import asyncio
import subprocess
import sys
import urllib.error
import urllib.request
import os
from unittest.mock import patch

from coopagents.spaces import private_write, read_profile, validate_origin
from coopagents import space_runtime as runtime


class Profiles(unittest.TestCase):
    def setUp(self):
        self.directory = Path('.local/runtime-tests') / uuid4().hex
        self.directory.mkdir(parents=True)

    def test_private_profile_conflict(self):
        path = self.directory / 'profile.json'
        data = dict(schema_version=1, origin='http://127.0.0.1:8765',
                    room_id='room', member_id='member', web_token='web', agent_token='agent')
        private_write(path, data)
        self.assertEqual(read_profile(path), data)
        with self.assertRaises(FileExistsError):
            private_write(path, data)

    def test_origin_rejects_credentials_paths_and_remote_http(self):
        for value in ('http://example.com', 'https://x@y.test', 'https://x.test/path',
                      'http://127.0.0.1:9?token=x', 'https://x.test#token'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_origin(value)

    def test_profile_rejects_missing_credentials(self):
        path = self.directory / 'profile.json'
        private_write(path, {'schema_version': 1})
        with self.assertRaises(ValueError):
            read_profile(path)

    def test_hosted_agent_profile_without_web_credential(self):
        path = self.directory / 'hosted-agent.json'
        profile = dict(schema_version=1, origin='https://hosted.example.com',
                       room_id='room', member_id='member', agent_token='agent')
        private_write(path, profile)
        self.assertEqual(read_profile(path), profile)
        with patch.object(runtime, 'request') as remote:
            with self.assertRaises(ValueError):
                runtime.invite(path)
            remote.assert_not_called()

    def test_profile_rejects_empty_optional_web_credential(self):
        path = self.directory / 'invalid-web.json'
        private_write(path, dict(schema_version=1, origin='https://hosted.example.com',
                                 room_id='room', member_id='member', agent_token='agent', web_token=''))
        with self.assertRaises(ValueError):
            read_profile(path)

    def test_state_refuses_repository_and_links(self):
        from coopagents.spaces import private_directory
        with self.assertRaises(ValueError):
            private_directory(Path('tests/private-state'))
        with self.assertRaises(ValueError):
            private_directory(Path('.local/../tests/private-state'))

    def test_status_returns_current_origin_after_control_startup(self):
        profile = dict(schema_version=1, origin='http://127.0.0.1:8765', room_id='room',
                       member_id='member', web_token='web', agent_token='agent',
                       control_origin='http://127.0.0.1:8766', control_token='control')
        updated = profile | {'origin': 'https://fresh.trycloudflare.com'}
        with patch.object(runtime, 'read_profile', side_effect=[profile, updated]), \
             patch.object(runtime, 'request', return_value={'room_id': 'room', 'status': 'running'}):
            self.assertEqual(runtime.status(self.directory / 'profile.json')['origin'], updated['origin'])

    @unittest.skipUnless(os.name == 'nt', 'Windows reparse point regression')
    def test_junction_is_refused_without_pathlib_junction_support(self):
        from coopagents.spaces import checked_path
        target = (self.directory / 'target').absolute()
        target.mkdir()
        junction = (self.directory / 'junction').absolute()
        quote = lambda value: str(value).replace("'", "''")
        script = "New-Item -ItemType Junction -Path '" + quote(junction) + "' -Target '" + quote(target) + "' | Out-Null"
        subprocess.run(['powershell', '-NoProfile', '-Command', script], check=True, capture_output=True)
        # Python 3.11 has no is_junction; returning false exercises the same
        # missed detection in the previous feature-detection implementation.
        with patch.object(Path, 'is_junction', return_value=False, create=True):
            with self.assertRaises(ValueError):
                checked_path(junction / 'profile.json')

    def test_stop_waits_until_runtime_ownership_lock_is_released(self):
        profile = dict(schema_version=1, origin='http://127.0.0.1:8765', room_id='room',
                       member_id='member', web_token='web', agent_token='agent',
                       control_origin='http://127.0.0.1:8766', control_token='control')
        with patch.object(runtime, 'read_profile', return_value=profile), \
             patch.object(runtime, 'request', return_value={'room_id': 'room'}), \
             patch.object(runtime, 'status', return_value={'status': 'unreachable'}), \
             patch.object(runtime, 'runtime_unlocked', side_effect=[False, False, True]) as unlocked, \
             patch.object(runtime.time, 'sleep'):
            self.assertEqual(runtime.stop(self.directory / 'profile.json')['status'], 'stopped')
            self.assertEqual(unlocked.call_count, 3)


class Runtime(unittest.TestCase):
    def setUp(self):
        self.directory = Path('.local/runtime-tests') / uuid4().hex
        self.directory.mkdir(parents=True)
        self.profile_path = self.directory / 'owner' / 'profile.json'

    def tearDown(self):
        if self.profile_path.exists() and runtime.status(self.profile_path)['status'] == 'running':
            runtime.stop(self.profile_path)

    def test_real_supervisor_personal_join_http_websocket_restart(self):
        created = runtime.create('Test space', 'Owner', self.profile_path.parent, network='local')
        owner = read_profile(self.profile_path)
        self.assertNotIn(owner['web_token'], json.dumps(created))
        self.assertNotEqual(owner['origin'], owner['control_origin'])
        self.assertFalse(runtime.runtime_unlocked(self.profile_path))
        invitation = runtime.invite(self.profile_path)
        self.assertNotIn('invite_token', json.dumps(invitation))
        joined = runtime.join(invitation['invitation_file'], 'Peer', self.directory / 'peer')
        peer = read_profile(joined['profile'])
        self.assertNotEqual(owner['member_id'], peer['member_id'])
        self.assertNotIn('control_token', peer)
        with self.assertRaisesRegex(ValueError, 'already used, has expired or was revoked'):
            runtime.join(invitation['invitation_file'], 'Duplicate', self.directory / 'duplicate')
        me = runtime.request(peer['origin'], '/api/me', token=peer['agent_token'])
        self.assertEqual(me['me']['member_id'], peer['member_id'])
        snapshot = runtime.request(peer['origin'], '/api/snapshot', token=peer['agent_token'])
        self.assertEqual(len(snapshot['members']), 2)
        with self.assertRaises(urllib.error.HTTPError):
            runtime.request(peer['origin'], '/api/operations/create_room', token=peer['agent_token'],
                            data={'name': 'Illegal', 'owner_name': 'Peer'})
        with self.assertRaises(urllib.error.HTTPError):
            runtime.request(peer['origin'], '/api/operations/create_task', token=peer['agent_token'],
                            data={'intent_key': 't', 'title': 'Task', 'scope': 'test'})
        task = runtime.request(owner['origin'], '/api/operations/create_task', token=owner['web_token'],
                               data={'intent_key': 't', 'title': 'Task', 'scope': 'test'})
        claimed = runtime.request(peer['origin'], '/api/operations/claim_task', token=peer['agent_token'],
                                  data={'task_id': task['id'], 'session_key': 'peer-session'})
        with self.assertRaises(urllib.error.HTTPError):
            runtime.request(owner['origin'], '/api/operations/claim_task', token=owner['agent_token'],
                            data={'task_id': task['id'], 'session_key': 'owner-session'})

        async def websocket():
            import httpx2
            from mcp import Client
            from mcp.client.streamable_http import streamable_http_client
            async with httpx2.AsyncClient(headers={'Authorization': 'Bearer ' + peer['agent_token'],
                                                   'Origin': peer['origin']}) as http:
                async with Client(streamable_http_client(peer['origin'] + '/mcp', http_client=http), cache=None) as client:
                    result = await client.call_tool('whoami', {})
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content['me']['member_id'], peer['member_id'])
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    self.assertNotIn('create_room', names)
                    self.assertNotIn('invite', names)
            import websockets
            async with websockets.connect(peer['origin'].replace('http:', 'ws:') + '/api/events',
                                          origin=peer['origin']) as ws:
                await ws.send(json.dumps({'token': peer['agent_token'], 'after_id': 0}))
                ready = json.loads(await asyncio.wait_for(ws.recv(), 5))
                self.assertEqual(ready['room_id'], peer['room_id'])
                self.assertEqual(ready['type'], 'ready')
        asyncio.run(websocket())
        with self.assertRaises(urllib.error.HTTPError):
            runtime.request(owner['origin'], '/stop', token=owner['control_token'], data={})
        runtime.stop(self.profile_path)
        self.assertEqual(runtime.status(self.profile_path)['status'], 'unreachable')
        self.assertTrue(runtime.runtime_unlocked(self.profile_path))
        runtime.start(self.profile_path)
        reconnected = runtime.reconnect(joined['profile'], owner['origin'], owner['room_id'])
        self.assertEqual(reconnected['member_id'], peer['member_id'])
        with self.assertRaises(ValueError):
            runtime.reconnect(joined['profile'], owner['origin'], 'different-room')
        snapshot = runtime.request(peer['origin'], '/api/snapshot', token=peer['agent_token'])
        self.assertEqual(len(snapshot['tasks']), 1)
        self.assertEqual(len(snapshot['members']), 2)
        result = subprocess.run([sys.executable, '-m', 'coopagents.space_runtime', 'status',
                                 '--profile', str(self.profile_path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(owner['web_token'], result.stdout + result.stderr)
        self.assertNotIn(owner['agent_token'], result.stdout + result.stderr)

    def test_invitation_message_joins_once_through_stdin(self):
        from datetime import datetime, timedelta, timezone
        runtime.create('Hack night', 'Alice', self.profile_path.parent, network='local')
        owner = read_profile(self.profile_path)
        for hours in (0, 73):
            with self.subTest(hours=hours), self.assertRaises(urllib.error.HTTPError):
                runtime.invite(self.profile_path, hours=hours)
        result = subprocess.run([sys.executable, '-m', 'coopagents.space_runtime', 'invite', '--profile',
                                 str(self.profile_path), '--message', 'zh', '--hours', '24'],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        invited = json.loads(result.stdout)
        message = invited['message']
        self.assertTrue(message.startswith('Alice 邀请你加入 Coopagents 空间「Hack night」。'))
        self.assertTrue(invited['local_only'])
        self.assertNotIn('invitation', invited)
        for secret in (owner['web_token'], owner['agent_token'], owner['control_token']):
            self.assertNotIn(secret, result.stdout + result.stderr)
        expires = datetime.fromisoformat(invited['expires_at'])
        self.assertLess(abs(expires - datetime.now(timezone.utc) - timedelta(hours=24)), timedelta(minutes=5))

        def join(name, text):
            return subprocess.run([sys.executable, '-m', 'coopagents.space_runtime', 'join', '--invitation-code-stdin',
                                   '--name', name, '--state-dir', str(self.directory / name)],
                                  input=text.encode('utf-8'), capture_output=True)
        damaged = join('damaged', message.replace('coopagents-invite-1.', 'coopagents-invite-1.%'))
        self.assertEqual(damaged.returncode, 1)
        self.assertIn(b'Invitation code', damaged.stderr)
        joined = join('peer', message)
        self.assertEqual(joined.returncode, 0, joined.stderr)
        peer = read_profile(json.loads(joined.stdout)['profile'])
        self.assertEqual(peer['room_id'], owner['room_id'])
        for secret in (peer['web_token'], peer['agent_token']):
            self.assertNotIn(secret.encode(), joined.stdout + joined.stderr)
        self.assertEqual(join('again', message).returncode, 1)
        # The file route agents use: the whole message saved to a file.
        second = json.loads(subprocess.run([sys.executable, '-m', 'coopagents.space_runtime', 'invite', '--profile',
                                            str(self.profile_path), '--message', 'en'], capture_output=True, text=True).stdout)
        saved = self.directory / 'pasted-message.txt'
        saved.write_text(second['message'], encoding='utf-8')
        by_file = subprocess.run([sys.executable, '-m', 'coopagents.space_runtime', 'join', '--invitation-file', str(saved),
                                  '--name', 'FromFile', '--state-dir', str(self.directory / 'from-file')], capture_output=True)
        self.assertEqual(by_file.returncode, 0, by_file.stderr)
        with self.assertRaises(ValueError):
            runtime.join(invited['invitation_file'], 'Both', self.directory / 'both', invitation_code=message)

    def test_revoke_invitation_member_and_control_denial(self):
        runtime.create('Test space', 'Owner', self.profile_path.parent, network='local')
        owner = read_profile(self.profile_path)
        invitation = runtime.invite(self.profile_path, share=True)
        runtime.request(owner['origin'], '/api/operations/revoke_invite', token=owner['web_token'],
                        data={'invite_token': invitation['invitation']['invite_token']})
        with self.assertRaisesRegex(ValueError, 'Ask the inviter for a new invitation message'):
            runtime.join(invitation['invitation_file'], 'Peer', self.directory / 'rejected')
        invitation = runtime.invite(self.profile_path)
        peer_info = runtime.join(invitation['invitation_file'], 'Peer', self.directory / 'peer')
        peer = read_profile(peer_info['profile'])
        with self.assertRaises(urllib.error.HTTPError):
            runtime.request(owner['control_origin'], '/stop', token=peer['agent_token'], data={})
        with self.assertRaises(urllib.error.HTTPError):
            runtime.request(owner['origin'], '/api/operations/revoke_member', token=peer['web_token'],
                            data={'member_id': owner['member_id']})
        runtime.request(owner['origin'], '/api/operations/revoke_member', token=owner['web_token'],
                        data={'member_id': peer['member_id']})
        with self.assertRaises(urllib.error.HTTPError):
            runtime.request(peer['origin'], '/api/me', token=peer['agent_token'])


if __name__ == '__main__':
    unittest.main()
