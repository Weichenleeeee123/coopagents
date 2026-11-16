"""Schema/registration checks only; no native processes or network calls."""
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from mcp.server import MCPServer
from coopagents.coordination import CoordinationService
from coopagents.git_adapter import create_local_mcp
from coopagents.mcp_service import create_mcp_app


class SessionRoutingContractTests(unittest.TestCase):
    def setUp(self):
        self.service = CoordinationService(Path('.local/test-evidence') / ('routing-contract-' + uuid4().hex + '.sqlite3'))

    def test_native_alias_and_digest_filter_are_additive_personal_agent_parameters(self):
        registration = self.service.operations['register_session']
        self.assertEqual(registration[0], 'agent')
        self.assertIn('native_session_id', registration[2])
        self.assertEqual(registration[2]['native_session_id'], (str, False, None))
        self.assertEqual(self.service.operations['wake_digest'][2]['session_key'], (str, False, None))

    def test_presence_is_internal_authenticated_operation_not_extra_model_tool(self):
        self.assertIn('session_presence', self.service.operations)
        operation = self.service.operations['session_presence']
        self.assertEqual(operation[0], 'agent')
        self.assertEqual(set(operation[2]), {'session_key', 'tool', 'state', 'ttl_seconds'})
        with patch.object(MCPServer, 'add_tool') as register:
            create_mcp_app(self.service)
        names = [call.kwargs.get('name') for call in register.call_args_list]
        self.assertNotIn('session_presence', names)

    def test_http_and_git_registration_include_the_same_native_alias_parameter(self):
        signatures = []
        for factory, source in ((create_mcp_app, self.service), (create_local_mcp, SimpleNamespace())):
            with patch.object(MCPServer, 'add_tool') as register:
                factory(source)
                methods = [call.args[0] for call in register.call_args_list
                           if call.kwargs.get('name') == 'register_session']
                self.assertEqual(len(methods), 1)
                import inspect
                signatures.append(inspect.signature(methods[0]).parameters)
        self.assertIn('native_session_id', signatures[0])
        self.assertEqual(set(signatures[0]), set(signatures[1]))


if __name__ == '__main__':
    unittest.main()
