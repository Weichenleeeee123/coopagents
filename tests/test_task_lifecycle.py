from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import unittest

from coopagents.api import Service
from coopagents.errors import AccessDenied, Conflict, NotFound
from test_github_sync import FakeProvider


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        root = Path('.local/test-evidence'); root.mkdir(parents=True, exist_ok=True)
        self.path = root / ('lifecycle-' + str(uuid4()) + '.sqlite3')
        self.s = Service(self.path, FakeProvider())
        self.owner = self.s.identity.create_room('Room', 'Owner')
        self.a = self.s.identity.add_member(self.owner['web_token'], 'Alice')
        self.b = self.s.identity.add_member(self.owner['web_token'], 'Bob')
        self.task = self.s.tasks.create_task(self.a['web_token'], 'task', 'Implement feature', 'src')
        self.assertIn('release_task', self.s.operations, 'Lifecycle operations are missing')

    def claim(self, who=None, session='one'):
        self.task = self.s.tasks.claim_task((who or self.a)['agent_token'], self.task['id'], session_key=session)
        return self.task

    def change(self, action, who=None, kind='web', **extra):
        args = dict(task_id=self.task['id'], expected_revision=self.task['revision'], request_key=str(uuid4()), summary='Context: preserve branch feature', **extra)
        self.task = self.s.call(action, (who or self.a)[kind+'_token'], args)
        return self.task

    def report(self, who=None, session='one', epoch=None):
        return self.s.activity.report_progress((who or self.a)['agent_token'], self.task['id'], 'local_done', 'Ready', session_key=session, ownership_epoch=epoch if epoch is not None else self.task['ownership_epoch'])

    def test_transfer_archives_progress_sessions_and_isolates_same_member_sessions(self):
        self.claim(); old_epoch = self.task['ownership_epoch']
        self.s.activity.register_session(self.a['agent_token'], 'one', 'codex-cli', 'repo', 'feature', self.task['id'], ownership_epoch=old_epoch)
        self.report()
        with self.assertRaises(Conflict): self.report(session='two')
        with self.assertRaises(Conflict): self.report(session=None)
        self.change('propose_handoff', kind='agent', target_member_id=self.b['member_id'], session_key='one', ownership_epoch=old_epoch)
        brief = self.s.checkpoints.checkpoint(self.b['agent_token'], 'bob', 'codex-cli', 'startup')['brief']
        self.assertEqual(brief['handoffs'][0]['task_id'], self.task['id'])
        self.change('accept_handoff', self.b)
        self.assertEqual(self.task['owner_member_id'], self.b['member_id'])
        self.assertEqual(self.s.activity.list_progress(self.b['web_token']), [])
        self.assertTrue(all(s['task_id'] is None for s in self.s.activity.list_sessions(self.b['web_token'])))
        with self.assertRaises(AccessDenied): self.report(epoch=old_epoch)
        self.claim(self.b, 'bob'); self.report(self.b, 'bob')
        history = self.s.lifecycle.snapshot(self.b['web_token'])['history']
        archived = next(h for h in history if h['action']=='accept_handoff')['context']
        self.assertEqual(archived['progress']['summary'], 'Ready')
        self.assertEqual(archived['sessions'][0]['session_key'], 'one')
        with self.s.identity.db.connect() as db: self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_release_reclaim_cannot_resurrect_old_session_or_progress(self):
        self.claim(); old = self.task['ownership_epoch']; self.report()
        self.change('release_task', kind='agent', session_key='one', ownership_epoch=old)
        with self.assertRaises(Conflict): self.claim(session='one')
        self.claim(session='two')
        with self.assertRaises(Conflict): self.report(epoch=old)
        self.assertEqual(self.s.activity.list_progress(self.a['web_token']), [])
        self.report(session='two')
        self.s = Service(self.path, FakeProvider())
        self.assertEqual(self.s.tasks.list_tasks(self.a['agent_token'])[0]['execution_session_key'], 'two')

    def test_cancel_reopen_and_creator_permissions(self):
        with self.assertRaises(AccessDenied): self.change('cancel_task', self.b)
        self.change('cancel_task')
        self.assertEqual(self.task['state'], 'cancelled')
        with self.assertRaises(Conflict): self.claim()
        self.change('reopen_task')
        self.assertEqual(self.task['state'], 'open')
        self.claim(); self.report()
        with self.assertRaises(AccessDenied): self.change('cancel_task', kind='agent')
        self.change('cancel_task'); self.change('reopen_task')
        self.assertEqual(self.s.activity.list_progress(self.a['web_token']), [])

    def test_cancel_hides_declared_overlap_and_reopen_restores_it(self):
        other = self.s.tasks.create_task(self.b['web_token'], 'overlap', 'Related work', 'src/feature')
        expected = [self.task['id'], other['id']]
        self.assertEqual(self.s.activity.overlaps(self.a['web_token'])[0]['task_ids'], expected)
        self.change('cancel_task')
        self.assertEqual(self.s.activity.overlaps(self.a['web_token']), [])
        self.change('reopen_task')
        self.assertEqual(self.s.activity.overlaps(self.a['web_token'])[0]['task_ids'], expected)

    def test_payload_aware_idempotence_stale_revision_and_agent_boundaries(self):
        self.claim()
        args = dict(task_id=self.task['id'], expected_revision=self.task['revision'], request_key='retry', summary='Handoff', target_member_id=self.b['member_id'], session_key='one', ownership_epoch=self.task['ownership_epoch'])
        self.task = self.s.call('propose_handoff', self.a['agent_token'], args)
        self.assertEqual(self.s.call('propose_handoff', self.a['agent_token'], args), self.task)
        with self.assertRaises(Conflict): self.s.call('propose_handoff', self.a['agent_token'], dict(args, summary='Changed'))
        for operation in ('accept_handoff','reject_handoff','force_handoff'):
            with self.assertRaises(AccessDenied): self.change(operation, self.b, kind='agent')
        with self.assertRaises(Conflict): self.s.call('release_task', self.a['web_token'], {k:v for k,v in args.items() if k not in ('target_member_id','session_key','ownership_epoch')})
        self.change('reject_handoff', self.b)
        self.assertEqual(self.task['owner_member_id'], self.a['member_id'])

    def test_accept_force_race_has_single_winner(self):
        self.claim(); self.change('propose_handoff', target_member_id=self.b['member_id'])
        args = dict(task_id=self.task['id'], expected_revision=self.task['revision'], request_key='accept', summary='Take over')
        def run(entry):
            op, who, extra = entry
            try: return self.s.call(op, who['web_token'], dict(args, **extra))
            except Conflict: return None
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(run, [('accept_handoff', self.b, {}), ('force_handoff', self.owner, {'target_member_id':self.owner['member_id']})]))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_git_history_never_drives_next_epoch_and_refs_can_be_relinked(self):
        self.claim(); self.s.repositories.bind_repository(self.owner['web_token'], 'github.com/acme/demo')
        begun = self.s.github.begin_authorization(self.owner['web_token'])
        self.s.github.complete_authorization(begun['state'], 'code'); self.s.github.finish_authorization(self.owner['web_token'], begun['state'])
        auth = dict(session_key='one', ownership_epoch=self.task['ownership_epoch'])
        first = self.s.github.associate(self.a['agent_token'], self.task['id'], pr_number=7, **auth)
        self.s.github.app.current['pull_requests'][0]['merged'] = True
        self.s.github.refresh(self.owner['web_token'])
        from coopagents.tasks import _utc_now
        observation = dict(request_key='original', workspace_id='workspace_original', repository='github.com/acme/demo', branch='feature',head='a'*40,paths=['src/a'],captured_at=_utc_now())
        self.s.repositories.observe(self.a['agent_token'], self.task['id'], observation, **auth)
        self.assertEqual(self.s.git_snapshot(self.a['web_token'])['deliveries'][0]['state'], 'merged')
        self.change('release_task'); self.claim(session='new')
        snap = self.s.git_snapshot(self.a['web_token'])
        self.assertEqual(snap['deliveries'], []); self.assertEqual(snap['workspaces'], [])
        self.assertTrue(snap['events'][0]['historical'])
        with self.assertRaises(Conflict): self.s.repositories.observe(self.a['agent_token'], self.task['id'], observation, **auth)
        second = self.s.github.associate(self.a['agent_token'], self.task['id'], pr_number=7, session_key='new', ownership_epoch=self.task['ownership_epoch'])
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(self.s.git_snapshot(self.a['web_token'])['deliveries'], [])
        self.s.github.refresh(self.owner['web_token'])
        self.assertEqual(self.s.git_snapshot(self.a['web_token'])['deliveries'][0]['ownership_epoch'], self.task['ownership_epoch'])

    def test_all_task_bound_activity_requires_current_session_and_epoch(self):
        self.claim(); epoch=self.task['ownership_epoch']
        for session, generation in [('two',epoch), ('one',epoch-1), ('one',None)]:
            with self.subTest(session=session, generation=generation):
                with self.assertRaises(Conflict):
                    self.s.activity.register_session(self.a['agent_token'],session,'codex-cli','repo','feature',self.task['id'],ownership_epoch=generation)
                with self.assertRaises(Conflict):
                    self.s.checkpoints.checkpoint(self.a['agent_token'],session,'codex-cli','startup',self.task['id'],ownership_epoch=generation)
        self.change('force_handoff',self.owner,target_member_id=self.b['member_id'])
        with self.assertRaises(Conflict): self.report(self.b,session='unbound')
        self.claim(self.b,'bob')
        self.s.checkpoints.checkpoint(self.b['agent_token'],'bob','codex-cli','startup',self.task['id'],ownership_epoch=self.task['ownership_epoch'])

    def test_target_and_action_permissions_do_not_cross_project(self):
        other=self.s.identity.create_room('Other','Other')
        self.claim()
        with self.assertRaises(NotFound): self.change('propose_handoff',target_member_id=other['member_id'])
        with self.assertRaises(NotFound): self.change('force_handoff',other,target_member_id=self.b['member_id'])
        with self.assertRaises(AccessDenied): self.change('force_handoff',self.a,target_member_id=self.b['member_id'])
        with self.assertRaises(AccessDenied): self.change('release_task',self.b)
        with self.assertRaises(AccessDenied): self.change('propose_handoff',self.b,kind='agent',target_member_id=self.owner['member_id'])

    def test_project_admin_can_force_but_inactive_team_target_cannot_receive(self):
        accounts=self.s.accounts;workspaces=self.s.workspaces
        account=accounts.oauth_account('github','1001','owner')
        owner_session=accounts.create_session(account['id'])['session_token']
        team=workspaces.create_team(owner_session,'Team')['team_id']
        room=workspaces.create_project(owner_session,team,'Managed')['room_id']
        owner=workspaces.project_credential(owner_session,room)
        people=[]
        for index,role in enumerate(('admin','member')):
            account=accounts.oauth_account('github',str(1002+index),role)
            session=accounts.create_session(account['id'])['session_token']
            invite=workspaces.create_invite(owner_session,team,role,[room])
            workspaces.accept_invite(invite['invite_token'],session_token=session)
            people.append((account,workspaces.project_credential(session,room)))
        admin,target=people[0][1],people[1][1]
        agent=self.s.identity.rotate_agent(owner['web_token'])['agent_token']
        task=self.s.tasks.create_task(owner['web_token'],'managed','Task','src')
        task=self.s.tasks.claim_task(agent,task['id'])
        self.assertTrue(self.s.lifecycle.snapshot(admin['web_token'])['can_manage'])
        args=dict(task_id=task['id'],expected_revision=task['revision'],request_key='force',summary='Admin takeover',target_member_id=target['member_id'])
        with self.s.identity.db.connect(write=True) as db:
            db.execute('UPDATE team_members SET active=0 WHERE team_id=? AND account_id=?',(team,people[1][0]['id']))
        with self.assertRaises(AccessDenied):self.s.call('force_handoff',admin['web_token'],args)
        with self.s.identity.db.connect(write=True) as db:
            db.execute('UPDATE team_members SET active=1 WHERE team_id=? AND account_id=?',(team,people[1][0]['id']))
        result=self.s.call('force_handoff',admin['web_token'],args)
        self.assertEqual(result['owner_member_id'],target['member_id'])

    def test_history_paginates_and_pending_handoffs_are_not_buried_by_closed_records(self):
        self.claim();self.change('propose_handoff',target_member_id=self.b['member_id'])
        with self.s.identity.db.connect(write=True) as db:
            for _ in range(105):
                db.execute("""INSERT INTO task_handoffs(room_id,task_id,from_member_id,target_member_id,
                    proposed_by,summary,status,created_at) VALUES(?,?,?,?,?,?,'rejected',?)""",
                    (self.task['room_id'],self.task['id'],self.a['member_id'],self.b['member_id'],self.a['member_id'],'old','2026-01-01'))
        snapshot=self.s.lifecycle.snapshot(self.b['web_token'])
        self.assertTrue(any(h['status']=='pending' for h in snapshot['handoffs']))
        self.assertIn('read_task_history',self.s.operations)
        scoped=self.s.call('read_task_history',self.b['web_token'],dict(task_id=self.task['id'],limit=1))
        self.assertEqual(scoped['handoff']['target_member_id'],self.b['member_id'])
        self.assertEqual(scoped['task']['revision'],self.task['revision'])
        self.change('reject_handoff',self.b)
        self.assertIn('read_task_history',self.s.operations)
        first=self.s.call('read_task_history',self.a['agent_token'],dict(task_id=self.task['id'],limit=1))
        second=self.s.call('read_task_history',self.a['agent_token'],dict(task_id=self.task['id'],limit=1,before_id=first['next_before_id']))
        self.assertEqual(first['events'][0]['action'],'reject_handoff')
        self.assertEqual(second['events'][0]['action'],'propose_handoff')
        third=self.s.call('read_task_history',self.a['agent_token'],dict(task_id=self.task['id'],limit=1,before_id=second['next_before_id']))
        self.assertEqual(third['events'][0]['action'],'claim_task')
        self.assertIsNone(third['next_before_id'])

    def test_old_database_migration_preserves_activity_and_then_archives_it(self):
        from unittest.mock import patch
        from coopagents.identity import IdentityStore
        from coopagents.tasks import _utc_now
        old_path=self.path.with_name('old-'+self.path.name)
        with patch('coopagents.task_lifecycle.initialize'):
            old=IdentityStore(old_path)
        person=old.create_room('Legacy','Legacy owner');now=_utc_now()
        with old.db.connect(write=True) as db:
            task_id=db.execute("""INSERT INTO tasks(room_id,intent_key,title,scope,state,owner_member_id,created_at,claimed_at)
                VALUES(?,?,?,?,'claimed',?,?,?)""",(person['room_id'],'legacy','Legacy','src',person['member_id'],now,now)).lastrowid
            db.execute("INSERT INTO sessions(room_id,member_id,session_key,tool,repository,branch,task_id,updated_at) VALUES(?,?,?,'codex-cli',?,?,?,?)",(person['room_id'],person['member_id'],'old-session','repo','legacy',task_id,now))
            db.execute("INSERT INTO progress VALUES(?,?,?,'local_done','Legacy done','','agent_report',?)",(task_id,person['room_id'],person['member_id'],now))
        migrated=Service(old_path,FakeProvider())
        task=migrated.tasks.list_tasks(person['web_token'])[0]
        self.assertEqual(task['ownership_epoch'],0)
        self.assertEqual(migrated.activity.list_progress(person['web_token'])[0]['state'],'local_done')
        target=migrated.identity.add_member(person['web_token'],'Next owner')
        transferred=migrated.call('force_handoff',person['web_token'],dict(task_id=task_id,expected_revision=0,request_key='migration',summary='Archive legacy',target_member_id=target['member_id']))
        self.assertEqual(transferred['ownership_epoch'],1)
        with self.assertRaises(Conflict):migrated.activity.report_progress(target['agent_token'],task_id,'working','Must bind first')
        reopened=Service(old_path,FakeProvider())
        self.assertEqual(reopened.activity.list_progress(person['web_token']),[])
        self.assertEqual(reopened.lifecycle.snapshot(person['web_token'])['history'][0]['context']['progress']['summary'],'Legacy done')
        current=reopened.tasks.list_tasks(person['web_token'])[0]
        reopened.call('force_handoff',person['web_token'],dict(task_id=task_id,expected_revision=current['revision'],request_key='return',summary='Return legacy work',target_member_id=person['member_id']))
        with self.assertRaises(Conflict):reopened.tasks.claim_task(person['agent_token'],task_id,session_key='old-session')
        with reopened.identity.db.connect() as db:self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_legacy_observation_payload_retry_survives_upgrade(self):
        import hashlib,json
        from coopagents.tasks import _utc_now
        self.claim(session=None)
        self.s.repositories.bind_repository(self.owner['web_token'],'github.com/acme/demo')
        observation=dict(request_key='legacy',workspace_id='legacy_workspace_1',repository='github.com/acme/demo',branch='feature',head='a'*40,paths=['src/a'],captured_at=_utc_now())
        first=self.s.repositories.observe(self.a['agent_token'],self.task['id'],observation)
        normalized=self.s.repositories.validate_observation(observation)
        old_hash=hashlib.sha256(json.dumps([self.task['id'],normalized],sort_keys=True).encode()).hexdigest()
        with self.s.identity.db.connect(write=True) as db:db.execute('UPDATE git_observations SET payload_hash=? WHERE id=?',(old_hash,first['id']))
        retried=self.s.repositories.observe(self.a['agent_token'],self.task['id'],observation)
        self.assertEqual(retried,first)

    def test_claim_archives_preclaim_delivery_and_allows_current_epoch_reassociation(self):
        self.s.repositories.bind_repository(self.owner['web_token'],'github.com/acme/demo')
        begun=self.s.github.begin_authorization(self.owner['web_token'])
        self.s.github.complete_authorization(begun['state'],'code');self.s.github.finish_authorization(self.owner['web_token'],begun['state'])
        first=self.s.github.associate(self.owner['web_token'],self.task['id'],pr_number=7)
        self.claim()
        second=self.s.github.associate(self.a['agent_token'],self.task['id'],pr_number=7,session_key='one',ownership_epoch=self.task['ownership_epoch'])
        self.assertNotEqual(first['id'],second['id'])
        history=self.s.lifecycle.snapshot(self.a['web_token'])['history']
        self.assertEqual(history[0]['action'],'claim_task')
        self.assertEqual(history[0]['context']['github_refs'][0]['id'],first['id'])

    def test_legacy_registered_sessions_and_task_checkpoints_cannot_rebind_after_release(self):
        self.claim(session=None)
        self.s.activity.register_session(self.a['agent_token'],'legacy-session','codex-cli','repo','feature',self.task['id'])
        self.s.checkpoints.checkpoint(self.a['agent_token'],'legacy-hook','codex-cli','startup',self.task['id'])
        self.change('release_task')
        for key in ('legacy-session','legacy-hook'):
            with self.subTest(key=key),self.assertRaises(Conflict):self.claim(session=key)
        self.claim(session='new-after-legacy');self.report(session='new-after-legacy')

    def test_team_adoption_preserves_handoff_to_existing_legacy_collaborators(self):
        self.claim()
        account=self.s.accounts.oauth_account('github','1099','Manager')
        session=self.s.accounts.create_session(account['id'])['session_token']
        team=self.s.workspaces.create_team(session,'Adopted')['team_id']
        self.s.workspaces.claim_legacy_project(session,team,self.owner['web_token'])
        self.s.identity.authenticate(self.b['web_token'])
        self.assertFalse(self.s.lifecycle.snapshot(self.b['web_token'])['can_manage'])
        self.change('propose_handoff',target_member_id=self.b['member_id'])
        self.change('accept_handoff',self.b)
        self.assertEqual(self.task['owner_member_id'],self.b['member_id'])

if __name__ == '__main__': unittest.main()
