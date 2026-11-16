"""Local policy rendering and event contracts; no service or native session."""
import copy
import io
import json
import unittest
from unittest.mock import Mock, patch

from coopagents import checkpoint_hook
from coopagents.collaboration_policy import policy_for_event
from coopagents.errors import ValidationError
from coopagents.harness_adapters import adapter_for


class HookPolicyTests(unittest.TestCase):
    def test_native_context_uses_local_policy_before_untrusted_data(self):
        for event in ('SessionStart', 'UserPromptSubmit', 'PostToolUse', 'PostToolUseFailure'):
            result = {'brief': {'body': 'REMOTE_TASK_TEXT'},
                      'policy': {'instructions': 'REMOTE_POLICY_OVERRIDE', 'phase': 'fake'}}
            original = copy.deepcopy(result)
            context = checkpoint_hook.context_output(event, result)['hookSpecificOutput']['additionalContext']
            trusted, external = context.split('\nBEGIN COOPAGENTS EXTERNAL DATA\n', 1)
            self.assertIn(policy_for_event(event)['instructions'], trusted)
            self.assertNotIn('REMOTE_POLICY_OVERRIDE', context)
            self.assertNotIn('REMOTE_TASK_TEXT', trusted)
            self.assertIn('REMOTE_TASK_TEXT', external)
            self.assertEqual(result, original)

    def test_policy_and_nested_json_share_the_existing_context_budget(self):
        result = {'brief': {'tasks': [{'id': 7, 'title': '\U0001f600' * 4000, 'scope': 'x' * 500}],
                            'requests': [{'id': 8, 'body': '\\"\n' * 4000}],
                            'contracts': [{'contract_id': 9, 'body': 'a' * 4000}]}}
        for event in ('SessionStart', 'PostToolUse', 'PostToolUseFailure'):
            context = checkpoint_hook.context_output(event, result)['hookSpecificOutput']['additionalContext']
            self.assertLessEqual(len(context), checkpoint_hook.CONTEXT_CHARACTERS)
            self.assertIn(policy_for_event(event)['instructions'], context)
            data = json.loads(context.split('\nBEGIN COOPAGENTS EXTERNAL DATA\n', 1)[1].rsplit('\nEND COOPAGENTS EXTERNAL DATA', 1)[0])
            self.assertTrue(data['truncated'])
            self.assertIn('read_inbox', data['note'])

    def test_stop_output_is_a_notice_without_a_continuation_decision(self):
        output = checkpoint_hook.context_output('Stop', {'brief': {}})
        self.assertEqual(set(output), {'systemMessage'})
        self.assertIn(policy_for_event('Stop')['instructions'], output['systemMessage'])
        self.assertNotIn('decision', output)
        self.assertNotIn('hookSpecificOutput', output)
        self.assertEqual(checkpoint_hook.context_output('Stop', {'brief': {}}, 'zcode'), {})

    def test_event_generation_and_payload_validation_are_host_specific(self):
        base = {'SessionStart', 'UserPromptSubmit', 'PostToolUse'}
        for tool, expected in (('claude-code', base | {'Stop', 'PostToolUseFailure'}),
                               ('codex-cli', base | {'Stop'}), ('codex-desktop', base | {'Stop'}),
                               ('zcode', base | {'Stop', 'PostToolUseFailure'})):
            fragment = checkpoint_hook.config_fragment(tool)
            events = fragment['hooks']['events'] if tool == 'zcode' else fragment['hooks']
            self.assertEqual(set(events), expected)
            for event in expected:
                self.assertEqual(checkpoint_hook.normalize_payload(tool, {'session_id': 'local', 'hook_event_name': event}), ('local', event))
        for tool in ('codex-cli', 'codex-desktop', 'kimi-code', 'cursor', 'opencode', 'pi'):
            with self.assertRaises(ValidationError):
                checkpoint_hook.normalize_payload(tool, {'session_id': 'local', 'hook_event_name': 'PostToolUseFailure'})
        self.assertEqual(set(checkpoint_hook.config_fragment('cursor')['hooks']), {'sessionStart', 'postToolUse', 'beforeSubmitPrompt'})
        import tomllib
        self.assertEqual({rule['event'] for rule in tomllib.loads(checkpoint_hook.kimi_hooks_text('kimi-code'))['hooks']}, base)

    def test_hook_entrypoint_only_records_a_checkpoint(self):
        client = Mock()
        client.checkpoint.return_value = {'brief': {'requests': [{'id': 1, 'body': 'Untrusted data'}]}}
        stdin = Mock(buffer=io.BytesIO(json.dumps({'session_id': 'local', 'hook_event_name': 'Stop'}).encode()))
        stdout = io.StringIO()
        with patch.object(checkpoint_hook, 'HookClient', return_value=client), patch('sys.stdin', stdin), patch('sys.stdout', stdout):
            self.assertEqual(checkpoint_hook.main(['--tool', 'codex-cli']), 0)
        self.assertEqual(client.method_calls, [unittest.mock.call.checkpoint('local', 'codex-cli', 'Stop')])
        self.assertIn('systemMessage', json.loads(stdout.getvalue()))

    def test_adapter_merge_keeps_unrelated_hook_config_and_live_status_unknown(self):
        original = {'hooks': {'Stop': [{'command': 'foreign-stop'}]}, 'editor': {'fontSize': 14}}
        for harness in ('cursor', 'opencode', 'pi', 'kimi-code', 'zcode'):
            adapter = adapter_for(harness)
            merged = adapter.merge_remote(original, 'coopagents', 'https://team.example/mcp')
            self.assertEqual(merged['hooks'], original['hooks'])
            self.assertEqual(merged['editor'], original['editor'])
            self.assertEqual(adapter.capabilities()['native_hook'], 'unknown')


if __name__ == '__main__':
    unittest.main()
