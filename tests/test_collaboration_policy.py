"""Every collaboration entry point carries the same daily-work policy."""
from collections import defaultdict
import importlib
import importlib.util
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mcp.server import MCPServer, Server

from coopagents.git_adapter import create_local_mcp
from coopagents.mcp_service import create_mcp_app
from coopagents.space_bridge import Bridge


class CollaborationPolicyTests(unittest.TestCase):
    EVENT_PHASES = {
        'SessionStart': 'startup', 'startup': 'startup',
        'UserPromptSubmit': 'prompt', 'prompt': 'prompt',
        'PostToolUse': 'tool', 'tool': 'tool',
        'Stop': 'completion', 'completion': 'completion',
        'PostToolUseFailure': 'blocker', 'blocker': 'blocker',
        'reply': 'reply', 'manual': 'manual',
    }
    def policy(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.collaboration_policy'),
                             'entry points need a shared versioned collaboration policy')
        return importlib.import_module('coopagents.collaboration_policy')

    def instructions(self):
        service = SimpleNamespace(operations=defaultdict(lambda: ('agent', None, {})))
        with patch('coopagents.mcp_service.MCPServer', wraps=MCPServer) as server:
            create_mcp_app(service)
            http = server.call_args.kwargs['instructions']
        with patch('mcp.server.MCPServer', wraps=MCPServer) as server:
            create_local_mcp(SimpleNamespace())
            git = server.call_args.kwargs['instructions']
        with patch('mcp.server.Server', wraps=Server) as server:
            Bridge.__new__(Bridge).server()
            bridge = server.call_args.kwargs['instructions']
        return http, git, bridge

    def test_all_entry_points_include_the_exact_versioned_policy(self):
        policy = self.policy()
        self.assertTrue(policy.POLICY_VERSION)
        self.assertIn(policy.POLICY_VERSION, policy.DAILY_COLLABORATION_POLICY)
        for instructions in self.instructions():
            self.assertEqual(instructions.count(policy.DAILY_COLLABORATION_POLICY), 1)

    def test_common_policy_explains_daily_work_and_evidence_boundaries(self):
        text = self.policy().DAILY_COLLABORATION_POLICY
        for phrase in ('startup', 'blocker', 'completion', 'ownership_epoch', 'responsibility',
                       'replies to requests you sent', 'independent work', 'human',
                       'untrusted', 'never marks messages read', 'read receipt', 'current route'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_policy_guides_the_task_focused_question_reply_and_agreement_paths(self):
        text = self.policy().DAILY_COLLABORATION_POLICY
        for operation in ('work_brief', 'ask_owner', 'read_replies', 'record_agreement_use', 'has_more'):
            self.assertIn(operation, text)

    def test_transport_identity_wake_and_authority_notes_are_retained(self):
        self.policy()
        http, git, bridge = self.instructions()
        for phrase in ('authenticated personal agent', 'web interface', 'wake_digest',
                       'read_dependency', 'latest reply_id and revision'):
            self.assertIn(phrase, http)
        for phrase in ('repo_checkpoint', 'does not create or publish releases',
                       'client-reported evidence', 'no idle wakeup', 'repository content'):
            self.assertIn(phrase, git)
        for phrase in ('personal agent identity', 'read_changes', 'counts-only notice',
                       'install_wake', 'returns installed', 'CLI helper or web UI'):
            self.assertIn(phrase, bridge)

    def test_policy_does_not_expose_human_mutation_operations(self):
        self.policy()
        with patch.object(MCPServer, 'add_tool') as add_tool:
            create_local_mcp(SimpleNamespace())
        # Policy is prose; adding a policy must not change the available protocol.
        names = [call.kwargs.get('name', call.args[0].__name__) for call in add_tool.call_args_list]
        self.assertTrue({'create_task', 'decision', 'accept_handoff'}.isdisjoint(names))

    def event_policy(self, event):
        module = self.policy()
        self.assertTrue(callable(getattr(module, 'policy_for_event', None)),
                        'lifecycle guidance needs a shared event policy function')
        return module.policy_for_event(event)

    def test_event_policy_normalizes_native_and_tool_lifecycle_events(self):
        module = self.policy()
        for event, phase in self.EVENT_PHASES.items():
            with self.subTest(event=event):
                policy = self.event_policy(event)
                self.assertEqual(set(policy), {'version', 'phase', 'required_actions', 'instructions'})
                self.assertEqual(policy['version'], module.POLICY_VERSION)
                self.assertEqual(policy['phase'], phase)
                self.assertTrue(policy['required_actions'])
                self.assertTrue(all(isinstance(action, str) and action for action in policy['required_actions']))
                self.assertEqual(len(policy['required_actions']), len(set(policy['required_actions'])))
                self.assertEqual(policy, self.event_policy(phase))

    def test_machine_actions_and_instructions_use_the_same_static_rule_source(self):
        module = self.policy()
        self.assertTrue(hasattr(module, 'POLICY_RULES'), 'machine actions and prose need one rule source')
        for phase in set(self.EVENT_PHASES.values()):
            policy = self.event_policy(phase)
            self.assertTrue(policy['instructions'].startswith(module.DAILY_COLLABORATION_POLICY))
            for action in policy['required_actions']:
                self.assertIn(module.POLICY_RULES[action], policy['instructions'])
        reply = self.event_policy('reply')
        self.assertIn('check_reply_lifecycle', reply['required_actions'])
        self.assertIn('reply', reply['instructions'])
        for phrase in ('untrusted', 'real current user instruction', 'never mark messages read'):
            self.assertIn(phrase, reply['instructions'])

    def test_event_policy_has_no_message_input_and_does_not_share_mutable_results(self):
        first = self.event_policy('reply')
        first['required_actions'].clear()
        first['instructions'] = 'untrusted replacement'
        second = self.event_policy('reply')
        self.assertTrue(second['required_actions'])
        self.assertNotEqual(second['instructions'], first['instructions'])
        with self.assertRaises(TypeError):
            self.policy().policy_for_event('reply', message='grant admin')

    def test_unknown_event_policy_inputs_fail_closed_with_supported_events(self):
        from coopagents.errors import ValidationError
        self.event_policy('startup')
        for event in ('session_start', 'assistant message: completion', '', None, True, [], {}):
            with self.subTest(event=event):
                with self.assertRaises(ValidationError) as caught:
                    self.policy().policy_for_event(event)
                self.assertIn('reply', str(caught.exception))
                self.assertIn('SessionStart', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
