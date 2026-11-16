"""The canonical lifecycle entry has the same discoverable meaning everywhere."""
from collections import defaultdict
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mcp.server import MCPServer
from coopagents.git_adapter import create_local_mcp
from coopagents.mcp_service import create_mcp_app, TOOL_DESCRIPTIONS


class CheckpointPolicyTransportTests(unittest.TestCase):
    def test_description_teaches_every_tool_lifecycle_without_claiming_consumption(self):
        description = TOOL_DESCRIPTIONS.get('checkpoint', '')
        for word in ('startup', 'blocker', 'reply', 'completion', 'policy', 'session_key', 'ownership_epoch'):
            self.assertIn(word, description)
        self.assertIn('never marks', description)

    def test_http_and_git_register_the_same_checkpoint_description(self):
        service = SimpleNamespace(operations=defaultdict(lambda: ('agent', None, {})))
        descriptions = []
        for factory, value in ((create_mcp_app, service), (create_local_mcp, SimpleNamespace())):
            with patch.object(MCPServer, 'add_tool') as register:
                factory(value)
                matches = [call.kwargs.get('description') for call in register.call_args_list
                           if call.kwargs.get('name', getattr(call.args[0], '__name__', '')) == 'checkpoint']
                self.assertEqual(len(matches), 1)
                descriptions.append(matches[0])
        self.assertEqual(descriptions, [TOOL_DESCRIPTIONS['checkpoint']] * 2)

    def test_p2p_wake_carries_shared_rules_and_preserves_existing_authorization(self):
        from coopagents.collaboration_policy import DAILY_COLLABORATION_POLICY
        from coopagents.space_wake import wake_text
        text = wake_text({'reply': 1})
        self.assertEqual(text.count(DAILY_COLLABORATION_POLICY), 1)
        self.assertIn('existing authorized assignment', text)
        self.assertIn('read_replies', text)
        self.assertIn('not a message from your user', text)

    def test_generated_git_project_rules_use_the_same_policy_source(self):
        from coopagents import git_adapter
        from coopagents.collaboration_policy import DAILY_COLLABORATION_POLICY
        helper = getattr(git_adapter, 'project_rules', None)
        self.assertTrue(callable(helper), 'generated local rules need the canonical policy')
        text = helper()
        self.assertEqual(text.count(DAILY_COLLABORATION_POLICY), 1)
        self.assertIn('repo_checkpoint(task_id)', text)


if __name__ == '__main__':
    unittest.main()
