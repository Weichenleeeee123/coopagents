import io
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from uuid import uuid4

from coopagents.api import Service
from coopagents.errors import AccessDenied
from coopagents.spaces import checked_path, private_write
from coopagents import space_wake
from coopagents.space_wake import (AuthDenied, Policy, Watcher, WakeSetupError, WakeState, disable, hook_config,
                                 install, merge_cursor_hooks, merge_hooks, merge_zcode_hooks, remote_digest, settings_path, wake_text, watch)
from transport_support import LiveService


def evidence(name):
    root = Path('.local/test-evidence') / ('wake-' + name + '-' + uuid4().hex)
    root.mkdir(parents=True, exist_ok=True)
    return root


def hook_script(command):
    if ' -EncodedCommand ' not in command:
        return command
    encoded = command.split(' -EncodedCommand ', 1)[1]
    return base64.b64decode(encoded).decode('utf-16-le')


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds or 0.001


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.s = Service(evidence('digest') / 'room.sqlite3')
        self.a = self.s.identity.create_room('Wake', 'Alice')
        self.b = self.s.identity.add_member(self.a['web_token'], 'Bob')

    def digest(self, who):
        return self.s.call('wake_digest', who['agent_token'], {})

    def send(self, sender, receiver, body='Need login_ticket format'):
        return self.s.call('send_request', sender['agent_token'], dict(
            request_key=str(uuid4()), receiver_member_id=receiver['member_id'], context_version=1, body=body))

    def test_request_reply_lifecycle_without_bodies_or_receipts(self):
        request = self.send(self.b, self.a, body='SECRET-BODY-123')
        digest = self.digest(self.a)
        self.assertEqual(digest['counts'], {'request': 1, 'reply': 0, 'handoff': 0})
        self.assertEqual(digest['items'][0]['kind'], 'request')
        self.assertNotIn('SECRET-BODY-123', json.dumps(digest))
        self.assertEqual(self.digest(self.b)['counts']['request'], 0, 'Sender is not woken for its own request')
        # Reading the digest is not reading the message.
        self.assertIsNone(self.s.messages.list_requests(self.a['web_token'])[0]['read_at'])
        self.s.call('read_inbox', self.a['agent_token'], {})
        self.assertEqual(self.digest(self.a)['counts']['request'], 0)
        self.s.call('reply', self.a['agent_token'], dict(request_id=request['id'], request_key=str(uuid4()),
                                                         context_version=1, body='string, 600 seconds'))
        reply_digest = self.digest(self.b)
        self.assertEqual(reply_digest['counts'], {'request': 0, 'reply': 1, 'handoff': 0})
        self.assertEqual(self.digest(self.a)['counts']['reply'], 0, 'Author is not woken for its own reply')
        self.s.call('resolve_request', self.b['agent_token'], dict(request_id=request['id'], context_version=1))
        self.assertEqual(self.digest(self.b)['items'], [])

    def test_handoff_and_dependency_routes(self):
        task = self.s.tasks.create_task(self.a['web_token'], 'api', 'API', 'src/api')
        task = self.s.tasks.claim_task(self.a['agent_token'], task['id'], session_key='one')
        self.s.call('propose_handoff', self.a['agent_token'], dict(
            task_id=task['id'], expected_revision=task['revision'], request_key=str(uuid4()),
            summary='Branch feature/api', target_member_id=self.b['member_id'], session_key='one',
            ownership_epoch=task['ownership_epoch']))
        self.assertEqual(self.digest(self.b)['counts']['handoff'], 1)
        ui = self.s.tasks.claim_task(self.b['agent_token'], self.s.tasks.create_task(self.b['web_token'], 'ui', 'UI', 'src/ui')['id'], session_key='ui')
        dep = self.s.call('create_dependency', self.b['agent_token'], dict(
            source_task_id=ui['id'], target_task_id=task['id'], need='Login schema', context='',
            expected_revision=ui['revision'], request_key=str(uuid4()), session_key='ui', ownership_epoch=ui['ownership_epoch']))
        self.assertEqual(dep['routing_state'], 'routed')
        self.assertEqual(self.digest(self.a)['counts']['request'], 1, 'Dependency owner is woken through its routed request')

    def test_web_credential_is_rejected(self):
        with self.assertRaises(AccessDenied):
            self.s.call('wake_digest', self.a['web_token'], {})


class WatcherPolicyTests(unittest.TestCase):
    def setUp(self):
        self.profile = evidence('policy') / 'profile.json'
        private_write(self.profile, dict(schema_version=1, origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='t'))
        self.clock = FakeClock()
        self.items = []
        self.calls = 0

    def digest(self):
        self.calls += 1
        return {'items': list(self.items), 'counts': {}}

    def watcher(self, session='s1', event='Stop', policy=None, digest=None):
        return Watcher(self.profile, 'claude', session, event, policy=policy or Policy(debounce=0, poll=5),
                       digest=digest or self.digest, clock=self.clock, sleep=self.clock.sleep, cursor=lambda: None)

    def test_wakes_once_per_item_across_sessions(self):
        self.items = [{'kind': 'request', 'id': 7}]
        outcome, text = self.watcher().run(60)
        self.assertEqual(outcome, 'wake')
        self.assertIn('1 new request addressed to you', text)
        self.clock.now += 1000
        self.assertEqual(self.watcher(session='s2').run(30), ('quiet', 'deadline'))

    def test_rate_limits_defer_then_wake(self):
        policy = Policy(debounce=0, poll=5, min_interval=60, max_per_hour=2)
        self.items = [{'kind': 'request', 'id': 1}]
        self.assertEqual(self.watcher(policy=policy).run(10)[0], 'wake')
        self.items.append({'kind': 'reply', 'id': 2})
        self.assertEqual(self.watcher(policy=policy).run(30), ('quiet', 'deadline'), 'Within the minimum interval')
        started = self.clock.now
        self.assertEqual(self.watcher(policy=policy).run(120)[0], 'wake')
        self.assertGreaterEqual(self.clock.now - started, 25)
        self.items.append({'kind': 'handoff', 'id': 3})
        self.assertEqual(self.watcher(policy=policy).run(1200), ('quiet', 'deadline'), 'Hourly cap reached')

    def test_debounce_coalesces_burst(self):
        state = {'n': 0}
        def burst():
            state['n'] += 1
            items = [{'kind': 'request', 'id': 1}]
            if state['n'] > 1:
                items.append({'kind': 'request', 'id': 2})
            return {'items': items}
        outcome, text = self.watcher(policy=Policy(debounce=3, poll=5), digest=burst).run(60)
        self.assertEqual(outcome, 'wake')
        self.assertIn('2 new requests addressed to you', text)

    def test_session_start_baseline_only_wakes_for_new_items(self):
        self.items = [{'kind': 'request', 'id': 1}]
        def later():
            if self.clock.now > 1_000_020:
                self.items = [{'kind': 'request', 'id': 1}, {'kind': 'handoff', 'id': 9}]
            return {'items': list(self.items)}
        outcome, text = self.watcher(event='SessionStart', digest=later).run(60, baseline=True)
        self.assertEqual(outcome, 'wake')
        self.assertIn('1 task handoff offered to you', text)
        self.assertNotIn('request', text.split('Use the')[0])

    def test_newer_watcher_supersedes(self):
        older = self.watcher()
        def takeover():
            if self.clock.now > 1_000_010 and not hasattr(self, 'taken'):
                self.taken = True
                WakeState(self.profile).register('s1', 'claude', 'Stop', self.clock.now)
            return {'items': []}
        older.digest = takeover
        self.assertEqual(older.run(100), ('quiet', 'superseded'))

    def test_auth_denied_and_faults_never_wake(self):
        def denied():
            raise AuthDenied()
        self.assertEqual(self.watcher(digest=denied).run(60), ('quiet', 'auth_denied'))
        def broken():
            raise OSError('offline')
        self.assertEqual(self.watcher(digest=broken).run(60), ('quiet', 'deadline'))

    def test_concurrent_claims_wake_only_one_watcher(self):
        from concurrent.futures import ThreadPoolExecutor
        gate = threading.Barrier(6)
        policy = Policy(min_interval=0, max_per_hour=100)
        def claim(n):
            gate.wait(timeout=5)
            return WakeState(self.profile).claim(['request:1'], f's{n}', 1_000_000.0 + n, policy)[0]
        with ThreadPoolExecutor(max_workers=6) as pool:
            winners = [r for r in pool.map(claim, range(6)) if r]
        self.assertEqual(winners, [['request:1']])

    def test_orphaned_watcher_never_claims(self):
        self.items = [{'kind': 'request', 'id': 5}]
        owner = {'alive': False}
        orphan = Watcher(self.profile, 'claude', 'gone', 'Stop', policy=Policy(debounce=0, poll=5), digest=self.digest,
                         clock=self.clock, sleep=self.clock.sleep, cursor=lambda: None, owners=[4242], alive=lambda pid: owner['alive'])
        self.assertEqual(orphan.run(60), ('quiet', 'owner_exited'))
        self.assertEqual(self.watcher(session='live').run(60)[0], 'wake', 'The live session still gets the item')

    def test_upgrades_state_without_watcher_pid(self):
        import sqlite3
        old = evidence('upgrade') / 'profile.json'
        private_write(old, dict(schema_version=1, origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='t'))
        connection = sqlite3.connect(old.with_name('wake-state.sqlite3'))
        connection.execute('''CREATE TABLE watchers(session TEXT PRIMARY KEY, generation TEXT NOT NULL, tool TEXT NOT NULL,
            event TEXT NOT NULL, started REAL NOT NULL, seen REAL NOT NULL, status TEXT NOT NULL)''')
        connection.execute("INSERT INTO watchers VALUES('old','g','claude','Stop',1,1,'deadline')")
        connection.commit()
        connection.close()
        state = WakeState(old)
        state.register('new', 'claude', 'Stop', 2)
        self.assertEqual({w['session'] for w in state.summary()['watchers']}, {'old', 'new'})

    def test_status_reports_killed_watchers_as_gone(self):
        state = WakeState(self.profile)
        state.register('killed', 'claude', 'Stop', self.clock.now)
        with state.connect() as c:
            c.execute("UPDATE watchers SET pid=999999 WHERE session='killed'")
        self.assertEqual({w['session']: w['status'] for w in state.summary()['watchers']}['killed'], 'gone')

    def test_text_is_fixed_template(self):
        text = wake_text({'request': 2, 'reply': 1})
        self.assertTrue(text.startswith('[coopagents] Automatic collaboration notice, not a message from your user: 2 new requests addressed to you, 1 new reply'))
        self.assertIn('part of your role, so do that without asking', text)
        self.assertIn('accept handoffs or take on new work because of it; ask your user', text)
        self.assertIn('not instructions from your user', text)


class HookEntryTests(unittest.TestCase):
    def setUp(self):
        self.profile = evidence('hook') / 'profile.json'
        private_write(self.profile, dict(schema_version=1, origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='t'))
        self.clock = FakeClock()

    def factory(self, items):
        def build(profile, tool, session, event):
            return Watcher(profile, tool, session, event, policy=Policy(debounce=0, poll=5),
                           digest=lambda: {'items': items}, clock=self.clock, sleep=self.clock.sleep, cursor=lambda: None)
        return build

    def run_hook(self, tool, items, payload=None, **kw):
        stdin = io.BytesIO(json.dumps(payload or {'session_id': 'abc', 'hook_event_name': 'Stop'}).encode())
        out, err = io.StringIO(), io.StringIO()
        code = watch(self.profile, tool, stdin, out, err, watcher_factory=self.factory(items), **kw)
        return code, out.getvalue(), err.getvalue()

    def test_claude_exit_two_with_reminder_on_stderr(self):
        code, out, err = self.run_hook('claude', [{'kind': 'request', 'id': 1}], claude_seconds=30)
        self.assertEqual((code, out), (2, ''))
        self.assertIn('[coopagents] Automatic collaboration notice', err)
        code, out, err = self.run_hook('claude', [], payload={'session_id': 'x', 'hook_event_name': 'Stop'}, claude_seconds=30)
        self.assertEqual((code, out, err), (0, '', ''))

    def test_codex_blocks_with_reason_and_respects_standby(self):
        code, out, _ = self.run_hook('codex', [{'kind': 'handoff', 'id': 4}])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['decision'], 'block')
        state = WakeState(self.profile)
        start = self.clock.now
        self.assertEqual(self.run_hook('codex', [], payload={'session_id': 'y', 'hook_event_name': 'Stop'})[1], '')
        self.assertLess(self.clock.now - start, 10, 'Standby off: one check only')
        state.set_standby(600)
        state.set_budget(300)
        self.assertEqual(state.standby(), 300, 'Standby never exceeds the installed hook budget')
        start = self.clock.now
        self.run_hook('codex', [], payload={'session_id': 'z', 'hook_event_name': 'Stop'})
        self.assertGreaterEqual(self.clock.now - start, 300)

    def test_headless_claude_never_watches(self):
        from unittest.mock import patch
        with patch.dict('os.environ', {'CLAUDE_CODE_ENTRYPOINT': 'sdk-cli'}):
            code, out, err = self.run_hook('claude', [{'kind': 'request', 'id': 1}], claude_seconds=30)
        self.assertEqual((code, out, err), (0, '', ''))
        with WakeState(self.profile).connect() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM watchers WHERE session='abc'").fetchone())

    def test_p2p_member_watcher_never_opens_a_link(self):
        from unittest.mock import patch
        import coopagents.p2p as p2p
        member = evidence('p2p') / 'profile.json'
        private_write(member, dict(schema_version=1, origin='http://127.0.0.1:9', room_id='r', member_id='m',
                                   agent_token='t', p2p={'endpoint_id': 'a' * 64}))
        opened = []
        with patch.object(p2p, 'MemberLink', side_effect=lambda *a: opened.append(a)), \
             patch.object(p2p, 'member_link', side_effect=lambda *a: opened.append(a)):
            stdin = io.BytesIO(json.dumps({'session_id': 'p2p', 'hook_event_name': 'Stop'}).encode())
            self.assertEqual(watch(member, 'codex', stdin, io.StringIO(), io.StringIO()), 0)
        self.assertEqual(opened, [], 'A short-lived watcher must not hold the member link')
        with WakeState(member).connect() as c:
            self.assertEqual(c.execute("SELECT status FROM watchers WHERE session='p2p'").fetchone()[0], 'deadline')

    def test_zcode_stop_blocks_with_reason_and_session_start_only_baselines(self):
        items = [{'kind': 'request', 'id': 1}]
        code, out, _ = self.run_hook('zcode', items, payload={'session_id': 'zs', 'hook_event_name': 'SessionStart'})
        self.assertEqual((code, out), (0, ''), 'SessionStart baselines without waking')
        code, out, _ = self.run_hook('zcode', items, payload={'session_id': 'zs', 'hook_event_name': 'Stop'})
        self.assertEqual((code, out), (0, ''), 'Baselined items do not wake the first Stop')
        code, out, _ = self.run_hook('zcode', items + [{'kind': 'reply', 'id': 2}],
                                     payload={'session_id': 'zs', 'hook_event_name': 'Stop'})
        self.assertEqual(code, 0)
        decision = json.loads(out)
        self.assertEqual(decision['decision'], 'block')
        self.assertIn('1 new reply to your request', decision['reason'])

    def test_cursor_stop_returns_followup_and_session_start_only_baselines(self):
        items = [{'kind': 'request', 'id': 1}]
        code, out, _ = self.run_hook('cursor', items, payload={'conversation_id': 'cs', 'hook_event_name': 'sessionStart'})
        self.assertEqual((code, out), (0, ''), 'sessionStart baselines without waking')
        code, out, _ = self.run_hook('cursor', items, payload={'conversation_id': 'cs', 'hook_event_name': 'stop'})
        self.assertEqual((code, out), (0, ''), 'Baselined items do not wake the first stop')
        code, out, _ = self.run_hook('cursor', items + [{'kind': 'reply', 'id': 2}],
                                     payload={'conversation_id': 'cs', 'hook_event_name': 'stop'})
        self.assertEqual(code, 0)
        self.assertIn('1 new reply to your request', json.loads(out)['followup_message'])
        # session_id fallback: sessionStart payloads carry both identifiers.
        code, out, _ = self.run_hook('cursor', [], payload={'session_id': 'cs2', 'hook_event_name': 'sessionStart'})
        self.assertEqual((code, out), (0, ''))
        with WakeState(self.profile).connect() as c:
            self.assertIsNotNone(c.execute("SELECT 1 FROM watchers WHERE session='cs2'").fetchone())

    def test_codex_desktop_watch_blocks_like_codex(self):
        code, out, _ = self.run_hook('codex-desktop', [{'kind': 'request', 'id': 1}])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['decision'], 'block')

    def test_malformed_input_is_quiet(self):
        stdin = io.BytesIO(b'not json')
        self.assertEqual(watch(self.profile, 'claude', stdin, io.StringIO(), io.StringIO()), 0)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.root = evidence('install')
        self.profile = self.root / 'private' / 'profile.json'
        private_write(self.profile, dict(schema_version=1, origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='t'))
        self.project = self.root / 'project'

    def test_merge_keeps_foreign_hooks_and_is_idempotent(self):
        foreign = {'type': 'command', 'command': 'echo keep'}
        document = {'model': 'x', 'hooks': {'Stop': [{'hooks': [foreign]}], 'PreToolUse': [{'matcher': 'Bash', 'hooks': [foreign]}]}}
        once = merge_hooks(document, hook_config(self.profile, 'claude'))
        twice = merge_hooks(once, hook_config(self.profile, 'claude'))
        self.assertEqual(once, twice)
        self.assertEqual(twice['model'], 'x')
        self.assertEqual(len(twice['hooks']['Stop']), 2)
        self.assertEqual(twice['hooks']['PreToolUse'], document['hooks']['PreToolUse'])
        self.assertEqual(merge_hooks(twice, {}), document)

    def test_hooks_installed_before_the_rename_are_replaced_and_removable(self):
        legacy = {'type': 'command', 'command': 'python -I -m crewmesh.space_wake watch --tool claude --profile p'}
        foreign = {'type': 'command', 'command': 'echo keep'}
        document = {'hooks': {'Stop': [{'hooks': [foreign]}, {'hooks': [legacy]}], 'SessionStart': [{'hooks': [legacy]}]}}
        upgraded = merge_hooks(document, hook_config(self.profile, 'claude'))
        commands = [h['command'] for groups in upgraded['hooks'].values() for g in groups for h in g['hooks']]
        self.assertFalse(any('crewmesh.space_wake' in c for c in commands))
        self.assertEqual(sum('coopagents.space_wake' in hook_script(c) for c in commands), 2)
        self.assertEqual(merge_hooks(document, {}), {'hooks': {'Stop': [{'hooks': [foreign]}]}})

    def test_generated_command_runs_in_native_shells(self):
        import shutil
        command = hook_config(self.profile, 'codex')['Stop'][0]['hooks'][0]['command']
        shells = {'default': None}
        if sys.platform == 'win32':
            shells['powershell'] = ['powershell.exe', '-NoProfile', '-Command', command]
            bash = shutil.which('bash')
            if bash:
                shells['bash'] = [bash, '-c', command]
        for name, argv in shells.items():
            session = 'shell-' + name
            payload = json.dumps({'session_id': session, 'hook_event_name': 'Stop'}).encode()
            proc = subprocess.run(argv or command, shell=argv is None, input=payload, capture_output=True, timeout=60)
            self.assertEqual(proc.returncode, 0, (name, proc.stderr))
            with WakeState(self.profile).connect() as c:
                row = c.execute('SELECT status FROM watchers WHERE session=?', (session,)).fetchone()
            self.assertIsNotNone(row, f'{name} did not reach the watcher')
            self.assertEqual(row[0], 'deadline', name)

    def test_zcode_hook_config_uses_process_hooks_with_stop_timeout(self):
        config = hook_config(self.profile, 'zcode', standby=400)
        self.assertEqual(sorted(config), ['SessionStart', 'Stop'])
        start = config['SessionStart'][0]
        self.assertEqual(start['matcher'], 'startup|clear')
        hook = start['hooks'][0]
        self.assertEqual(hook['type'], 'process')
        self.assertEqual(hook['command'], str(Path(sys.executable)))
        self.assertEqual(hook['args'], ['-I', '-m', 'coopagents.space_wake', 'watch', '--tool', 'zcode',
                                        '--profile', str(checked_path(self.profile))])
        stop = config['Stop'][0]['hooks'][0]
        self.assertEqual(stop['timeoutMs'], (400 + space_wake.DEADLINE_MARGIN) * 1000)
        self.assertNotIn('timeout', stop)

    def test_zcode_merge_preserves_mcp_and_foreign_hooks_and_is_idempotent(self):
        foreign = {'type': 'process', 'command': 'node', 'args': ['scripts/check.mjs']}
        document = {'mcp': {'servers': {'other': {'type': 'http', 'url': 'https://other.example/mcp'}}},
                    'hooks': {'enabled': True, 'timeoutMs': 60000,
                              'events': {'Stop': [{'hooks': [foreign]}],
                                         'PreToolUse': [{'matcher': 'Bash', 'hooks': [foreign]}]}}}
        once = merge_zcode_hooks(document, hook_config(self.profile, 'zcode'))
        twice = merge_zcode_hooks(once, hook_config(self.profile, 'zcode'))
        self.assertEqual(once, twice)
        self.assertEqual(twice['mcp'], document['mcp'])
        self.assertEqual(twice['hooks']['timeoutMs'], 60000)
        self.assertTrue(twice['hooks']['enabled'])
        self.assertEqual(len(twice['hooks']['events']['Stop']), 2)
        self.assertEqual(twice['hooks']['events']['PreToolUse'], document['hooks']['events']['PreToolUse'])
        self.assertEqual(merge_zcode_hooks(twice, {}), document)

    def test_zcode_hooks_installed_before_the_rename_are_replaced_and_removable(self):
        legacy = {'type': 'process', 'command': sys.executable,
                  'args': ['-I', '-m', 'crewmesh.space_wake', 'watch', '--tool', 'zcode', '--profile', 'p']}
        foreign = {'type': 'process', 'command': 'node', 'args': ['scripts/check.mjs']}
        document = {'hooks': {'enabled': True, 'events': {'Stop': [{'hooks': [foreign]}, {'hooks': [legacy]}],
                                                          'SessionStart': [{'hooks': [legacy]}]}}}
        upgraded = merge_zcode_hooks(document, hook_config(self.profile, 'zcode'))
        argv = [str(a) for groups in upgraded['hooks']['events'].values() for g in groups
                for h in g['hooks'] for a in h.get('args', [])]
        self.assertFalse(any('crewmesh.space_wake' in a for a in argv))
        self.assertEqual(sum('coopagents.space_wake' in a for a in argv), 2)
        self.assertEqual(merge_zcode_hooks(document, {}),
                         {'hooks': {'enabled': True, 'events': {'Stop': [{'hooks': [foreign]}]}}})

    def test_zcode_process_hook_runs_as_a_subprocess(self):
        hook = hook_config(self.profile, 'zcode')['Stop'][0]['hooks'][0]
        payload = json.dumps({'session_id': 'zcode-proc', 'hook_event_name': 'Stop'}).encode()
        proc = subprocess.run([hook['command'], *hook['args']], input=payload, capture_output=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with WakeState(self.profile).connect() as c:
            row = c.execute("SELECT status FROM watchers WHERE session='zcode-proc'").fetchone()
        self.assertIsNotNone(row, 'The process hook did not reach the watcher')
        self.assertEqual(row[0], 'deadline')

    def test_zcode_install_and_disable_use_user_config_only(self):
        from unittest.mock import patch
        home = self.root / 'home'
        home.mkdir()
        config = home / '.zcode' / 'cli' / 'config.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'mcp': {'servers': {'other': {'type': 'http', 'url': 'https://other.example/mcp'}}}}),
                          encoding='utf-8')
        with patch.dict('os.environ', {'HOME': str(home)}):
            self.assertEqual(settings_path('zcode', 'user'), config)
            result = install(self.profile, 'zcode', scope='user', standby=400)
            self.assertEqual(result['settings'], str(config))
            self.assertEqual(result['events'], ['SessionStart', 'Stop'])
            document = json.loads(config.read_text(encoding='utf-8'))
            self.assertTrue(document['hooks']['enabled'])
            self.assertEqual(document['mcp']['servers']['other']['url'], 'https://other.example/mcp')
            stop = document['hooks']['events']['Stop'][0]['hooks'][0]
            self.assertEqual(stop['timeoutMs'], (400 + space_wake.DEADLINE_MARGIN) * 1000)
            self.assertTrue(list(config.parent.glob('config.json.coopagents-*.bak')), 'Previous settings are kept')
            self.assertTrue(disable('zcode', scope='user')['changed'])
            after = json.loads(config.read_text(encoding='utf-8'))
            self.assertEqual(after['mcp'], document['mcp'])
            self.assertNotIn('events', after['hooks'])

    def test_zcode_project_scope_and_missing_profile_are_refused(self):
        with self.assertRaises(WakeSetupError):
            install(self.profile, 'zcode', scope='project', project_dir=self.project)
        with self.assertRaises(WakeSetupError):
            install(None, 'zcode', scope='user')
        with self.assertRaises(WakeSetupError):
            disable('zcode', scope='project', project_dir=self.project)
        with self.assertRaises(WakeSetupError):
            settings_path('zcode', 'project', self.project)

    def test_zcode_preview_cli_accepts_explicit_tool_and_profile(self):
        from contextlib import redirect_stdout
        from unittest.mock import patch
        home = self.root / 'home2'
        home.mkdir()
        with patch.dict('os.environ', {'HOME': str(home), 'CLAUDECODE': '1'}):
            out = io.StringIO()
            with redirect_stdout(out):
                code = space_wake.main(['preview', '--tool', 'zcode', '--scope', 'user',
                                        '--profile', str(self.profile)])
            self.assertEqual(code, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result['settings'], str(home / '.zcode' / 'cli' / 'config.json'))
            # Regression: the preview must emit the config.json hooks shape
            # {"enabled": true, "events": {...}}, never the plugin-file
            # events map — ZCode's strict schema rejects the latter and the
            # loader then discards the whole config file.
            self.assertEqual(sorted(result['hooks']), ['enabled', 'events'])
            self.assertIs(result['hooks']['enabled'], True)
            self.assertEqual(sorted(result['hooks']['events']), ['SessionStart', 'Stop'])

    def test_zcode_preview_matches_what_install_writes_to_a_fresh_config(self):
        from contextlib import redirect_stdout
        from unittest.mock import patch
        home = self.root / 'home3'
        home.mkdir()
        config = home / '.zcode' / 'cli' / 'config.json'
        with patch.dict('os.environ', {'HOME': str(home), 'CLAUDECODE': '1'}):
            out = io.StringIO()
            with redirect_stdout(out):
                code = space_wake.main(['preview', '--tool', 'zcode', '--scope', 'user',
                                        '--profile', str(self.profile)])
            self.assertEqual(code, 0)
            preview_hooks = json.loads(out.getvalue())['hooks']
            install(self.profile, 'zcode', scope='user')
            installed = json.loads(config.read_text(encoding='utf-8'))
            self.assertEqual(preview_hooks, installed['hooks'])
            self.assertEqual(installed, merge_zcode_hooks({}, hook_config(self.profile, 'zcode')))

    def test_cursor_hook_config_uses_flat_definitions_with_stop_timeout(self):
        config = hook_config(self.profile, 'cursor', standby=400)
        self.assertEqual(sorted(config), ['sessionStart', 'stop'])
        start = config['sessionStart'][0]
        self.assertEqual(start['timeout'], space_wake.CURSOR_SESSION_TIMEOUT)
        stop = config['stop'][0]
        self.assertEqual(stop['timeout'], 400 + space_wake.DEADLINE_MARGIN)
        for definition in (start, stop):
            self.assertIn('coopagents.space_wake watch --tool cursor', hook_script(definition['command']))
            self.assertNotIn('asyncRewake', definition)

    def test_cursor_merge_preserves_version_and_foreign_hooks_and_is_idempotent(self):
        foreign = {'command': './hooks/format.sh', 'timeout': 30}
        document = {'version': 1, 'hooks': {'stop': [foreign], 'afterFileEdit': [foreign]}}
        once = merge_cursor_hooks(document, hook_config(self.profile, 'cursor'))
        twice = merge_cursor_hooks(once, hook_config(self.profile, 'cursor'))
        self.assertEqual(once, twice)
        self.assertEqual(once['version'], 1)
        self.assertEqual(len(once['hooks']['stop']), 2)
        self.assertEqual(once['hooks']['afterFileEdit'], [foreign])
        self.assertEqual(merge_cursor_hooks(twice, {}), document)
        fresh = merge_cursor_hooks({}, hook_config(self.profile, 'cursor'))
        self.assertEqual(fresh['version'], 1)

    def test_cursor_hooks_installed_before_the_rename_are_replaced_and_removable(self):
        legacy = {'command': 'python -I -m crewmesh.space_wake watch --tool cursor --profile p'}
        foreign = {'command': './hooks/format.sh'}
        document = {'version': 1, 'hooks': {'stop': [foreign, legacy], 'sessionStart': [legacy]}}
        upgraded = merge_cursor_hooks(document, hook_config(self.profile, 'cursor'))
        commands = [d['command'] for groups in upgraded['hooks'].values() for d in groups]
        self.assertFalse(any('crewmesh.space_wake' in c for c in commands))
        self.assertEqual(sum('coopagents.space_wake' in hook_script(c) for c in commands), 2)
        self.assertEqual(merge_cursor_hooks(document, {}),
                         {'version': 1, 'hooks': {'stop': [foreign]}})

    def test_cursor_command_runs_as_a_subprocess(self):
        command = hook_config(self.profile, 'cursor')['stop'][0]['command']
        payload = json.dumps({'conversation_id': 'cursor-proc', 'hook_event_name': 'stop'}).encode()
        proc = subprocess.run(command, shell=True, input=payload, capture_output=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with WakeState(self.profile).connect() as c:
            row = c.execute("SELECT status FROM watchers WHERE session='cursor-proc'").fetchone()
        self.assertIsNotNone(row, 'The Cursor hook did not reach the watcher')
        self.assertEqual(row[0], 'deadline')

    def test_cursor_install_and_disable_cover_project_and_user_scopes(self):
        from unittest.mock import patch
        home = self.root / 'home-cursor'
        home.mkdir()
        project_hooks = self.project / '.cursor' / 'hooks.json'
        project_hooks.parent.mkdir(parents=True)
        project_hooks.write_text(json.dumps({'version': 1, 'hooks': {'afterFileEdit': [{'command': './hooks/format.sh'}]}}),
                                 encoding='utf-8')
        with patch.dict('os.environ', {'HOME': str(home)}):
            result = install(self.profile, 'cursor', project_dir=self.project, standby=400)
            self.assertEqual(result['settings'], str(project_hooks.absolute()))
            self.assertEqual(result['events'], ['sessionStart', 'stop'])
            document = json.loads(project_hooks.read_text(encoding='utf-8'))
            self.assertEqual(document['version'], 1)
            self.assertEqual(document['hooks']['afterFileEdit'][0]['command'], './hooks/format.sh')
            self.assertEqual(document['hooks']['stop'][0]['timeout'], 400 + space_wake.DEADLINE_MARGIN)
            self.assertTrue(list(project_hooks.parent.glob('hooks.json.coopagents-*.bak')), 'Previous settings are kept')
            self.assertTrue(disable('cursor', project_dir=self.project)['changed'])
            self.assertEqual(json.loads(project_hooks.read_text(encoding='utf-8')),
                             {'version': 1, 'hooks': {'afterFileEdit': [{'command': './hooks/format.sh'}]}})
            user_hooks = home / '.cursor' / 'hooks.json'
            result = install(self.profile, 'cursor', scope='user')
            self.assertEqual(result['settings'], str(user_hooks))
            self.assertEqual(json.loads(user_hooks.read_text(encoding='utf-8'))['version'], 1)
            self.assertTrue(disable('cursor', scope='user')['changed'])

    def test_cursor_missing_profile_is_refused(self):
        with self.assertRaises(WakeSetupError):
            install(None, 'cursor', project_dir=self.project)
        with self.assertRaises(WakeSetupError):
            install(None, 'cursor', scope='user')

    def test_cursor_preview_cli_accepts_explicit_tool_and_profile(self):
        from contextlib import redirect_stdout
        from unittest.mock import patch
        home = self.root / 'home-cursor2'
        home.mkdir()
        with patch.dict('os.environ', {'HOME': str(home), 'CLAUDECODE': '1'}):
            out = io.StringIO()
            with redirect_stdout(out):
                code = space_wake.main(['preview', '--tool', 'cursor', '--scope', 'user',
                                        '--profile', str(self.profile)])
            self.assertEqual(code, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result['version'], 1)
            self.assertEqual(result['settings'], str(home / '.cursor' / 'hooks.json'))
            self.assertIn('stop', result['hooks'])

    def test_zcode_checkpoint_and_wake_fragments_coexist_in_one_config(self):
        from coopagents.checkpoint_hook import config_fragment
        checkpoint = config_fragment('zcode')['hooks']['events']
        merged = merge_zcode_hooks({}, checkpoint)
        merged = merge_zcode_hooks(merged, hook_config(self.profile, 'zcode'))
        events = merged['hooks']['events']
        self.assertEqual(len(events['SessionStart']), 2, 'Checkpoint and wake baselines share the event')
        self.assertEqual(len(events['Stop']), 1)
        self.assertEqual(len(events['PostToolUse']), 1)
        self.assertEqual(len(events['UserPromptSubmit']), 1)
        removed = merge_zcode_hooks(merged, {})
        events = removed['hooks']['events']
        self.assertEqual(len(events['SessionStart']), 1, 'Wake disable keeps the checkpoint hook')
        self.assertNotIn('Stop', events)
        self.assertIn('PostToolUse', events)

    def test_codex_desktop_alias_installs_and_disables_as_codex(self):
        self.project.mkdir(parents=True, exist_ok=True)
        result = install(self.profile, 'codex-desktop', project_dir=self.project, standby=400)
        self.assertEqual(result['installed'], 'codex')
        hooks = json.loads((self.project / '.codex' / 'hooks.json').read_text(encoding='utf-8'))
        self.assertEqual(hooks['hooks']['Stop'][0]['hooks'][0]['timeout'], 400 + space_wake.DEADLINE_MARGIN)
        self.assertIn('--tool codex', hook_script(hooks['hooks']['Stop'][0]['hooks'][0]['command']))
        self.assertTrue(disable('codex-desktop', project_dir=self.project)['changed'])

    def test_codex_desktop_preview_cli_accepts_the_alias(self):
        from contextlib import redirect_stdout
        from unittest.mock import patch
        self.project.mkdir(parents=True, exist_ok=True)
        with patch.dict('os.environ', {'CLAUDECODE': '', 'CODEX_THREAD_ID': '', 'CODEX_SESSION_ID': ''}):
            out = io.StringIO()
            with redirect_stdout(out):
                code = space_wake.main(['preview', '--tool', 'codex-desktop', '--profile', str(self.profile),
                                        '--project-dir', str(self.project)])
            self.assertEqual(code, 0)
            result = json.loads(out.getvalue())
            self.assertIn('Stop', result['hooks'])
            self.assertTrue(result['settings'].endswith('.codex/hooks.json'))

    def test_install_and_disable_claude_and_codex(self):
        settings = self.project / '.claude' / 'settings.local.json'
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({'permissions': {'allow': ['Read']}}), encoding='utf-8')
        install(self.profile, 'claude', project_dir=self.project)
        document = json.loads(settings.read_text(encoding='utf-8'))
        handler = document['hooks']['Stop'][0]['hooks'][0]
        self.assertTrue(handler['asyncRewake'])
        self.assertEqual(handler['timeout'], space_wake.CLAUDE_HOOK_TIMEOUT)
        self.assertIn('coopagents.space_wake watch --tool claude', hook_script(handler['command']))
        self.assertNotIn('\\', handler['command'])
        self.assertEqual(document['permissions'], {'allow': ['Read']})
        self.assertTrue(list(settings.parent.glob('settings.local.json.coopagents-*.bak')), 'Previous settings are kept')
        self.assertTrue(disable('claude', project_dir=self.project)['changed'])
        self.assertEqual(json.loads(settings.read_text(encoding='utf-8')), {'permissions': {'allow': ['Read']}})
        install(self.profile, 'codex', project_dir=self.project, standby=400)
        codex = json.loads((self.project / '.codex' / 'hooks.json').read_text(encoding='utf-8'))
        self.assertEqual(codex['hooks']['Stop'][0]['hooks'][0]['timeout'], 400 + space_wake.DEADLINE_MARGIN)
        self.assertNotIn('asyncRewake', codex['hooks']['Stop'][0]['hooks'][0])
        state = WakeState(self.profile)
        state.set_standby(3600)
        self.assertEqual(state.standby(), 400)


class LiveWakeTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.owner, self.member = self.live.bootstrap()
        self.profile = evidence('live') / 'profile.json'
        private_write(self.profile, dict(schema_version=1, origin=self.live.url, **self.owner))

    def send(self, body='Need schema'):
        status, result, _ = self.live.request('POST', '/api/operations/send_request', self.member['agent_token'], dict(
            request_key=str(uuid4()), receiver_member_id=self.owner['member_id'], context_version=1, body=body))
        self.assertEqual(status, 200)
        return result

    def test_remote_digest_over_http(self):
        self.send()
        self.assertEqual(remote_digest(self.profile)['counts']['request'], 1)
        wrong = self.profile.with_name('member.json')
        private_write(wrong, dict(schema_version=1, origin=self.live.url, room_id=self.owner['room_id'],
                                  member_id=self.owner['member_id'], agent_token=self.member['agent_token']))
        with self.assertRaises(AuthDenied):
            remote_digest(wrong)

    def test_watcher_exits_when_its_session_process_dies(self):
        # A stand-in "session" process launches the hook, then is killed like a closed terminal.
        script = ('import subprocess, sys, json, time\n'
                  'p = subprocess.Popen([sys.executable, "-I", "-m", "coopagents.space_wake", "watch", "--tool", "claude", "--profile", sys.argv[1]],'
                  ' stdin=subprocess.PIPE)\n'
                  'p.stdin.write(json.dumps({"session_id": "dying", "hook_event_name": "Stop"}).encode()); p.stdin.close()\n'
                  'print(p.pid, flush=True)\n'
                  'time.sleep(600)\n')
        session = subprocess.Popen([sys.executable, '-I', '-c', script, str(self.profile)], stdout=subprocess.PIPE)
        watcher_pid = int(session.stdout.readline())
        state = WakeState(self.profile)
        for _ in range(100):
            with state.connect() as c:
                if c.execute("SELECT 1 FROM watchers WHERE session='dying'").fetchone():
                    break
            threading.Event().wait(.1)
        session.kill()
        session.wait(10)
        for _ in range(150):
            if not space_wake.pid_alive(watcher_pid):
                break
            threading.Event().wait(.1)
        self.assertFalse(space_wake.pid_alive(watcher_pid), 'Orphaned watcher kept running')
        with state.connect() as c:
            self.assertEqual(c.execute("SELECT status FROM watchers WHERE session='dying'").fetchone()[0], 'owner_exited')
        self.send()
        with state.connect() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM notified').fetchone(), 'Nothing was consumed by the dead session')

    def test_hook_subprocess_wakes_on_arrival_and_never_leaks_body(self):
        holder = {}
        def run():
            holder['proc'] = subprocess.run(
                [sys.executable, '-I', '-c',
                 'import sys; from coopagents import space_wake as w; w.CLAUDE_HOOK_TIMEOUT=w.DEADLINE_MARGIN+60;'
                 'sys.exit(w.main(sys.argv[1:]))',
                 'watch', '--tool', 'claude', '--profile', str(self.profile)],
                input=json.dumps({'session_id': 'live', 'hook_event_name': 'Stop'}).encode(),
                capture_output=True, timeout=90)
        thread = threading.Thread(target=run)
        thread.start()
        threading.Event().wait(2)
        self.send(body='PRIVATE-TEAMMATE-TEXT')
        thread.join(90)
        proc = holder['proc']
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn(b'1 new request addressed to you', proc.stderr)
        self.assertNotIn(b'PRIVATE-TEAMMATE-TEXT', proc.stderr + proc.stdout)


if __name__ == '__main__':
    unittest.main()
