"""Real authenticated HTTP and MCP evidence for workflow convenience operations."""
import asyncio
from contextlib import asynccontextmanager
import unittest

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from transport_support import LiveService


class WorkflowMCPTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.a, self.b = self.live.bootstrap()

    @asynccontextmanager
    async def client(self, member):
        async with httpx2.AsyncClient(headers={'Authorization': 'Bearer '+member['agent_token']}) as http:
            async with Client(streamable_http_client(self.live.url+'/mcp', http_client=http), cache=None) as client:
                yield client

    def test_owner_question_and_sent_reply_cross_actual_mcp(self):
        status, task, _ = self.live.request('POST', '/api/tasks', self.b['web_token'],
            dict(intent_key='backend', title='Backend', scope='src/api'))
        self.assertEqual(status, 200)
        self.live.request('POST', f"/api/tasks/{task['id']}/claim", self.b['agent_token'],
                          dict(session_key='backend'))

        async def run():
            async with self.client(self.a) as a, self.client(self.b) as b:
                names = {t.name for t in (await a.list_tools()).tools}
                self.assertIn('ask_owner', names)
                self.assertIn('read_replies', names)
                self.assertTrue({'work_brief', 'read_workflow', 'record_agreement_use'} <= names)
                self.assertNotIn('decision', names)
                result = await a.call_tool('ask_owner', dict(request_key='schema', body='Which fields?', scope='src/api'))
                self.assertFalse(result.is_error, result.content)
                request = result.structured_content['request']
                await b.call_tool('read_inbox', {})
                answer = await b.call_tool('reply', dict(request_id=request['id'], request_key='answer',
                    context_version=1, body='cursor:string', evidence='api/schema.py'))
                self.assertFalse(answer.is_error, answer.content)
                page = await a.call_tool('read_replies', {})
                self.assertFalse(page.is_error, page.content)
                self.assertEqual(page.structured_content['replies'][0]['body'], 'cursor:string')
                self.assertFalse(page.structured_content['model_consumption_proven'])
                brief = await a.call_tool('work_brief', {})
                self.assertFalse(brief.is_error, brief.content)
                self.assertTrue(brief.structured_content['read_only'])
                projected = await a.call_tool('read_workflow', {})
                self.assertFalse(projected.is_error, projected.content)
                self.assertTrue(projected.structured_content['onboarding']['two_member_exchange_complete'])
        asyncio.run(run())
        status, page, _ = self.live.request('POST', '/api/operations/read_replies', self.a['agent_token'], {})
        self.assertEqual(status, 200)
        self.assertEqual(len(page['replies']), 1)
        status, _, _ = self.live.request('POST', '/api/operations/ask_owner', self.a['web_token'],
            dict(request_key='wrong-kind', body='Q', scope='src/api'))
        self.assertEqual(status, 401)
