"""The local Git entry point shares workflow descriptions and real forwarding."""
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from mcp.server import MCPServer
from coopagents.git_adapter import LocalAdapter, create_local_mcp
from coopagents.mcp_service import TOOL_DESCRIPTIONS
from transport_support import LiveService


class WorkflowGitTests(unittest.TestCase):
    def test_new_workflow_tools_share_the_remote_operation_descriptions(self):
        with patch.object(MCPServer, 'add_tool') as registered:
            create_local_mcp(SimpleNamespace())
        descriptions = {call.kwargs.get('name', call.args[0].__name__): call.kwargs.get('description')
                        for call in registered.call_args_list}
        for name in ('ask_owner', 'read_replies', 'record_agreement_use', 'work_brief', 'read_workflow'):
            self.assertEqual(descriptions[name], TOOL_DESCRIPTIONS[name])

    def test_all_five_operations_forward_into_the_actual_bound_http_project(self):
        live = LiveService()
        self.addCleanup(live.close)
        a, b = live.bootstrap()
        service = live.app.state.service
        service.repositories.bind_repository(a['web_token'], 'github.com/acme/workflow')
        root = Path('.local/test-evidence') / ('workflow-git-' + uuid4().hex)
        repo = root/'repo'
        repo.mkdir(parents=True)
        subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin',
                        'https://github.com/acme/workflow.git'], check=True, capture_output=True)
        front = service.tasks.create_task(a['web_token'], 'front', 'Frontend', 'src/ui')
        front = service.tasks.claim_task(a['agent_token'], front['id'], 'front')
        back = service.tasks.create_task(b['web_token'], 'back', 'Backend', 'src/api')
        service.tasks.claim_task(b['agent_token'], back['id'], 'back')
        left = LocalAdapter(repo, live.url, a['room_id'], a['agent_token'], state_root=root/'a')
        right = LocalAdapter(repo, live.url, a['room_id'], b['agent_token'], state_root=root/'b')
        question = left.forward('ask_owner', dict(scope='src/api', body='Schema?', request_key='question'))
        request = question['request']
        right.forward('read_inbox', {})
        right.forward('reply', dict(request_id=request['id'], request_key='answer', context_version=1, body='cursor'))
        self.assertEqual(left.forward('read_replies', {})['replies'][0]['body'], 'cursor')
        contract = service.contracts.propose(b['agent_token'], 'api', 0, 'API', 'cursor')
        service.contracts.decide(a['web_token'], contract['id'], 1, 'approved')
        auth = dict(task_id=front['id'], session_key='front', ownership_epoch=front['ownership_epoch'])
        used = left.forward('record_agreement_use', dict(contract_id=contract['id'], version=1, **auth))
        self.assertEqual(used['baseline_version'], 1)
        self.assertTrue(left.forward('work_brief', auth)['read_only'])
        self.assertTrue(left.forward('read_workflow', {})['onboarding']['two_member_exchange_complete'])
