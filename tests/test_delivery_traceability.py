import unittest
from pathlib import Path
from uuid import uuid4
from datetime import timedelta

from coopagents.coordination import CoordinationService
from coopagents.errors import AccessDenied, Conflict, NotFound
from coopagents.repositories import now
from test_github_sync import FakeProvider


class DeliveryTraceabilityTests(unittest.TestCase):
    def setUp(self):
        root=Path('.local/test-evidence/delivery-traceability')/uuid4().hex;root.mkdir(parents=True)
        self.provider=FakeProvider();self.s=CoordinationService(root/'trace.sqlite3',self.provider)
        self.owner=self.s.identity.create_room('Delivery','Owner')
        self.peer=self.s.identity.add_member(self.owner['web_token'],'Peer')
        self.other=self.s.identity.create_room('Other','Other')
        self.s.repositories.bind_repository(self.owner['web_token'],'github.com/acme/demo')
        auth=self.s.github.begin_authorization(self.owner['web_token'])
        self.s.github.complete_authorization(auth['state'],'code')
        self.s.github.finish_authorization(self.owner['web_token'],auth['state'])
        self.task=self.task_for('one')

    def task_for(self,key):
        task=self.s.tasks.create_task(self.owner['web_token'],key,key,'src')
        return self.s.tasks.claim_task(self.peer['agent_token'],task['id'])

    def test_explicit_unsynced_and_reverse_many_to_many_associations(self):
        second=self.task_for('two')
        for task in (self.task,second):
            self.s.github.associate(self.peer['agent_token'],task['id'],pr_number=7)
        before=self.s.read_deliveries(self.owner['web_token'],kind='pr',value='7')
        self.assertEqual(len(before['items']),1)
        obj=before['items'][0]
        self.assertEqual(obj['task_ids'],[self.task['id'],second['id']])
        self.assertEqual({a['relationship_source'] for a in obj['associations']},{'explicit'})
        self.assertTrue(all(a['linked_by']==self.peer['member_id'] for a in obj['associations']))
        self.assertTrue(all(a['state']=='pending_sync' for a in obj['associations']))
        self.s.github.refresh(self.owner['web_token'])
        after=self.s.read_deliveries(self.owner['web_token'],task_id=second['id'])
        self.assertEqual(after['items'][0]['task_ids'],[self.task['id'],second['id']])
        self.assertTrue(all(a['state']=='closed_unmerged' for a in after['items'][0]['associations']))
        self.assertEqual(self.s.read_deliveries(self.other['web_token'])['items'],[])

    def test_suggestions_require_confirmation_and_cannot_survive_epoch_change(self):
        args=dict(task_id=self.task['id'],request_key='suggest-one',pr_number=7,evidence='Member supplied PR reference')
        proposal=self.s.delivery.suggest(self.peer['agent_token'],**args)
        self.assertEqual(proposal,self.s.delivery.suggest(self.peer['agent_token'],**args))
        self.assertEqual(self.s.github.snapshot(self.owner['web_token'])['deliveries'],[])
        with self.assertRaises(AccessDenied):
            self.s.delivery.decide(self.peer['agent_token'],proposal['id'],'confirmed')
        result=self.s.delivery.decide(self.owner['web_token'],proposal['id'],'confirmed')
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(self.s.delivery.decide(self.owner['web_token'],proposal['id'],'confirmed'),result)
        with self.assertRaises(Conflict):self.s.delivery.decide(self.owner['web_token'],proposal['id'],'rejected')
        self.assertEqual(self.s.tasks.list_tasks(self.owner['web_token'])[0]['state'],'claimed')
        second=self.s.delivery.suggest(self.peer['agent_token'],task_id=self.task['id'],request_key='suggest-two',branch='feature',evidence='Explicit candidate')
        self.s.lifecycle.release_task(self.peer['agent_token'],self.task['id'],self.task['revision'],'release','Pause')
        self.s.tasks.claim_task(self.peer['agent_token'],self.task['id'])
        with self.assertRaises(Conflict):self.s.delivery.decide(self.owner['web_token'],second['id'],'confirmed')

    def test_stale_revoked_and_unavailable_remote_facts_do_not_close_tasks(self):
        self.s.github.associate(self.peer['agent_token'],self.task['id'],pr_number=7)
        self.provider.current['pull_requests'][0]['merged']=True
        self.s.github.refresh(self.owner['web_token'])
        self.assertEqual(self.s.tasks.list_tasks(self.owner['web_token'])[0]['state'],'claimed')
        with self.s.identity.db.connect(write=True) as db:
            stamp=(now()-timedelta(days=1)).isoformat()
            db.execute('UPDATE github_connections SET sync_at=?',(stamp,))
            db.execute('UPDATE github_evidence SET sync_at=?',(stamp,))
        view=self.s.read_deliveries(self.owner['agent_token'])
        self.assertTrue(view['items'][0]['associations'][0]['stale'])
        with self.s.identity.db.connect(write=True) as db:db.execute("UPDATE github_connections SET status='revoked'")
        view=self.s.read_deliveries(self.owner['web_token'])
        self.assertTrue(view['items'][0]['associations'][0]['unavailable'])
        self.assertEqual(view['items'][0]['associations'][0]['state'],'unavailable')

    def test_http_mcp_and_manager_only_confirmation(self):
        import asyncio
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        from transport_support import LiveService
        live=LiveService();self.addCleanup(live.close);owner,peer=live.bootstrap()
        task=live.request('POST','/api/tasks',owner['web_token'],dict(intent_key='delivery',title='Delivery',scope='src'))[1]
        live.request('POST',f"/api/tasks/{task['id']}/claim",peer['agent_token'],{})
        async def run():
            async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+peer['agent_token']}) as http:
                async with Client(streamable_http_client(live.url+'/mcp',http_client=http),cache=None) as client:
                    result=await client.call_tool('suggest_delivery',dict(task_id=task['id'],request_key='pr-candidate',pr_number=7,evidence='Review this PR'))
                    self.assertFalse(result.is_error,result.content)
                    read=await client.call_tool('read_deliveries',dict(kind='pr',value='7'))
                    self.assertFalse(read.is_error,read.content)
                    return result.structured_content
        proposal=asyncio.run(run())
        status,view,_=live.request('GET','/api/deliveries?kind=pr&value=7',owner['web_token'])
        self.assertEqual(status,200,view);self.assertEqual(view['items'][0]['task_ids'],[task['id']])
        self.assertEqual(live.request('POST','/api/operations/decide_delivery',peer['agent_token'],dict(suggestion_id=proposal['id'],decision='rejected'))[0],401)
        status,decision,_=live.request('POST','/api/operations/decide_delivery',owner['web_token'],dict(suggestion_id=proposal['id'],decision='rejected'),headers={'Origin':live.url})
        self.assertEqual(status,200,decision)
        self.assertEqual(decision['status'],'rejected')

    def test_local_observations_remain_observed_and_immutable_commit_can_reverse_lookup(self):
        observation=dict(request_key='git-one',workspace_id='w'*24,repository='github.com/acme/demo',branch='feature',head='a'*40,paths=['src/a'],captured_at=now().isoformat())
        self.s.repositories.observe(self.peer['agent_token'],self.task['id'],observation)
        result=self.s.read_deliveries(self.owner['web_token'],kind='commit',value='a'*40)
        relation=result['items'][0]['associations'][0]
        self.assertEqual(relation['relationship_source'],'observed')
        self.assertEqual(relation['source'],'local_git')
        self.assertEqual(result['items'][0]['task_ids'],[self.task['id']])

    def test_confirmation_failure_rolls_back_and_task_specific_retry_key_is_bound(self):
        suggestion=self.s.delivery.suggest(self.peer['agent_token'],task_id=self.task['id'],request_key='same',pr_number=7)
        second=self.task_for('second')
        with self.assertRaises(Conflict):self.s.delivery.suggest(self.peer['agent_token'],task_id=second['id'],request_key='same',pr_number=7)
        with self.s.identity.db.connect(write=True) as db:db.execute("UPDATE github_connections SET status='revoked'")
        with self.assertRaises(Conflict):self.s.delivery.decide(self.owner['web_token'],suggestion['id'],'confirmed')
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM delivery_suggestions WHERE id=?',(suggestion['id'],)).fetchone()[0],'pending')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM github_refs').fetchone()[0],0)


if __name__=='__main__':unittest.main()
