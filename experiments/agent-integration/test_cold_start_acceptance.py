"""Safety and evidence regressions; these do not consume model quota."""
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import time
import subprocess
import unittest
from uuid import uuid4
from contextlib import ExitStack, redirect_stdout
import io
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('cold_start_acceptance', Path(__file__).with_name('cold_start_acceptance.py'))


class ColdStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(cls.runner)

    def test_native_commands_keep_sandbox_and_default_model(self):
        root = Path('C:/synthetic/run') if os.name == 'nt' else Path('/synthetic/run')
        for tool in ('codex', 'claude'):
            command = self.runner.model_command(tool, tool, root, root / 'python', setup=True)
            joined = ' '.join(command)
            self.assertNotIn('bypass', joined.lower())
            self.assertNotIn('--model', command)
            self.assertNotIn('-m', command)
            if tool == 'codex':
                self.assertIn('workspace-write', command)
                self.assertEqual('features.prefer_mxc=true' in command, os.name == 'nt')
            else:
                self.assertIn('--allowedTools', command)
                self.assertNotIn('Bash(*)', joined)

    def test_collaboration_uses_read_only_and_exact_registered_tool_approvals(self):
        root = Path(__file__).resolve().parents[2] / '.local/cold-start-tests' / uuid4().hex
        profile = root / 'coopagents-home/member/profile.json'
        profile.parent.mkdir(parents=True)
        profile.write_text(json.dumps({'room_id': '12345678-room'}))
        config = root / 'codex-home/config.toml'
        config.parent.mkdir()
        python = root / 'python'
        entry = {'command': str(python), 'args': ['-m', 'coopagents.space_bridge', '--profile', str(profile)]}
        config.write_text('mcp_servers = ' + self.runner.toml_value({'coopagents_12345678': entry}))
        command = self.runner.model_command('codex', 'codex', root, python, require=('whoami', 'read_team'))
        self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
        settings = [command[i + 1] for i, arg in enumerate(command)
                    if arg == '-c' and command[i + 1].startswith('mcp_servers.')]
        self.assertEqual(settings, [
            'mcp_servers.coopagents_12345678.enabled_tools=["whoami", "read_team"]',
            'mcp_servers.coopagents_12345678.tools.whoami.approval_mode="approve"',
            'mcp_servers.coopagents_12345678.tools.read_team.approval_mode="approve"'])
        self.assertNotIn('send_request', ' '.join(command))
        for foreign in ({'personal': entry}, {'coopagents_12345678': dict(entry, command='foreign')},
                        {'coopagents_12345678': entry, 'personal': entry},
                        {'coopagents_12345678': dict(entry, args=['-m', 'other'])}):
            config.write_text('mcp_servers = ' + self.runner.toml_value(foreign))
            with self.assertRaises(ValueError):
                self.runner.model_command('codex', 'codex', root, python, require=('whoami',))

    def test_claude_setup_allows_only_equivalent_exact_runtime_executable(self):
        root = Path('/synthetic/run')
        python = PureWindowsPath('C:/Users/Synthetic User/project/.venv/Scripts/python.exe')
        command = self.runner.model_command('claude', 'claude', root, python, setup=True)
        allowed = command[command.index('--allowedTools') + 1].split(',')
        self.assertEqual(allowed, ['Read',
            'Bash("C:\\Users\\Synthetic User\\project\\.venv\\Scripts\\python.exe" -m coopagents.space_runtime:*)',
            'Bash("C:/Users/Synthetic User/project/.venv/Scripts/python.exe" -m coopagents.space_runtime:*)',
            'Bash("/c/Users/Synthetic User/project/.venv/Scripts/python.exe" -m coopagents.space_runtime:*)'])
        self.assertTrue(all(rule.endswith('" -m coopagents.space_runtime:*)')
                            for rule in allowed if rule.startswith('Bash(')))
        command = self.runner.model_command('claude', 'claude', root, python)
        self.assertEqual(command[command.index('--allowedTools') + 1], 'Read')
        posix = self.runner.model_command('claude', 'claude', root, PurePosixPath('/venv/bin/python'), setup=True)
        self.assertEqual(posix[posix.index('--allowedTools') + 1],
                         'Read,Bash("/venv/bin/python" -m coopagents.space_runtime:*)')

    def test_claude_required_permissions_use_verified_exact_server_and_tools(self):
        root = Path(__file__).resolve().parents[2] / '.local/cold-start-tests' / uuid4().hex
        profile = root / 'coopagents-home/member/profile.json'
        profile.parent.mkdir(parents=True)
        profile.write_text(json.dumps({'room_id': '12345678-room'}))
        config = root / 'claude-home/.claude.json'
        config.parent.mkdir()
        python = root / 'python'
        entry = {'command': str(python), 'args': ['-m', 'coopagents.space_bridge', '--profile', str(profile)]}
        config.write_text(json.dumps({'mcpServers': {'coopagents_12345678': entry}}))
        command = self.runner.model_command('claude', 'claude', root, python, require=('whoami', 'read_team'))
        self.assertEqual(command[command.index('--allowedTools') + 1],
                         'Read,mcp__coopagents_12345678__whoami,mcp__coopagents_12345678__read_team')
        for servers in ({'foreign': entry}, {'coopagents_12345678': dict(entry, command='foreign')},
                        {'coopagents_12345678': entry, 'foreign': entry}):
            config.write_text(json.dumps({'mcpServers': servers}))
            with self.assertRaises(ValueError):
                self.runner.model_command('claude', 'claude', root, python, require=('whoami',))

    def test_invitation_requires_exact_successful_native_command_result(self):
        profile = Path('/synthetic/member/profile.json')
        command = self.runner.invitation_command(Path('/venv/python'), profile)
        invitation = {'message': 'synthetic invitation', 'invitation_file': str(profile.with_name('invitation-test.json'))}
        def events(command=command, result=invitation, failed=False):
            return [
                {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'invite',
                    'name': 'Bash', 'input': {'command': command}}]}},
                {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'invite',
                    'is_error': failed, 'content': json.dumps(result)}]}}]
        self.assertEqual(self.runner.native_invitation_result('claude', events(), command, profile), invitation)
        for rejected in (events(command='echo invented'), events(failed=True),
                         events(result={'isError': True, **invitation}),
                         events(result=dict(invitation, invitation_file='/foreign/invitation.json')),
                         [{'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': json.dumps(invitation)}]}}]):
            with self.assertRaises(ValueError):
                self.runner.native_invitation_result('claude', rejected, command, profile)
        codex = [{'type': 'item.completed', 'item': {'type': 'command_execution', 'command': command,
                  'exit_code': 0, 'aggregated_output': json.dumps(invitation)}}]
        self.assertEqual(self.runner.native_invitation_result('codex', codex, command, profile), invitation)

    def test_claude_nonstructured_messages_and_blocks_do_not_crash_or_prove_tools(self):
        noise = [{'type': kind, 'message': message}
                 for kind in ('system', 'assistant', 'user')
                 for message in ('permission denied', None, [], 42, {}, {'content': 'denied'},
                                 {'content': [None, 'denied', 42]})]
        noise.append({'type': 'system', 'subtype': 'permission_denied'})
        events = noise + [
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': 'ok', 'name': 'mcp__coopagents_x__whoami'},
                {'type': 'tool_use', 'id': 'foreign', 'name': 'mcp__unrelated_x__read_team'},
                {'type': 'tool_use', 'id': 'denied', 'name': 'mcp__coopagents_x__reply'}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'ok', 'content': '{}'},
                {'type': 'tool_result', 'tool_use_id': 'foreign', 'content': '{}'},
                {'type': 'tool_result', 'tool_use_id': 'denied', 'is_error': True}]}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'actual answer'}]}}]
        self.assertEqual(self.runner.successful_tools('claude', events), {'whoami'})
        self.assertEqual(self.runner.assistant_text('claude', events), 'actual answer')

    def test_host_reply_authorizes_only_exact_synthetic_file_read(self):
        answer = Path(__file__).resolve().parents[2] / '.local/synthetic answer.txt'
        prompt = self.runner.host_reply_prompt('codex', 'nonce', answer)
        self.assertIn(str(answer), prompt)
        self.assertIn('Get-Content -LiteralPath' if os.name == 'nt' else 'cat --', prompt)
        self.assertNotIn('Do not execute commands', prompt)
        self.assertIn('Do not execute any other commands', prompt)
        self.assertIn('Do not change files', prompt)

    def test_failed_owned_host_stop_fails_full_and_partial_acceptance(self):
        # Exercise main's real finalization path without calling native models.
        for partial, collaboration_status in ((False, 'passed'), (True, 'host_verified_partial')):
            with self.subTest(partial=partial), ExitStack() as patches:
                roots = {}
                def prepare(root, *args, tool=None, **kwargs):
                    root.mkdir(parents=True)
                    (root / 'profile.json').write_text('{}', encoding='utf-8')
                    roots[tool] = root
                    return {'SYNTHETIC_ROOT': str(root)}
                def profile(path):
                    tool = 'claude' if Path(path).parent == roots['claude'] else 'codex'
                    return {'room_id': 'synthetic-room', 'member_id': tool, 'control_token': 'synthetic'}
                def native_registration(env, *args):
                    return {'profile': str(Path(env['SYNTHETIC_ROOT']) / 'profile.json')}
                def process(command, **kwargs):
                    stopped = 'stop' in command
                    return subprocess.CompletedProcess(command, 1 if stopped else 0,
                                                       stdout='' if '--porcelain' in command else 'synthetic-commit')
                overrides = {'codex_tool_approvals': lambda *a: [], 'claude_tool_approvals': lambda *a: [],
                    'native_invitation_result': lambda *a: {'message': 'synthetic invitation'},
                    'prepare_homes': prepare, 'bounded': lambda *a, **k: 0,
                    'registrations': native_registration, 'events_from': lambda *a: [],
                    'successful_tools': lambda *a: {'whoami', 'read_team', 'send_request', 'read_inbox', 'reply'},
                    'native_identity_proven': lambda *a: True, 'snapshot': lambda *a: {},
                    'network_proven': lambda *a: True, 'diagnostics_proven': lambda *a: True,
                    'exchange_proven': lambda *a: True,
                    'assistant_text': lambda *a: (roots['claude'] / 'repo/acceptance-answer.txt').read_text()}
                for name, replacement in overrides.items():
                    patches.enter_context(patch.object(self.runner, name, replacement))
                patches.enter_context(patch.object(self.runner.subprocess, 'run', process))
                patches.enter_context(patch('coopagents.spaces.read_profile', profile))
                patches.enter_context(patch('coopagents.spaces.read_json', return_value={'network': 'local'}))
                output = patches.enter_context(redirect_stdout(io.StringIO()))
                arguments = ['--host', 'claude', '--network', 'local', '--codex', 'synthetic-codex', '--claude', 'synthetic-claude']
                if partial:
                    arguments.append('--stop-after-host-verification')
                code = self.runner.main(arguments)
                report = json.loads((roots['claude'].parent / 'summary.json').read_text())
                self.assertEqual(code, 1)
                self.assertFalse(report['host_stopped'])
                self.assertEqual(report['status'], 'shutdown_failed')
                self.assertEqual(report['collaboration_status'], collaboration_status)
                self.assertIn('Result: shutdown_failed', output.getvalue())

    def test_runner_rejects_nonisolated_python_before_model_execution(self):
        with patch.object(self.runner.sys, 'prefix', self.runner.sys.base_prefix), \
                patch.object(self.runner, 'bounded') as model, \
                redirect_stdout(io.StringIO()), patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                self.runner.main(['--prepare-only', '--codex', sys.executable, '--claude', sys.executable])
        self.assertEqual(error.exception.code, 2)
        model.assert_not_called()

    def test_partial_host_cli_is_explicit_and_preparation_spends_no_quota(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('cold_start_acceptance.py')),
                                 '--host', 'codex', '--stop-after-host-verification', '--prepare-only',
                                 '--codex', sys.executable, '--claude', sys.executable],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('PASS', result.stdout)

    def test_zero_exit_and_setup_prose_never_mark_create_stage_passed(self):
        root = Path(__file__).resolve().parents[2] / '.local' / 'cold-start-tests' / uuid4().hex
        from coopagents.spaces import private_directory
        private_directory(root)
        fake = root / ('fake.cmd' if os.name == 'nt' else 'fake.sh')
        event = json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Setup passed'}})
        fake.write_text('@echo off\n' + 'echo ' + event + '\nexit /b 0\n' if os.name == 'nt' else
                        '#!/bin/sh\nprintf \'%s\\n\' \'' + event + '\'\n', encoding='utf-8')
        if os.name != 'nt':
            fake.chmod(0o700)
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('cold_start_acceptance.py')),
                                 '--host', 'codex', '--stop-after-host-verification', '--codex', str(fake),
                                 '--claude', sys.executable, '--timeout', '10'],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('01-create: FAIL', result.stdout)
        self.assertNotIn('01-create: PASS', result.stdout)

    def test_prose_and_failed_tool_calls_do_not_count(self):
        events = [
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'whoami read_team passed'}},
            {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'tool': 'whoami', 'error': {'message': 'denied'}}},
        ]
        self.assertEqual(self.runner.successful_tools('codex', events), set())

    def test_real_child_timeout_is_bounded_and_retains_evidence(self):
        root = Path(__file__).resolve().parents[2] / '.local' / 'cold-start-tests' / uuid4().hex
        from coopagents.spaces import private_directory
        private_directory(root)
        started = time.monotonic()
        result = self.runner.bounded([sys.executable, '-c', 'import time;time.sleep(10)'],
                                     'synthetic prompt', root / 'child.log', dict(os.environ), root, 1)
        self.assertEqual(result, 'timeout')
        self.assertLess(time.monotonic() - started, 8)
        self.assertTrue((root / 'child.log').exists())
        self.assertTrue((root / 'child.prompt.txt').exists())

    def test_codex_completed_native_tool_evidence(self):
        events = [{'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'tool': name,
                   'status': 'completed', 'error': None, 'result': {'content': []}}}
                  for name in ('whoami', 'read_team')]
        self.assertEqual(self.runner.successful_tools('codex', events), {'whoami', 'read_team'})

    def test_identity_requires_actual_matching_native_response(self):
        expected = {'room_id': 'room', 'member_id': 'member'}
        def events(identity):
            return [{'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'tool': 'whoami',
                     'status': 'completed', 'error': None, 'result': {'content': [
                         {'type': 'text', 'text': json.dumps({'me': identity})}]}}}]
        self.assertTrue(self.runner.native_identity_proven('codex', events(expected), expected))
        self.assertFalse(self.runner.native_identity_proven('codex', events(dict(expected, member_id='wrong')), expected))
        self.assertFalse(self.runner.native_identity_proven('codex', events(dict(expected, room_id='wrong')), expected))
        self.assertFalse(self.runner.native_identity_proven('codex', [], expected))

    def test_nested_native_error_cannot_pass_identity_or_tool_checks(self):
        identity = {'room_id': 'room', 'member_id': 'member'}
        events = [{'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'tool': 'whoami',
                   'status': 'completed', 'error': None, 'result': {'content': [{'type': 'text',
                       'text': json.dumps({'isError': True, 'me': identity})}]}}}]
        self.assertEqual(self.runner.successful_tools('codex', events), set())
        self.assertFalse(self.runner.native_identity_proven('codex', events, identity))

    def test_claude_native_identity_extracts_text_content(self):
        identity = {'room_id': 'room', 'member_id': 'member'}
        events = [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'a', 'name': 'mcp__coopagents_x__whoami'}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'a', 'content': [
                {'type': 'text', 'text': json.dumps({'me': identity})}]}]}}
        ]
        self.assertTrue(self.runner.native_identity_proven('claude', events, identity))
        events[1]['message']['content'][0]['is_error'] = True
        self.assertFalse(self.runner.native_identity_proven('claude', events, identity))

    def test_network_evidence_rejects_local_fallback_and_wrong_peer_endpoint(self):
        from coopagents.p2p import endpoint_id
        host = {'network': 'p2p', 'p2p_secret': '11' * 32}
        guest = {'p2p': {'endpoint_id': endpoint_id(host['p2p_secret'])}}
        self.assertTrue(self.runner.network_proven('p2p', host, guest))
        self.assertFalse(self.runner.network_proven('p2p', {'network': 'local'}, {}))
        self.assertFalse(self.runner.network_proven('p2p', host, {}))
        self.assertFalse(self.runner.network_proven('p2p', host, {'p2p': {'endpoint_id': endpoint_id('22' * 32)}}))
        self.assertFalse(self.runner.network_proven('local', host, guest))
        self.assertTrue(self.runner.network_proven('local', {'network': 'local'}, {}))
        self.assertTrue(self.runner.network_proven('p2p', host))

    def test_claude_requires_matching_successful_tool_result(self):
        events = [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'a', 'name': 'mcp__coopagents_x__whoami'},
                                                       {'type': 'tool_use', 'id': 'b', 'name': 'mcp__coopagents_x__read_team'}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'a', 'content': '{}'},
                                                  {'type': 'tool_result', 'tool_use_id': 'b', 'is_error': True}]}}
        ]
        self.assertEqual(self.runner.successful_tools('claude', events), {'whoami'})

    def test_exchange_proof_binds_sender_recipient_and_answer(self):
        snapshot = {'requests': [{'sender_member_id': 'guest', 'receiver_member_id': 'host',
                    'body': 'question nonce', 'replies': [{'author_member_id': 'host', 'body': 'answer secret'}]}]}
        self.assertTrue(self.runner.exchange_proven(snapshot, 'guest', 'host', 'nonce', 'secret'))
        self.assertFalse(self.runner.exchange_proven(snapshot, 'guest', 'wrong', 'nonce', 'secret'))
        self.assertFalse(self.runner.exchange_proven(snapshot, 'guest', 'host', 'nonce', 'invented'))

    def test_completed_diagnostics_require_both_personal_identities(self):
        state = {'collaboration': {'diagnostics': [
            {'member_id': 'host', 'status': 'completed'},
            {'member_id': 'guest', 'status': 'sent'}]}}
        self.assertFalse(self.runner.diagnostics_proven(state, {'host', 'guest'}))
        state['collaboration']['diagnostics'][1]['status'] = 'completed'
        self.assertTrue(self.runner.diagnostics_proven(state, {'host', 'guest'}))

    def test_final_reply_consumption_uses_actual_assistant_output(self):
        event = {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'answer-123'}]}}
        self.assertIn('answer-123', self.runner.assistant_text('claude', [event]))
        self.assertNotIn('answer-123', self.runner.assistant_text('claude', [
            {'type': 'user', 'message': {'content': [{'type': 'text', 'text': 'answer-123'}]}}]))

    def test_isolated_settings_copy_only_auth_and_model_provider(self):
        root = Path(__file__).resolve().parents[2] / '.local' / 'cold-start-tests' / uuid4().hex
        source = root / 'source'
        source.mkdir(parents=True)
        (source / 'config.toml').write_text('model = "configured-model"\nmodel_provider = "custom"\n'
            '[model_providers.custom]\nname = "custom"\nbase_url = "https://example.invalid"\nenv_key = "SELECTED_API_KEY"\n'
            '[model_providers.unrelated]\nname = "unrelated"\nexperimental_bearer_token = "unrelated-secret"\n'
            'env_key = "UNRELATED_API_KEY"\n'
            '[mcp_servers.personal]\ncommand = "private"\n', encoding='utf-8')
        (source / 'auth.json').write_text('{"token":"synthetic"}', encoding='utf-8')
        claude = root / 'claude-source.json'
        claude.write_text(json.dumps({'env': {'ANTHROPIC_AUTH_TOKEN': 'synthetic', 'UNRELATED_SECRET': 'omit',
                                     'AWS_SECRET_ACCESS_KEY': 'omit', 'GOOGLE_API_KEY': 'omit',
                                     'ANTHROPIC_UNRELATED_SECRET': 'omit'},
                                     'model': 'configured-claude', 'hooks': {'Stop': []}}), encoding='utf-8')
        source_env = {'PATH': os.environ.get('PATH', ''), 'SystemDrive': 'C:', 'SELECTED_API_KEY': 'selected-auth',
                      'UNRELATED_API_KEY': 'omit', 'AWS_SESSION_TOKEN': 'omit', 'GOOGLE_API_KEY': 'omit'}
        env = self.runner.prepare_homes(root / 'run', source, claude, environ=source_env)
        self.assertNotEqual(Path(env['CODEX_HOME']), source)
        config = (Path(env['CODEX_HOME']) / 'config.toml').read_text(encoding='utf-8')
        self.assertIn('configured-model', config)
        self.assertIn('example.invalid', config)
        self.assertNotIn('personal', config)
        self.assertNotIn('unrelated', config)
        self.assertEqual(env['SELECTED_API_KEY'], 'selected-auth')
        self.assertEqual(env['SystemDrive'], 'C:')
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'synthetic')
        for key in ('UNRELATED_SECRET', 'UNRELATED_API_KEY', 'AWS_SESSION_TOKEN', 'GOOGLE_API_KEY',
                    'AWS_SECRET_ACCESS_KEY', 'ANTHROPIC_UNRELATED_SECRET'):
            self.assertNotIn(key, env)
        self.assertEqual((source / 'auth.json').read_text(), '{"token":"synthetic"}')
        self.assertNotIn('hooks', (Path(env['CLAUDE_CONFIG_DIR']) / 'settings.json').read_text())

    def test_selected_claude_bedrock_auth_excludes_other_backend_credentials(self):
        root = Path(__file__).resolve().parents[2] / '.local' / 'cold-start-tests' / uuid4().hex
        root.mkdir(parents=True)
        settings = root / 'settings.json'
        settings.write_text(json.dumps({'env': {'CLAUDE_CODE_USE_BEDROCK': '1',
            'AWS_ACCESS_KEY_ID': 'selected-key', 'AWS_SECRET_ACCESS_KEY': 'selected-secret',
            'AWS_REGION': 'us-east-1', 'GOOGLE_API_KEY': 'unrelated', 'ANTHROPIC_AUTH_TOKEN': 'unrelated'}}))
        env = self.runner.prepare_homes(root / 'run', root / 'no-codex-config', settings, environ={}, tool='claude')
        self.assertEqual(env['AWS_SECRET_ACCESS_KEY'], 'selected-secret')
        self.assertEqual(env['CLAUDE_CODE_USE_BEDROCK'], '1')
        self.assertNotIn('GOOGLE_API_KEY', env)
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', env)

    def test_codex_child_does_not_receive_claude_or_unused_cloud_credentials(self):
        root = Path(__file__).resolve().parents[2] / '.local' / 'cold-start-tests' / uuid4().hex
        root.mkdir(parents=True)
        settings = root / 'settings.json'
        settings.write_text(json.dumps({'env': {'ANTHROPIC_AUTH_TOKEN': 'unrelated'}}))
        env = self.runner.prepare_homes(root / 'run', root / 'no-codex-config', settings,
            environ={'OPENAI_API_KEY': 'selected', 'AWS_SECRET_ACCESS_KEY': 'unrelated',
                     'UNRELATED_API_KEY': 'unrelated'}, tool='codex')
        self.assertEqual(env['OPENAI_API_KEY'], 'selected')
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', env)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', env)
        self.assertNotIn('UNRELATED_API_KEY', env)


if __name__ == '__main__':
    unittest.main()
