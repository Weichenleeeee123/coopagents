"""Owner-question public wording/schema checks; no service or native execution."""
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mcp.server import MCPServer

from coopagents.errors import ValidationError
from coopagents.mcp_service import TOOL_DESCRIPTIONS, create_mcp_app
from coopagents.protocol import validate
from coopagents.workflow import schemas


ROOT = Path(__file__).resolve().parents[1]


class OwnerQuestionContractTests(unittest.TestCase):
    def test_owner_question_description_explains_durable_current_responsibility(self):
        description = TOOL_DESCRIPTIONS['ask_owner']
        for phrase in ('with or without source_task_id', 'persist', 'unassigned', 'current route',
                       'candidates', 'request_key', 'same payload', 'send_request'):
            self.assertTrue(phrase in description, 'ask_owner description is missing: ' + phrase)
        self.assertNotIn('it sends a fixed-recipient question', description)
        self.assertNotIn('an unassigned target sends nothing', description)

    def test_reply_description_separates_owner_route_history_and_exact_read_evidence(self):
        description = TOOL_DESCRIPTIONS['read_replies']
        for phrase in ('owner-question', 'current route', 'Historical', 'exact reply ids',
                       'after_id', 'has_more', 'never resolves', 'model comprehension'):
            self.assertTrue(phrase in description, 'read_replies description is missing: ' + phrase)

    def test_existing_schemas_remain_additive_without_new_authority_fields(self):
        contract = schemas()
        self.assertEqual(set(contract), {'ask_owner', 'read_replies'})
        self.assertEqual(set(contract['ask_owner']), {'request_key', 'body', 'target_task_id',
            'scope', 'source_task_id', 'expected_revision', 'context', 'session_key', 'ownership_epoch'})
        self.assertEqual(set(contract['read_replies']), {'after_id', 'limit', 'task_id'})
        for field in ('target_task_id', 'source_task_id', 'expected_revision', 'ownership_epoch'):
            self.assertEqual(contract['ask_owner'][field], (int, False, None))
        for arguments in ({'request_key': 'question', 'body': 'Which field?', 'target_task_id': True},
                          {'request_key': 'question', 'body': 'Which field?', 'scope': 'src/api', 'approve': True}):
            with self.assertRaises(ValidationError):
                validate(arguments, contract['ask_owner'])

    def test_mcp_registration_reuses_descriptions_and_does_not_advertise_human_tools(self):
        service = SimpleNamespace(operations=defaultdict(lambda: ('agent', None, {})))
        with patch.object(MCPServer, 'add_tool') as register:
            create_mcp_app(service)
        entries = {call.kwargs['name']: call.kwargs.get('description') for call in register.call_args_list}
        self.assertEqual(entries['ask_owner'], TOOL_DESCRIPTIONS['ask_owner'])
        self.assertEqual(entries['read_replies'], TOOL_DESCRIPTIONS['read_replies'])
        self.assertTrue({'decision', 'accept_handoff', 'force_handoff', 'assign'}.isdisjoint(entries))

    def test_practical_guide_distinguishes_owner_routing_from_direct_fixed_recipient(self):
        text = (ROOT / 'docs/team-workflow.md').read_text(encoding='utf-8')
        for phrase in ('`task_owner`', 'with or without a source task', '`route`', 'historical',
                       'Direct `send_request`', 'fixed recipient', 'same key', 'candidates'):
            self.assertTrue(phrase in text, 'workflow guide is missing: ' + phrase)
        self.assertNotIn('Its `routing` is `fixed_recipient`', text)
        self.assertNotIn('A member-level question to an unassigned target also creates no message.', text)

    def test_bundled_protocols_and_evaluation_preserve_boundaries(self):
        for name in ('coopagents-connect', 'coopagents-space'):
            text = (ROOT / 'src/skills' / name / 'protocol.md').read_text(encoding='utf-8')
            for phrase in ('ask_owner', 'unassigned', 'current route', 'send_request', 'read_replies'):
                self.assertTrue(phrase in text, name + ' protocol is missing: ' + phrase)
        text = (ROOT / 'docs/workflow-evaluation.md').read_text(encoding='utf-8')
        self.assertTrue('owner-question routes' in text)
        self.assertTrue('not native acceptance' in text)


if __name__ == '__main__':
    unittest.main()
