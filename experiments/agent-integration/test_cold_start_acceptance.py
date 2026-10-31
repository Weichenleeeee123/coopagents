"""Safety and evidence regressions; these do not consume model quota."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import subprocess
import unittest
from uuid import uuid4

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
            else:
                self.assertIn('--allowedTools', command)
                self.assertNotIn('Bash(*)', joined)

    def test_partial_host_cli_is_explicit_and_preparation_spends_no_quota(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('cold_start_acceptance.py')),
                                 '--host', 'codex', '--stop-after-host-verification', '--prepare-only'],
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
            '[model_providers.custom]\nname = "custom"\nbase_url = "https://example.invalid"\n'
            '[mcp_servers.personal]\ncommand = "private"\n', encoding='utf-8')
        (source / 'auth.json').write_text('{"token":"synthetic"}', encoding='utf-8')
        claude = root / 'claude-source.json'
        claude.write_text(json.dumps({'env': {'ANTHROPIC_AUTH_TOKEN': 'synthetic', 'UNRELATED_SECRET': 'omit'},
                                     'model': 'configured-claude', 'hooks': {'Stop': []}}), encoding='utf-8')
        env = self.runner.prepare_homes(root / 'run', source, claude, environ={'PATH': os.environ.get('PATH', '')})
        self.assertNotEqual(Path(env['CODEX_HOME']), source)
        config = (Path(env['CODEX_HOME']) / 'config.toml').read_text(encoding='utf-8')
        self.assertIn('configured-model', config)
        self.assertIn('example.invalid', config)
        self.assertNotIn('personal', config)
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'synthetic')
        self.assertNotIn('UNRELATED_SECRET', env)
        self.assertEqual((source / 'auth.json').read_text(), '{"token":"synthetic"}')
        self.assertNotIn('hooks', (Path(env['CLAUDE_CONFIG_DIR']) / 'settings.json').read_text())


if __name__ == '__main__':
    unittest.main()
