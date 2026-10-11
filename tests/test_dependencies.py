from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import unittest

from crewmesh.api import Service
from crewmesh.errors import AccessDenied, Conflict, NotFound, ValidationError


class DependencyTests(unittest.TestCase):
    def setUp(self):
        root=Path('.local/test-evidence'); root.mkdir(parents=True,exist_ok=True)
        self.path=root/('dependencies-'+str(uuid4())+'.sqlite3')
        self.s=Service(self.path)
        self.a=self.s.identity.create_room('Dependencies','Frontend')
        self.b=self.s.identity.add_member(self.a['web_token'],'Backend')
        self.c=self.s.identity.add_member(self.a['web_token'],'New teammate')
        self.source=self.task(self.a,'frontend','src/ui')
        self.target=self.task(self.b,'backend','src/api')
        self.auth={'session_key':'frontend','ownership_epoch':self.source['ownership_epoch']}
        self.target_auth={'session_key':'backend','ownership_epoch':self.target['ownership_epoch']}

    def task(self,who,key,scope,claim=True):
        t=self.s.tasks.create_task(who['web_token'],key,key,scope)
        return self.s.tasks.claim_task(who['agent_token'],t['id'],key) if claim else t

    def create(self,**extra):
        args=dict(source_task_id=self.source['id'],target_task_id=self.target['id'],need='Login response schema',context='Need user_id and expiry',expected_revision=self.source['revision'],request_key=str(uuid4()),**self.auth)
        args.update(extra)
        return self.s.call('create_dependency',self.a['agent_token'],args)

    def call(self,op,dep,who=None,**extra):
        args=dict(dependency_id=dep['id'],expected_revision=dep['revision'],request_key=str(uuid4()))
        args.update(extra)
        return self.s.call(op,(who or self.a)['web_token'],args)

    def test_reply_requires_latest_explicit_read_and_preserves_manual_blocker(self):
        dep=self.create(); self.assertEqual(dep['routing_state'],'routed')
        with self.assertRaises(ValidationError):
            self.s.dependencies.resolve_dependency(self.a['web_token'],dep['id'],dep['revision'],None,'invalid','Must not cancel')
        self.assertEqual(self.s.dependencies.snapshot(self.a['web_token'])[0]['status'],'active')
        self.s.activity.report_progress(self.a['agent_token'],self.source['id'],'blocked','Other local issue',**self.auth)
        dep=self.call('reply_dependency',dep,self.b,body='user_id: string',evidence='contract v1')
        args=dict(reply_id=dep['latest_reply']['id'],summary='Schema fits')
        with self.assertRaises(Conflict): self.call('resolve_dependency',dep,**args)
        self.s.checkpoints.checkpoint(self.a['agent_token'],'frontend','codex-cli','manual')
        with self.assertRaises(Conflict): self.call('resolve_dependency',dep,**args)
        self.s.call('read_dependency',self.b['web_token'],dict(dependency_id=dep['id']))
        with self.assertRaises(Conflict): self.call('resolve_dependency',dep,**args)
        self.s.call('read_dependency',self.a['web_token'],dict(dependency_id=dep['id']))
        later=self.call('reply_dependency',dep,self.b,body='Correction: user_id is UUID',evidence='contract v2')
        with self.assertRaises(Conflict): self.call('resolve_dependency',dep,**args)
        self.s.call('read_dependency',self.a['web_token'],dict(dependency_id=later['id']))
        done=self.call('resolve_dependency',later,reply_id=later['latest_reply']['id'],summary='Accepted')
        self.assertEqual(done['status'],'satisfied')
        self.assertEqual(self.s.activity.list_progress(self.a['web_token'])[0]['state'],'blocked')

    def test_generic_message_paths_cannot_bypass_dependency(self):
        dep=self.create(); request=dep['current_request_id']
        with self.assertRaises(Conflict): self.s.messages.reply(self.b['agent_token'],request,'generic',dep['route_version'],'Answer')
        with self.assertRaises(Conflict): self.s.messages.assign_receiver(self.a['web_token'],request,self.c['member_id'])
        dep=self.call('reply_dependency',dep,self.b,body='Answer')
        with self.assertRaises(Conflict): self.s.messages.resolve_request(self.a['agent_token'],request,dep['route_version'])

    def test_self_cross_project_cycle_and_concurrent_reverse_edges(self):
        with self.assertRaises(Conflict): self.create(target_task_id=self.source['id'])
        other=self.s.identity.create_room('Other','Owner'); foreign=self.task(other,'foreign','src')
        with self.assertRaises(NotFound): self.create(target_task_id=foreign['id'])
        barrier=__import__('threading').Barrier(2)
        def run(reverse):
            barrier.wait()
            source,target,who=(self.target,self.source,self.b) if reverse else (self.source,self.target,self.a)
            try: return self.s.call('create_dependency',who['web_token'],dict(source_task_id=source['id'],target_task_id=target['id'],need='Work',context='',expected_revision=source['revision'],request_key=str(uuid4())))
            except Conflict as e: return str(e)
        with ThreadPoolExecutor(2) as pool: result=list(pool.map(run,[False,True]))
        self.assertEqual(sum(isinstance(x,dict) for x in result),1)
        self.assertIn('cycle',next(x for x in result if isinstance(x,str)).lower())

    def test_scope_lookup_returns_all_evidence_and_excludes_cancelled(self):
        self.task(self.c,'nested','src/api/auth',False)
        result=self.s.call('lookup_owner',self.a['web_token'],dict(scope='src/api/auth/login'))
        self.assertEqual(result['status'],'ambiguous'); self.assertEqual(len(result['candidates']),2)
        self.assertEqual(self.s.call('lookup_owner',self.a['web_token'],dict(scope='src/apian'))['status'],'not_found')


    def transfer(self,task,target):
        current=next(t for t in self.s.tasks.list_tasks(self.a['web_token']) if t['id']==task['id'])
        return self.s.call('force_handoff',self.a['web_token'],dict(task_id=task['id'],expected_revision=current['revision'],request_key=str(uuid4()),summary='New responsibility',target_member_id=target['member_id']))

    def test_owner_changes_keep_history_receipts_and_reroute_both_sides(self):
        dep=self.create(); old=dep['current_request_id']
        self.s.messages.read_inbox(self.b['agent_token'])
        dep=self.call('reply_dependency',dep,self.b,body='Original answer')
        self.s.call('read_dependency',self.a['web_token'],dict(dependency_id=dep['id']))
        self.transfer(self.target,self.c)
        routed=self.s.dependencies.snapshot(self.a['web_token'])[0]
        self.assertNotEqual(routed['current_request_id'],old); self.assertIsNone(routed['latest_reply'])
        requests=self.s.messages.list_requests(self.a['web_token'])
        history=next(r for r in requests if r['id']==old)
        self.assertEqual(history['dependency_route_state'],'historical'); self.assertIsNotNone(history['read_at'])
        self.assertEqual(len(history['replies']),1)
        self.assertEqual(requests[-1]['receiver_member_id'],self.c['member_id'])
        with self.assertRaises(AccessDenied): self.call('reply_dependency',routed,self.b,body='Late reply')
        with self.assertRaises(Conflict): self.call('resolve_dependency',routed,reply_id=dep['latest_reply']['id'],summary='Old answer')
        brief=self.s.checkpoints.checkpoint(self.a['agent_token'],'frontend','codex-cli','manual')['brief']
        self.assertNotIn(old,[r['id'] for r in brief['requests']])
        self.transfer(self.source,self.b)
        rerouted=self.s.dependencies.snapshot(self.a['web_token'])[0]
        request=next(r for r in self.s.messages.list_requests(self.a['web_token']) if r['id']==rerouted['current_request_id'])
        self.assertEqual(request['sender_member_id'],self.b['member_id'])
        with self.assertRaises(AccessDenied): self.call('resolve_dependency',rerouted,reply_id=dep['latest_reply']['id'],summary='No longer owner')
        self.s=Service(self.path)
        self.assertEqual(len(self.s.dependencies.read_dependency(self.b['web_token'],dep['id'])['routes']),3)
        with self.s.identity.db.connect() as db:self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_unassigned_source_target_claim_and_cancel_reopen(self):
        source=self.task(self.a,'planning','src/plan',False); target=self.task(self.b,'future','src/future',False)
        dep=self.s.call('create_dependency',self.a['web_token'],dict(source_task_id=source['id'],target_task_id=target['id'],need='Plan',expected_revision=source['revision'],request_key='planning'))
        self.assertEqual(dep['routing_state'],'waiting_source');self.assertIsNone(dep['current_request_id'])
        self.s.tasks.claim_task(self.a['agent_token'],source['id'],'planning')
        dep=self.s.dependencies.snapshot(self.a['web_token'])[0];self.assertEqual(dep['routing_state'],'unassigned')
        target=self.s.tasks.claim_task(self.b['agent_token'],target['id'],'future')
        dep=self.s.dependencies.snapshot(self.a['web_token'])[0];self.assertEqual(dep['routing_state'],'routed')
        target=self.s.call('cancel_task',self.b['web_token'],dict(task_id=target['id'],expected_revision=target['revision'],request_key='cancel-target',summary='Unavailable'))
        dep=self.s.dependencies.snapshot(self.a['web_token'])[0];self.assertEqual(dep['routing_state'],'target_cancelled');self.assertTrue(dep['blocked'])
        source=next(t for t in self.s.tasks.list_tasks(self.a['web_token']) if t['id']==source['id'])
        source=self.s.call('cancel_task',self.a['web_token'],dict(task_id=source['id'],expected_revision=source['revision'],request_key='cancel-source',summary='No longer needed'))
        dep=self.s.dependencies.snapshot(self.a['web_token'])[0];self.assertEqual(dep['status'],'cancelled')
        self.assertIn('No longer needed',dep['closed_reason'])
        self.s.call('reopen_task',self.a['web_token'],dict(task_id=source['id'],expected_revision=source['revision'],request_key='reopen-source',summary='New cycle'))
        self.assertEqual(self.s.dependencies.snapshot(self.a['web_token'])[0]['status'],'cancelled')

    def test_session_epoch_permission_idempotency_and_read_identity(self):
        args=dict(source_task_id=self.source['id'],target_task_id=self.target['id'],need='Contract',expected_revision=self.source['revision'],request_key='once',**self.auth)
        with self.assertRaises(AccessDenied): self.s.call('create_dependency',self.c['agent_token'],args)
        with self.assertRaises(Conflict): self.s.call('create_dependency',self.a['agent_token'],dict(args,session_key='different'))
        dep=self.s.call('create_dependency',self.a['agent_token'],args)
        self.assertEqual(self.s.call('create_dependency',self.a['agent_token'],args),dep)
        with self.assertRaises(Conflict): self.s.call('create_dependency',self.a['agent_token'],dict(args,need='Changed'))
        reply=dict(dependency_id=dep['id'],expected_revision=dep['revision'],request_key='reply',body='Ready',**self.target_auth)
        with self.assertRaises(Conflict): self.s.call('reply_dependency',self.b['agent_token'],dict(reply,ownership_epoch=0))
        dep=self.s.call('reply_dependency',self.b['agent_token'],reply)
        self.assertEqual(self.s.call('reply_dependency',self.b['agent_token'],reply),dep)
        self.assertEqual(dep['latest_reply']['actor_kind'],'agent')
        self.s.call('read_dependency',self.a['web_token'],dict(dependency_id=dep['id']))
        close=dict(dependency_id=dep['id'],expected_revision=dep['revision'],request_key='done',summary='Accepted',reply_id=dep['latest_reply']['id'],**self.auth)
        with self.assertRaises(Conflict):self.s.call('resolve_dependency',self.a['agent_token'],close)
        self.s.call('read_dependency',self.a['agent_token'],dict(dependency_id=dep['id'],**self.auth))
        self.assertEqual(self.s.call('resolve_dependency',self.a['agent_token'],close)['status'],'satisfied')
        self.assertEqual(self.s.call('resolve_dependency',self.a['agent_token'],close)['status'],'satisfied')

    def test_planning_permissions_and_unbound_legacy_agent_read(self):
        planning=self.task(self.b,'private-plan','src/plan',False)
        with self.assertRaises(AccessDenied):self.s.call('create_dependency',self.c['web_token'],dict(source_task_id=planning['id'],target_task_id=self.target['id'],need='No',expected_revision=0,request_key='unauthorized'))
        legacy=self.s.tasks.create_task(self.a['web_token'],'legacy','Legacy','legacy')
        legacy=self.s.tasks.claim_task(self.a['agent_token'],legacy['id'])
        dep=self.s.call('create_dependency',self.a['agent_token'],dict(source_task_id=legacy['id'],target_task_id=self.target['id'],need='Legacy contract',expected_revision=legacy['revision'],request_key='legacy'))
        dep=self.call('reply_dependency',dep,self.b,body='Answer')
        result=self.s.call('read_dependency',self.a['agent_token'],dict(dependency_id=dep['id']))
        self.assertTrue(result['read_recorded'])

    def test_three_node_cycle_and_cancelled_scope_exclusion(self):
        dep=self.create(); third=self.task(self.c,'third','src/third')
        self.s.call('create_dependency',self.b['web_token'],dict(source_task_id=self.target['id'],target_task_id=third['id'],need='Work',expected_revision=third['revision'],request_key='second'))
        with self.assertRaisesRegex(Conflict,'cycle'):
            self.s.call('create_dependency',self.c['web_token'],dict(source_task_id=third['id'],target_task_id=self.source['id'],need='Work',expected_revision=third['revision'],request_key='third'))
        self.call('cancel_dependency',dep,summary='No longer needed')
        third=self.s.call('cancel_task',self.c['web_token'],dict(task_id=third['id'],expected_revision=third['revision'],request_key='cancel-third',summary='Removed'))
        self.assertEqual(self.s.call('lookup_owner',self.a['web_token'],dict(task_id=third['id']))['status'],'not_found')

    def test_snapshot_checkpoint_are_bounded_peeks_and_progress_is_derived(self):
        import json
        for index in range(9):
            target=self.task(self.b,'target-'+str(index),'src/t'+str(index))
            self.create(target_task_id=target['id'],need='需'*500,context='文'*3000)
        brief=self.s.checkpoints.checkpoint(self.a['agent_token'],'frontend','codex-cli','manual')['brief']
        self.assertLessEqual(len(json.dumps(brief,ensure_ascii=False).encode()),16000)
        self.assertTrue(brief['truncated']);self.assertIn('dependencies',brief)
        self.assertEqual(sum(d['status']=='active' and d['source_task_id']==self.source['id'] for d in self.s.dependencies.snapshot(self.a['web_token'])),9)
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dependency_reads').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_receipts').fetchone()[0],0)


    def test_handoff_and_route_failure_roll_back_together(self):
        import sqlite3
        dep=self.create()
        self.s.activity.report_progress(self.a['agent_token'],self.source['id'],'working','Keep this',**self.auth)
        with self.s.identity.db.connect(write=True) as db:
            db.execute("CREATE TRIGGER fail_route BEFORE INSERT ON dependency_routes BEGIN SELECT RAISE(ABORT,'route unavailable'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.transfer(self.source,self.b)
        source=next(t for t in self.s.tasks.list_tasks(self.a['web_token']) if t['id']==self.source['id'])
        self.assertEqual(source['owner_member_id'],self.a['member_id'])
        self.assertEqual(self.s.activity.list_progress(self.a['web_token'])[0]['summary'],'Keep this')
        self.assertEqual(self.s.dependencies.snapshot(self.a['web_token'])[0],dep)
        self.assertEqual(len(self.s.messages.list_requests(self.a['web_token'])),1)

if __name__=='__main__': unittest.main()
