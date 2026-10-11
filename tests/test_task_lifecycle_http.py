import asyncio
from contextlib import asynccontextmanager
import unittest
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from transport_support import LiveService


class LifecycleTransportTests(unittest.TestCase):
    def setUp(self):
        self.live=LiveService(); self.addCleanup(self.live.close)
        self.owner,self.member=self.live.bootstrap()
        self.task=self.live.request('POST','/api/tasks',self.owner['web_token'],dict(intent_key='http',title='HTTP task',scope='src'))[1]

    def test_http_revision_conflicts_human_accept_and_cancel_projection(self):
        task=self.live.request('POST',f"/api/tasks/{self.task['id']}/claim",self.owner['agent_token'],{'session_key':'first'})[1]
        args=dict(expected_revision=task['revision'],request_key='transfer',summary='Use branch feature',target_member_id=self.member['member_id'],session_key='first',ownership_epoch=task['ownership_epoch'])
        status,task,_=self.live.request('POST',f"/api/tasks/{task['id']}/propose-handoff",self.owner['agent_token'],args)
        self.assertEqual(status,200,task)
        decision=dict(expected_revision=task['revision'],request_key='accept',summary='I will finish')
        path=f"/api/tasks/{task['id']}/accept-handoff"
        self.assertEqual(self.live.request('POST',path,self.member['agent_token'],decision)[0],401)
        status,task,_=self.live.request('POST',path,self.member['web_token'],decision)
        self.assertEqual(status,200,task)
        self.assertEqual(self.live.request('POST',path,self.member['web_token'],decision)[1],task)
        status,result,_=self.live.request('POST',f"/api/tasks/{task['id']}/cancel-task",self.member['web_token'],decision)
        self.assertEqual(status,409,result)
        bound=self.live.request('POST',f"/api/tasks/{task['id']}/claim",self.member['agent_token'],{'session_key':'second'})[1]
        self.assertEqual(self.live.request('POST',f"/api/tasks/{task['id']}/claim",self.member['agent_token'],{'session_key':'second'})[1],bound)
        self.assertEqual(self.live.request('POST',f"/api/tasks/{task['id']}/claim",self.member['agent_token'],{'session_key':'third'})[0],409)
        cancellation=dict(expected_revision=bound['revision'],request_key='cancel',summary='No longer needed')
        self.assertEqual(self.live.request('POST',f"/api/tasks/{task['id']}/cancel-task",self.member['web_token'],cancellation)[1]['state'],'cancelled')
        view=self.live.request('GET','/api/snapshot',self.owner['web_token'])[1]
        self.assertTrue(view['lifecycle']['can_manage'])
        self.assertEqual(view['tasks'][0]['state'],'cancelled')
        self.assertEqual(self.live.request('POST',f"/api/tasks/{task['id']}/claim",self.member['agent_token'],{})[0],409)

    @asynccontextmanager
    async def client(self,token):
        async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+token}) as http:
            async with Client(streamable_http_client(self.live.url+'/mcp',http_client=http),cache=None) as client:
                yield client

    def test_real_mcp_exposes_only_agent_lifecycle_operations_and_session_parameters(self):
        async def run():
            async with self.client(self.owner['agent_token']) as client:
                tools={tool.name:tool for tool in (await client.list_tools()).tools}
                self.assertIn('release_task',tools)
                self.assertIn('propose_handoff',tools)
                for name in ('accept_handoff','reject_handoff','force_handoff','cancel_task','reopen_task'):
                    self.assertNotIn(name,tools)
                for name in ('register_session','report_progress','repo_checkpoint','checkpoint','link_delivery'):
                    self.assertIn('ownership_epoch',tools[name].input_schema['properties'])
                claimed=await client.call_tool('claim_task',dict(task_id=self.task['id'],session_key='mcp'))
                self.assertFalse(claimed.is_error,claimed.content)
                task=claimed.structured_content
                args=dict(task_id=task['id'],expected_revision=task['revision'],request_key='release',summary='Branch saved',session_key='mcp',ownership_epoch=task['ownership_epoch'])
                released=await client.call_tool('release_task',args)
                self.assertFalse(released.is_error,released.content)
                self.assertEqual(released.structured_content['state'],'open')
        asyncio.run(run())
