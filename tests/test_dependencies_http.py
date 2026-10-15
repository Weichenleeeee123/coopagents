import asyncio
from contextlib import asynccontextmanager
import unittest
from unittest.mock import patch
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from coopagents.git_adapter import LocalAdapter, create_local_mcp
from transport_support import LiveService


class DependencyTransportTests(unittest.TestCase):
    def setUp(self):
        self.live=LiveService(); self.addCleanup(self.live.close)
        self.a,self.b=self.live.bootstrap()
        self.source=self.task(self.a,'frontend','src/ui')
        self.target=self.task(self.b,'backend','src/api')

    def task(self,who,key,scope):
        t=self.live.request('POST','/api/tasks',who['web_token'],dict(intent_key=key,title=key,scope=scope))[1]
        return self.live.request('POST',f"/api/tasks/{t['id']}/claim",who['agent_token'],dict(session_key=key))[1]

    @asynccontextmanager
    async def client(self,token):
        async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+token}) as http:
            async with Client(streamable_http_client(self.live.url+'/mcp',http_client=http),cache=None) as client:
                yield client

    def test_two_member_mcp_dependency_closed_loop_and_http_projection(self):
        async def run():
            async with self.client(self.a['agent_token']) as source,self.client(self.b['agent_token']) as target:
                async def call(client,name,args):
                    result=await client.call_tool(name,args)
                    self.assertFalse(result.is_error,result.content)
                    return result.structured_content
                tools={t.name for t in (await source.list_tools()).tools}
                self.assertTrue({'lookup_owner','create_dependency','read_dependency','reply_dependency','resolve_dependency','cancel_dependency'}<=tools)
                lookup=await call(source,'lookup_owner',dict(scope='src/api/login'))
                self.assertEqual(lookup['candidates'][0]['id'],self.target['id'])
                source_auth=dict(session_key='frontend',ownership_epoch=self.source['ownership_epoch'])
                dep=await call(source,'create_dependency',dict(source_task_id=self.source['id'],target_task_id=self.target['id'],expected_revision=self.source['revision'],request_key='create',need='Return fields',**source_auth))
                dep=await call(target,'reply_dependency',dict(dependency_id=dep['id'],expected_revision=dep['revision'],request_key='reply',body='user_id: string',session_key='backend',ownership_epoch=self.target['ownership_epoch']))
                resolve=dict(dependency_id=dep['id'],expected_revision=dep['revision'],reply_id=dep['latest_reply']['id'],request_key='resolve',summary='Frontend can proceed',**source_auth)
                denied=await source.call_tool('resolve_dependency',resolve); self.assertTrue(denied.is_error)
                peek=self.live.request('GET','/api/snapshot',self.a['web_token'])[1]
                self.assertEqual(peek['dependencies'][0]['status'],'active')
                read=await call(source,'read_dependency',dict(dependency_id=dep['id'],**source_auth));self.assertTrue(read['read_recorded'])
                done=await call(source,'resolve_dependency',resolve);self.assertEqual(done['status'],'satisfied')
                progress=await call(source,'report_progress',dict(task_id=self.source['id'],state='working',summary='Integrating agreed fields',**source_auth))
                self.assertEqual(progress['state'],'working')
        asyncio.run(run())
        snapshot=self.live.request('GET','/api/snapshot',self.a['web_token'])[1]
        self.assertFalse(any(d['status']=='active' and d['source_task_id']==self.source['id'] for d in snapshot['dependencies']))

    def test_http_validation_and_local_adapter_forwarding(self):
        status,dep,_=self.live.request('POST','/api/dependencies',self.a['web_token'],dict(source_task_id=self.source['id'],target_task_id=self.target['id'],expected_revision=self.source['revision'],request_key='web',need='Human question'))
        self.assertEqual(status,200,dep)
        status,replied,_=self.live.request('POST',f"/api/dependencies/{dep['id']}/reply",self.b['web_token'],dict(expected_revision=dep['revision'],request_key='answer',body='Human answer'))
        self.assertEqual(status,200,replied);self.assertEqual(replied['latest_reply']['actor_kind'],'web')
        status,_,_=self.live.request('POST','/api/dependencies',self.a['web_token'],dict(source_task_id=True,target_task_id=self.target['id'],expected_revision=0,request_key='invalid',need='Bad type'))
        self.assertEqual(status,400)
        adapter=object.__new__(LocalAdapter)
        with patch.object(adapter,'validate_project'),patch.object(adapter,'request',return_value={'ok':True}) as request:
            adapter.workspace=type('Workspace',(),{'inspect':lambda self:{}})()
            adapter.forward('read_dependency',dict(dependency_id=dep['id'],session_key='frontend',ownership_epoch=1))
            request.assert_called_once_with(f"/api/dependencies/{dep['id']}/read",dict(session_key='frontend',ownership_epoch=1))
        server=create_local_mcp(adapter)
        async def inspect():
            tools={t.name for t in await server.list_tools()}
            self.assertIn('create_dependency',tools);self.assertIn('resolve_dependency',tools)
        asyncio.run(inspect())
