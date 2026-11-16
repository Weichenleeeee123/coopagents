"""Private process-adapter checks; Python children are never native evidence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import importlib.util
import io
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import tomllib
import unittest
from unittest.mock import patch
from uuid import uuid4

import cold_start_acceptance as cold


MODULE = Path(__file__).with_name('workflow_native_process.py')
ROOT = Path(__file__).resolve().parents[2]


class WorkflowNativeProcessTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'the isolated native process adapter is missing')
        spec = importlib.util.spec_from_file_location('workflow_native_process', MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.root = ROOT / '.local/test-evidence' / ('native-process-' + uuid4().hex)
        self.root.mkdir(parents=True)
        self.source = self.root / 'codex-source'
        self.source.mkdir()
        self.settings = self.root / 'claude-source' / 'settings.json'
        self.settings.parent.mkdir()
        self.settings.write_text(json.dumps({'model': 'configured-claude',
            'env': {'ANTHROPIC_AUTH_TOKEN': 'synthetic-claude-auth'}, 'hooks': {'Stop': []}}), encoding='utf-8')
        (self.source / 'config.toml').write_text('model = "configured-codex"\nmodel_provider = "selected"\n'
            '[model_providers.selected]\nname = "Selected"\nbase_url = "https://example.invalid"\n'
            'env_key = "WORKFLOW_SELECTED_AUTH"\n[mcp_servers.personal]\ncommand = "must-not-copy"\n', encoding='utf-8')
        (self.source / 'auth.json').write_text('{"synthetic":"auth"}', encoding='utf-8')
        self.project = self.root / 'project'
        self.project.mkdir()
        self.token = 'synthetic-personal-mcp-token'

    def prepare(self, harness='codex', tools=None, run=None):
        with patch.dict(os.environ, {'WORKFLOW_SELECTED_AUTH': 'selected-provider-secret',
                                     'WORKFLOW_UNRELATED_SECRET': 'must-not-inherit'}):
            return self.module.prepare_native(run or self.root / ('run-' + uuid4().hex), harness,
                sys.executable, 'http://127.0.0.1:54321/mcp', self.token,
                ['whoami', 'read_team'] if tools is None else tools,
                codex_source=self.source, claude_settings=self.settings)

    def test_prepare_codex_reuses_existing_provider_isolation_and_single_server(self):
        with patch.object(cold, 'prepare_homes', wraps=cold.prepare_homes) as prepare:
            participant = self.prepare()
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(prepare.call_args.kwargs['tool'], 'codex')
        config = tomllib.loads((Path(participant['env']['CODEX_HOME']) / 'config.toml').read_text())
        self.assertEqual(config['model'], 'configured-codex')
        self.assertEqual(set(config['model_providers']), {'selected'})
        self.assertEqual(set(config['mcp_servers']), {'coopagents_workflow'})
        server = config['mcp_servers']['coopagents_workflow']
        self.assertEqual(server['url'], 'http://127.0.0.1:54321/mcp')
        self.assertEqual(server['http_headers'], {'Authorization': 'Bearer ' + self.token})
        self.assertEqual(server['enabled_tools'], ['whoami', 'read_team'])
        self.assertNotIn('approval_policy', config)
        self.assertNotIn('tools', server, 'tool approvals belong to the invocation, not persisted config')
        self.assertEqual(participant['env']['WORKFLOW_SELECTED_AUTH'], 'selected-provider-secret')
        self.assertNotIn('WORKFLOW_UNRELATED_SECRET', participant['env'])
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', participant['env'])
        self.assertIsInstance(json.loads(json.dumps(participant)), dict)
        self.assertEqual((self.source / 'auth.json').read_text(), '{"synthetic":"auth"}')

    def test_prepare_claude_keeps_model_and_only_its_selected_credentials(self):
        participant = self.prepare('claude')
        config = json.loads(Path(participant['mcp_config']).read_text())
        self.assertEqual(set(config['mcpServers']), {'coopagents_workflow'})
        self.assertEqual(config['mcpServers']['coopagents_workflow'], {'type': 'http',
            'url': 'http://127.0.0.1:54321/mcp', 'headers': {'Authorization': 'Bearer ' + self.token}})
        isolated = json.loads((Path(participant['env']['CLAUDE_CONFIG_DIR']) / 'settings.json').read_text())
        self.assertEqual(isolated, {'model': 'configured-claude'})
        self.assertEqual(participant['env']['ANTHROPIC_AUTH_TOKEN'], 'synthetic-claude-auth')
        self.assertNotIn('WORKFLOW_SELECTED_AUTH', participant['env'])
        self.assertNotIn('WORKFLOW_UNRELATED_SECRET', participant['env'])
        self.assertIn('hooks', json.loads(self.settings.read_text()))

    def test_codex_windows_private_sandbox_never_copies_global_permissions_or_trust(self):
        original = (self.source / 'config.toml').read_text()
        (self.source / 'config.toml').write_text('sandbox_mode = "danger-full-access"\n'
            'approval_policy = "never"\n' + original +
            '[projects."C:/synthetic-source-project"]\ntrust_level = "trusted"\n'
            '[windows]\nsandbox = "elevated"\n', encoding='utf-8')
        for windows in (True, False):
            with self.subTest(windows=windows), patch.object(self.module, '_WINDOWS', windows, create=True):
                participant = self.prepare()
            config = tomllib.loads((Path(participant['env']['CODEX_HOME']) / 'config.toml').read_text())
            self.assertEqual(config['sandbox_mode'], 'workspace-write')
            self.assertEqual(config.get('windows'), {'sandbox': 'unelevated'} if windows else None)
            self.assertNotIn('approval_policy', config)
            self.assertNotIn('projects', config)
            self.assertEqual(config['model'], 'configured-codex')
            self.assertEqual(config['model_provider'], 'selected')
        source = tomllib.loads((self.source / 'config.toml').read_text())
        self.assertEqual(source['sandbox_mode'], 'danger-full-access')
        self.assertEqual(source['approval_policy'], 'never')
        self.assertEqual(source['windows']['sandbox'], 'elevated')
        self.assertEqual(len(source['projects']), 1)

    def test_preparation_and_turn_directories_are_exclusive_and_preserved(self):
        run = self.root / 'reserved-run'
        run.mkdir()
        sentinel = run / 'keep.txt'
        sentinel.write_text('preserved')
        with self.assertRaises(FileExistsError):
            self.prepare(run=run)
        self.assertEqual(sentinel.read_text(), 'preserved')
        participant = self.prepare()
        turn = self.root / 'reserved-turn'
        turn.mkdir()
        sentinel = turn / 'keep.txt'
        sentinel.write_text('also preserved')
        with self.assertRaises(FileExistsError):
            self.module.run_turn(participant, 'Goal', self.project, turn)
        self.assertEqual(sentinel.read_text(), 'also preserved')

    def test_invalid_setup_inputs_fail_before_copying_credentials(self):
        for changes in ({'harness': 'other'}, {'enabled_tools': ['read_team', 'read_team']},
                        {'enabled_tools': ['read_team; shell']}, {'server_url': 'http://user:password@localhost:80/mcp'},
                        {'server_url': 'file:///private'}, {'token': 'line\nbreak'}):
            args = dict(run=self.root / uuid4().hex, harness='codex', executable=sys.executable,
                server_url='http://127.0.0.1:54321/mcp', token=self.token, enabled_tools=['whoami'],
                codex_source=self.source, claude_settings=self.settings)
            args.update(changes)
            with self.subTest(changes=list(changes)):
                with patch.object(cold, 'prepare_homes') as prepare:
                    with self.assertRaises(ValueError):
                        self.module.prepare_native(**args)
                    prepare.assert_not_called()

    def command(self, harness, resume=None):
        participant = self.prepare(harness)
        fake = {'exit_code': 0, 'timed_out': False, 'cancelled': False, 'events': [], 'started_at': 1, 'finished_at': 2,
                'event_path': 'private-events', 'stderr_path': 'private-stderr'}
        with patch.object(self.module, '_capture', return_value=fake) as capture:
            result = self.module.run_turn(participant, 'Implement the profile form.', self.project,
                self.root / ('command-' + uuid4().hex), resume=resume)
        command = capture.call_args.args[0]
        self.assertNotIn(self.token, json.dumps(command))
        self.assertNotIn('selected-provider-secret', json.dumps(command))
        self.assertNotIn('command', result)
        return participant, command

    def test_codex_new_and_resume_use_normal_sandbox_and_invocation_tool_approvals(self):
        for resume in (None, 'session-from-external-trace'):
            participant, command = self.command('codex', resume)
            self.assertIn('--json', command)
            self.assertIn('--no-daemon', command)
            self.assertNotIn('features.prefer_mxc=true', command)
            self.assertEqual(command[-1], '-')
            if resume:
                self.assertEqual(command[command.index('exec'):command.index('exec') + 3],
                                 ['exec', 'resume', resume])
                self.assertNotIn('--sandbox', command, 'exec resume has no --sandbox option')
                self.assertNotIn('-C', command, 'resume uses the verified project cwd')
                override = 'sandbox_mode="workspace-write"'
                self.assertIn(override, command)
                self.assertLess(command.index(override), command.index('exec'))
            else:
                self.assertNotIn('resume', command)
                self.assertEqual(command[:3], [participant['executable'], '--no-daemon', 'exec'])
                self.assertEqual(command[command.index('--sandbox') + 1], 'workspace-write')
                self.assertGreater(command.index('--sandbox'), command.index('exec'),
                                   'top-level sandbox does not propagate into exec')
                self.assertGreater(command.index('-C'), command.index('exec'))
                self.assertEqual(command[command.index('-C') + 1], str(self.project))
            for tool in participant['enabled_tools']:
                self.assertIn('mcp_servers.coopagents_workflow.tools.' + tool + '.approval_mode="approve"', command)
            for forbidden in ('--model', '-m', '--dangerously-bypass-approvals-and-sandbox',
                              '--dangerously-bypass-hook-trust', '--approve-for-me', '--ignore-rules'):
                self.assertNotIn(forbidden, command)
            self.assertNotIn('approval_policy="never"', command)

    def test_claude_new_and_resume_confine_files_and_allow_only_arm_tools(self):
        for resume in (None, 'session-from-external-trace'):
            participant, command = self.command('claude', resume)
            for flag in ('--print', '--verbose', '--strict-mcp-config', '--restricted'):
                self.assertIn(flag, command)
            self.assertEqual(command[command.index('--tools') + 1], 'Read,Edit,Write')
            self.assertEqual(command[command.index('--permission-prompts') + 1], 'none')
            self.assertEqual(command[command.index('--mcp-config') + 1], participant['mcp_config'])
            self.assertEqual(command[command.index('--settings') + 1],
                             str(Path(participant['env']['CLAUDE_CONFIG_DIR']) / 'settings.json'))
            self.assertEqual(set(command[command.index('--allowedTools') + 1].split(',')),
                {'Read(./**)', 'Edit(./**)', 'Write(./**)', 'mcp__coopagents_workflow__whoami',
                 'mcp__coopagents_workflow__read_team'})
            if resume:
                self.assertEqual(command[command.index('--resume') + 1], resume)
            self.assertNotIn('--model', command)
            self.assertNotIn('--dangerously-skip-permissions', command)
            self.assertNotIn('Bash', command)
            self.assertNotIn('PowerShell', command)

    def test_real_python_child_streams_timestamped_json_and_retains_raw_and_stderr(self):
        participant = self.prepare()
        child = [sys.executable, '-u', '-c', 'import json,sys; p=sys.stdin.read(); '
                 'print(json.dumps({"type":"started","prompt_length":len(p)})); '
                 'print("not-json"); print(json.dumps([1,2])); print("stderr-fixture",file=sys.stderr)']
        turn = self.root / 'stream-turn'
        output = io.StringIO()
        with patch.object(self.module, '_command', return_value=child), redirect_stdout(output):
            result = self.module.run_turn(participant, 'A private tool-free goal', self.project, turn)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(result['exit_code'], 0)
        self.assertFalse(result['timed_out'])
        self.assertFalse(result['cancelled'])
        self.assertEqual(len(result['events']), 2)
        self.assertEqual(result['events'][1]['event'], [1, 2])
        for event in result['events']:
            self.assertLessEqual(result['started_at'], event['at'])
            self.assertLessEqual(event['at'], result['finished_at'])
        retained = [json.loads(line) for line in Path(result['event_path']).read_text().splitlines()]
        self.assertEqual(retained, result['events'])
        self.assertIn('not-json', (turn / 'stdout.log').read_text())
        self.assertNotIn('not-json', Path(result['event_path']).read_text())
        self.assertEqual(Path(result['stderr_path']).read_text().strip(), 'stderr-fixture')
        self.assertEqual((turn / 'prompt.txt').read_text(), 'A private tool-free goal')
        if os.name != 'nt':
            for path in turn.iterdir():
                self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_events_are_flushed_while_the_child_is_still_running(self):
        participant = self.prepare()
        child = [sys.executable, '-u', '-c', 'import json,time; print(json.dumps({"first":True}),flush=True); '
                 'time.sleep(2); print(json.dumps({"second":True}),flush=True)']
        turn = self.root / 'realtime-turn'
        with patch.object(self.module, '_command', return_value=child), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.module.run_turn, participant, 'Goal', self.project, turn, 10)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if (turn / 'events.jsonl').exists() and (turn / 'events.jsonl').stat().st_size:
                    break
                time.sleep(.02)
            self.assertFalse(future.done(), 'events must be available before process exit')
            self.assertTrue(json.loads((turn / 'events.jsonl').read_text().splitlines()[0])['event']['first'])
            self.assertEqual(len(future.result(timeout=10)['events']), 2)

    def test_timeout_stops_the_owned_child_tree_and_preserves_partial_evidence(self):
        participant = self.prepare()
        heartbeat = self.root / 'child-heartbeat.txt'
        worker = 'from pathlib import Path; import time; p=Path(' + repr(str(heartbeat)) + '); '\
                 'p.write_text("started"); time.sleep(3); p.write_text("survived-timeout")'
        script = 'import subprocess,sys,time,json; child=subprocess.Popen([sys.executable,"-u","-c",' + repr(worker) + ']); '\
                 'print(json.dumps({"child_pid":child.pid}),flush=True); time.sleep(30)'
        child = [sys.executable, '-u', '-c', script]
        turn = self.root / 'timeout-turn'
        start = time.monotonic()
        with patch.object(self.module, '_command', return_value=child):
            result = self.module.run_turn(participant, 'Retained private prompt', self.project, turn, timeout=1)
        self.assertTrue(result['timed_out'])
        self.assertFalse(result['cancelled'])
        self.assertLess(time.monotonic() - start, 8)
        self.assertTrue(result['events'])
        self.assertTrue(Path(result['event_path']).is_file())
        self.assertTrue(Path(result['stderr_path']).is_file())
        self.assertEqual((turn / 'prompt.txt').read_text(), 'Retained private prompt')
        time.sleep(3)
        self.assertNotEqual(heartbeat.read_text() if heartbeat.exists() else '', 'survived-timeout')

    def test_cancellation_stops_only_owned_tree_and_keeps_all_evidence(self):
        self.assertIn('cancel_event', inspect.signature(self.module.run_turn).parameters,
                      'native turns need an explicit optional cancellation signal')
        participant = self.prepare()
        heartbeat = self.root / 'cancel-child-heartbeat.txt'
        worker = 'from pathlib import Path; import time; p=Path(' + repr(str(heartbeat)) + '); '\
                 'p.write_text("started"); time.sleep(3); p.write_text("survived-cancellation")'
        script = 'import subprocess,sys,time,json; child=subprocess.Popen([sys.executable,"-u","-c",' + repr(worker) + ']); '\
                 'print("raw-before-cancel",flush=True); print("stderr-before-cancel",file=sys.stderr,flush=True); '\
                 'print(json.dumps({"session":"synthetic-session","child_pid":child.pid}),flush=True); time.sleep(30)'
        child = [sys.executable, '-u', '-c', script]
        control_path = self.root / 'unrelated-process.txt'
        control_script = 'from pathlib import Path; import time; time.sleep(1); Path(' + repr(str(control_path)) + ').write_text("continued")'
        control = subprocess.Popen([sys.executable, '-u', '-c', control_script], env=participant['env'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(control.wait, timeout=5)
        turn, cancel = self.root / 'cancel-turn', threading.Event()
        with patch.object(self.module, '_command', return_value=child), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.module.run_turn, participant, 'Retain this interrupted goal',
                                 self.project, turn, 30, cancel_event=cancel)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if (turn / 'events.jsonl').exists() and (turn / 'events.jsonl').stat().st_size:
                    break
                time.sleep(.02)
            self.assertTrue((turn / 'events.jsonl').stat().st_size)
            start = time.monotonic()
            cancel.set()
            result = future.result(timeout=5)
        self.assertLess(time.monotonic() - start, 3)
        self.assertTrue(result['cancelled'])
        self.assertFalse(result['timed_out'])
        # Windows Job Object closure can produce exit code 0. The explicit
        # cancellation flag must still exclude this turn from normal success.
        self.assertFalse(result['exit_code'] == 0 and not result['cancelled'] and not result['timed_out'])
        self.assertEqual(result['events'][0]['event']['session'], 'synthetic-session')
        self.assertEqual((turn / 'prompt.txt').read_text(), 'Retain this interrupted goal')
        self.assertIn('raw-before-cancel', (turn / 'stdout.log').read_text())
        self.assertIn('stderr-before-cancel', Path(result['stderr_path']).read_text())
        self.assertEqual(json.loads(Path(result['event_path']).read_text().splitlines()[0]), result['events'][0])
        self.assertEqual(control.wait(timeout=5), 0)
        self.assertEqual(control_path.read_text(), 'continued')
        time.sleep(3)
        self.assertNotEqual(heartbeat.read_text() if heartbeat.exists() else '', 'survived-cancellation')

    def test_failed_launch_retains_private_files_without_returning_command_or_secret(self):
        participant = self.prepare()
        participant['executable'] = str(self.root / ('missing-' + self.token + '.exe'))
        turn = self.root / 'failed-turn'
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.module.run_turn(participant, 'Private prompt', self.project, turn)
        self.assertIsNone(result['exit_code'])
        self.assertFalse(result['timed_out'])
        self.assertEqual(result['events'], [])
        self.assertNotIn(self.token, json.dumps(result))
        self.assertEqual(output.getvalue(), '')
        self.assertTrue((turn / 'prompt.txt').is_file())
        self.assertIn('FileNotFoundError', Path(result['stderr_path']).read_text())
        self.assertNotIn(self.token, Path(result['stderr_path']).read_text())

    def test_invalid_turn_inputs_never_launch_a_process(self):
        participant = self.prepare()
        for changes in ({'timeout': 0}, {'timeout': True}, {'resume': '--dangerous'}, {'prompt': None},
                        {'cancel_event': True}):
            args = dict(participant=participant, prompt='Goal', project=self.project,
                        turn_dir=self.root / uuid4().hex, timeout=10)
            args.update(changes)
            with patch.object(self.module.subprocess, 'Popen') as popen:
                with self.assertRaises(ValueError):
                    self.module.run_turn(**args)
                popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
