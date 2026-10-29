"""Offline domain tests. FakeProvider is not live GitHub acceptance evidence."""
from copy import deepcopy
from pathlib import Path
import hashlib
import hmac
import json
import unittest
from uuid import uuid4
from datetime import timedelta

from coopagents.identity import IdentityStore
from coopagents.repositories import RepositoryStore
from coopagents.tasks import TaskStore
from coopagents.errors import AccessDenied, Conflict, NotFound, ValidationError
from coopagents.github_app import GitHubError
from coopagents.github_sync import GitHubSync
from coopagents.repositories import now,timestamp


class FakeProvider:
    enabled = True
    webhook_secret = 'offline-secret'
    def __init__(self):
        self.denied = False
        self.fail = False
        self.current = {'repository_id': 11, 'full_name': 'acme/demo',
            'branches': {'feature': 'a'*40}, 'pull_requests': [{
                'number': 7, 'state': 'closed', 'merged': False,
                'head_sha': 'b'*40, 'head_repository_id': 99, 'head_branch': 'feature',
                'checks': [{'head_sha': 'b'*40, 'status': 'completed', 'conclusion': 'success'}],
                'statuses': []}]}
    def authorization_url(self, state):
        return 'https://github.com/login/oauth/authorize?state=' + state
    def exchange_code(self, code):
        return 'EPHEMERAL_USER_TOKEN'
    def verify_user_repository(self, user_token, repository, installation_id=None):
        if self.denied or repository != 'github.com/acme/demo':
            raise AccessDenied('GitHub repository access not accepted')
        return {'installation_id': 22, 'repository_id': 11, 'full_name': 'acme/demo'}
    def verify_repository(self, installation_id, repository_id, full_name):
        if self.denied:
            raise AccessDenied('GitHub repository access not accepted')
        return {'id': 11, 'full_name': 'acme/demo'}
    def repository_state(self, installation_id, repository_id, full_name, branches=(), pr_numbers=(),commit_shas=()):
        if self.fail:
            raise GitHubError('GitHub unavailable', retryable=True)
        self.verify_repository(installation_id, repository_id, full_name)
        return deepcopy(self.current)


class GitHubSyncTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / str(uuid4())
        self.root.mkdir(parents=True)
        self.identity = IdentityStore(self.root / 'github.sqlite3')
        self.owner = self.identity.create_room('Team', 'Owner')
        self.member = self.identity.add_member(self.owner['web_token'], 'Member')
        self.other = self.identity.create_room('Other', 'Other')
        self.repositories = RepositoryStore(self.identity)
        self.repositories.bind_repository(self.owner['web_token'], 'github.com/acme/demo')
        self.tasks = TaskStore(self.identity)
        self.task = self.tasks.create_task(self.owner['web_token'], 'task', 'Task', 'src')
        self.tasks.claim_task(self.member['agent_token'], self.task['id'])
        self.app = FakeProvider()
        self.sync = GitHubSync(self.identity, self.repositories, self.app)

    def connect(self):
        begun = self.sync.begin_authorization(self.owner['web_token'])
        self.sync.complete_authorization(begun['state'], 'code')
        self.sync.finish_authorization(self.owner['web_token'], begun['state'])

    def webhook(self, delivery='delivery', event='push', payload=None):
        body = json.dumps(payload or {'installation': {'id': 22}, 'repository': {'id': 11}}).encode()
        signature = 'sha256=' + hmac.new(self.app.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return self.sync.receive_webhook(delivery, event, signature, body)

    def test_oauth_requires_manager_initiator_fresh_permissions_and_one_use(self):
        with self.assertRaises(AccessDenied): self.sync.begin_authorization(self.member['web_token'])
        begun = self.sync.begin_authorization(self.owner['web_token'])
        with self.assertRaises(AccessDenied): self.sync.complete_authorization('forged', 'code')
        self.sync.complete_authorization(begun['state'], 'code')
        self.assertIsNone(self.sync.snapshot(self.owner['web_token'])['connection'])
        with self.assertRaises(AccessDenied): self.sync.finish_authorization(self.other['web_token'], begun['state'])
        self.app.denied = True
        with self.assertRaises(AccessDenied): self.sync.finish_authorization(self.owner['web_token'], begun['state'])
        self.app.denied = False
        self.sync.finish_authorization(self.owner['web_token'], begun['state'])
        with self.assertRaises(AccessDenied): self.sync.finish_authorization(self.owner['web_token'], begun['state'])
        self.assertNotIn('EPHEMERAL_USER_TOKEN', self.root.joinpath('github.sqlite3').read_bytes().decode(errors='ignore'))

    def test_demoted_manager_cannot_finish(self):
        begun = self.sync.begin_authorization(self.owner['web_token'])
        self.sync.complete_authorization(begun['state'], 'code')
        with self.identity.db.connect(write=True) as c:
            c.execute("UPDATE members SET role='member' WHERE id=?", (self.owner['member_id'],))
        with self.assertRaises(AccessDenied): self.sync.finish_authorization(self.owner['web_token'], begun['state'])

    def test_refs_scoped_fork_requires_explicit_pr_closed_is_not_merged(self):
        self.connect()
        with self.assertRaises(NotFound): self.sync.associate(self.other['agent_token'], self.task['id'], pr_number=7)
        with self.assertRaises(AccessDenied): self.sync.associate(self.owner['agent_token'], self.task['id'], pr_number=7)
        self.sync.associate(self.member['agent_token'], self.task['id'], branch='feature')
        self.sync.refresh(self.member['agent_token'])
        view = self.sync.snapshot(self.owner['web_token'])
        self.assertEqual(len(view['deliveries']), 1)
        self.assertEqual(view['deliveries'][0]['head_sha'], 'a'*40)
        self.assertEqual(view['github_pending'][0]['number'], 7)
        self.sync.associate(self.owner['web_token'], self.task['id'], pr_number=7)
        self.sync.refresh(self.owner['web_token'])
        view = self.sync.snapshot(self.owner['web_token'])
        pr = next(v for v in view['deliveries'] if v.get('pr_number') == 7)
        self.assertEqual(pr['state'], 'closed_unmerged')
        self.assertEqual(pr['url'], 'https://github.com/acme/demo/pull/7')
        self.assertEqual(pr['source'], 'github_verified')
        self.assertEqual(self.sync.snapshot(self.other['web_token'])['deliveries'], [])

    def test_old_head_checks_are_not_current_evidence(self):
        self.connect()
        self.sync.associate(self.member['agent_token'], self.task['id'], pr_number=7)
        self.app.current['pull_requests'][0]['head_sha'] = 'c'*40
        self.sync.refresh(self.owner['web_token'])
        pr = self.sync.snapshot(self.owner['web_token'])['deliveries'][0]
        self.assertEqual(pr['checks'], [])
        self.assertEqual(pr['head_sha'], 'c'*40)

    def test_signed_inbox_dedup_conflicts_restart_retry_and_replay(self):
        self.connect()
        self.sync.associate(self.member['agent_token'], self.task['id'], branch='feature')
        with self.assertRaises(AccessDenied): self.sync.receive_webhook('bad','push','sha256='+'0'*64,b'{}')
        self.webhook()
        self.assertTrue(self.webhook()['duplicate'])
        with self.assertRaises(Conflict): self.webhook(payload={'installation': {'id':22},'repository': {'id':11},'ref':'changed'})
        reopened = GitHubSync(self.identity, self.repositories, self.app)
        self.app.fail = True
        reopened.process_pending()
        with self.identity.db.connect(write=True) as c: c.execute("UPDATE github_inbox SET next_attempt_at='' ")
        self.app.fail = False
        self.app.current['branches']['feature'] = 'd'*40
        reopened.process_pending()
        self.assertEqual(reopened.snapshot(self.owner['web_token'])['deliveries'][0]['head_sha'], 'd'*40)
        self.webhook('old-replay', payload={'installation':{'id':22},'repository':{'id':11},'after':'a'*40})
        reopened.process_pending()
        self.assertEqual(reopened.snapshot(self.owner['web_token'])['deliveries'][0]['head_sha'], 'd'*40)

    def test_revocation_removes_active_evidence(self):
        self.connect()
        self.sync.associate(self.member['agent_token'], self.task['id'], branch='feature')
        self.sync.refresh(self.owner['web_token'])
        self.app.denied = True
        self.webhook('revoke', 'installation', {'installation':{'id':22},'action':'deleted'})
        self.sync.process_pending()
        view = self.sync.snapshot(self.owner['web_token'])
        self.assertEqual(view['deliveries'], [])
        self.assertEqual(view['connection']['status'], 'revoked')

    def test_expired_state_callback_replay_restart_and_revoked_identity(self):
        begun = self.sync.begin_authorization(self.owner['web_token'])
        self.sync.complete_authorization(begun['state'], 'code')
        with self.assertRaises(AccessDenied): self.sync.complete_authorization(begun['state'], 'code')
        reopened = GitHubSync(self.identity, self.repositories, self.app)
        with self.assertRaises(AccessDenied): reopened.finish_authorization(self.owner['web_token'], begun['state'])
        with self.identity.db.connect(write=True) as c:
            c.execute('UPDATE github_oauth_states SET expires_at=?', ((now()-timedelta(seconds=1)).isoformat(),))
        with self.assertRaises(AccessDenied): self.sync.finish_authorization(self.owner['web_token'], begun['state'])
        self.connect()
        with self.identity.db.connect(write=True) as c:
            c.execute('UPDATE credentials SET revoked_at=? WHERE member_id=?', (now().isoformat(),self.owner['member_id']))
        with self.assertRaises(AccessDenied): self.sync.refresh(self.owner['web_token'])

    def test_reserving_revision_prevents_late_response_overwrite(self):
        self.connect()
        self.sync.associate(self.member['agent_token'],self.task['id'],branch='feature')
        original=self.app.repository_state
        def interleaved(*args,**kwargs):
            older=deepcopy(self.app.current)
            self.app.repository_state=original
            self.app.current['branches']['feature']='e'*40
            self.sync.refresh(self.member['agent_token'])
            return older
        self.app.repository_state=interleaved
        self.sync.refresh(self.member['agent_token'])
        self.assertEqual(self.sync.snapshot(self.member['agent_token'])['deliveries'][0]['head_sha'],'e'*40)

    def test_wrong_stable_repository_is_revoked_not_accepted(self):
        self.connect()
        self.app.current['repository_id']=99
        with self.assertRaises(AccessDenied): self.sync.refresh(self.owner['web_token'])
        self.assertEqual(self.sync.snapshot(self.owner['web_token'])['connection']['status'],'revoked')

    def test_branch_checks_and_multiple_immutable_commit_refs_survive_restart(self):
        self.connect()
        checks=[{'head_sha':'a'*40,'name':'ci','status':'completed','conclusion':'success'}]
        self.app.current['commits']={'a'*40:{'checks':checks,'statuses':[]},'c'*64:{'checks':[],'statuses':[]}}
        self.sync.associate(self.member['agent_token'],self.task['id'],branch='feature')
        self.sync.associate(self.member['agent_token'],self.task['id'],commit_sha='a'*40)
        self.sync.associate(self.member['agent_token'],self.task['id'],commit_sha='c'*64)
        self.sync.refresh(self.owner['web_token'])
        reopened=GitHubSync(self.identity,self.repositories,self.app)
        deliveries=reopened.snapshot(self.owner['web_token'])['deliveries']
        self.assertEqual(len(deliveries),3)
        self.assertEqual(next(d for d in deliveries if d['branch']=='feature')['checks'][0]['conclusion'],'success')
        self.assertEqual({d['commit_sha'] for d in deliveries if d.get('commit_sha')},{'a'*40,'c'*64})
        for value in ['abc',True,'A'*40,'a'*39]:
            with self.subTest(value=value),self.assertRaises(ValidationError):
                self.sync.associate(self.member['agent_token'],self.task['id'],commit_sha=value)

    def test_release_reference_is_explicit_task_scoped_and_idempotent(self):
        self.connect()
        first=self.sync.associate(self.member['agent_token'],self.task['id'],release_id=42)
        second=self.sync.associate(self.member['agent_token'],self.task['id'],release_id=42)
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(first['release_id'],42)
        self.assertEqual(first['linked_by'],self.member['member_id'])
        with self.identity.db.connect() as c:
            row=c.execute('SELECT * FROM github_release_refs WHERE room_id=? AND task_id=? AND release_id=?',
                          (self.owner['room_id'],self.task['id'],42)).fetchone()
        self.assertEqual(row['ownership_epoch'],1)
        with self.assertRaises(NotFound):
            self.sync.associate(self.other['agent_token'],self.task['id'],release_id=42)
        with self.assertRaises(ValidationError):
            self.sync.associate(self.member['agent_token'],self.task['id'],release_id=42,pr_number=7)
        for invalid in (True,0,-1,'42'):
            with self.subTest(release_id=invalid),self.assertRaises(ValidationError):
                self.sync.associate(self.member['agent_token'],self.task['id'],release_id=invalid)

    def test_unavailable_refs_do_not_revoke_other_deliveries(self):
        self.connect()
        self.sync.associate(self.member['agent_token'],self.task['id'],branch='feature')
        self.sync.associate(self.member['agent_token'],self.task['id'],pr_number=999)
        self.app.current['unavailable_pr_numbers']=[999]
        self.sync.refresh(self.owner['web_token'])
        view=self.sync.snapshot(self.owner['web_token'])
        self.assertEqual(view['connection']['status'],'active')
        self.assertEqual(next(d for d in view['deliveries'] if d.get('pr_number')==999)['state'],'unavailable')
        self.assertEqual(next(d for d in view['deliveries'] if d['branch']=='feature')['state'],'pushed')

    def test_malformed_signed_webhook_shapes_are_validation_errors(self):
        for payload in [{'installation':{'id':22},'repository':'string'},
                        {'installation':'string','repository':{'id':11}},
                        {'installation':{'id':22},'repository':[]},[],None]:
            body=json.dumps(payload).encode()
            signature='sha256='+hmac.new(self.app.webhook_secret.encode(),body,hashlib.sha256).hexdigest()
            with self.subTest(payload=payload),self.assertRaises(ValidationError):
                self.sync.receive_webhook(str(uuid4()),'push',signature,body)

    def test_rate_limit_backoff_is_durable_and_preserves_active_connection(self):
        self.connect();self.webhook('rate-limited');self.webhook('also-pending')
        calls=[]
        original=self.app.repository_state
        def limited(*args,**kwargs):
            calls.append(1)
            raise GitHubError('GitHub rate limited',retryable=True,retry_after=120,rate_limited=True)
        self.app.repository_state=limited
        started=now()
        self.sync.process_pending()
        self.assertEqual(self.sync.snapshot(self.owner['web_token'])['connection']['status'],'active')
        with self.identity.db.connect() as c:
            inbox=list(c.execute('SELECT * FROM github_inbox'))
        self.assertTrue(all(row['status']=='retry' and timestamp(row['next_attempt_at'])>=started+timedelta(seconds=120) for row in inbox))
        self.assertEqual(len(calls),1)
        self.app.repository_state=original
        reopened=GitHubSync(self.identity,self.repositories,self.app)
        with self.assertRaises(GitHubError): reopened.refresh(self.owner['web_token'])
        self.assertEqual(reopened.process_pending(),0)

    def test_room_ref_cap_keeps_idempotency_and_bounds_output(self):
        self.connect()
        for index in range(100):
            self.sync.associate(self.member['agent_token'],self.task['id'],branch='feature'+str(index))
        self.sync.associate(self.member['agent_token'],self.task['id'],branch='feature0')
        with self.assertRaises(ValidationError): self.sync.associate(self.member['agent_token'],self.task['id'],commit_sha='a'*40)
        with self.assertRaises(ValidationError): self.sync.associate(self.member['agent_token'],self.task['id'],release_id=42)

    def test_discovery_and_check_truncation_are_visible_in_snapshot(self):
        self.connect();self.sync.associate(self.member['agent_token'],self.task['id'],branch='feature')
        self.app.current['discovery']={'limit':50,'truncated':True,'state':'open'}
        self.app.current['commits']={'a'*40:{'checks':[],'statuses':[],'checks_truncated':True,'statuses_truncated':False}}
        self.sync.refresh(self.owner['web_token'])
        snapshot=self.sync.snapshot(self.owner['web_token'])
        self.assertTrue(snapshot['github_discovery']['truncated'])
        self.assertTrue(snapshot['deliveries'][0]['checks_truncated'])

    def test_oversized_output_never_replaces_valid_evidence(self):
        self.connect();self.sync.associate(self.member['agent_token'],self.task['id'],branch='feature')
        self.sync.refresh(self.owner['web_token'])
        checks=[{'head_sha':'a'*40,'name':'n'*200,'status':'completed','conclusion':'success'} for i in range(100)]
        self.app.current['commits']={'a'*40:{'checks':checks,'statuses':[]}}
        for index in range(30):
            self.sync.associate(self.member['agent_token'],self.task['id'],branch='other'+str(index))
            self.app.current['branches']['other'+str(index)]='a'*40
        with self.assertRaises(GitHubError): self.sync.refresh(self.owner['web_token'])
        snapshot=self.sync.snapshot(self.owner['web_token'])
        self.assertEqual(len(snapshot['deliveries']),1)
        self.assertLess(len(json.dumps(snapshot).encode()),500000)

    def test_reconnect_hides_prior_evidence_until_new_verified_sync(self):
        self.connect();self.sync.associate(self.member['agent_token'],self.task['id'],branch='feature')
        self.app.current['branches']['feature']='b'*40
        self.sync.refresh(self.owner['web_token'])
        self.app.denied=True
        with self.assertRaises(AccessDenied): self.sync.refresh(self.owner['web_token'])
        self.app.denied=False;self.app.current['branches']['feature']='c'*40
        self.connect()
        self.assertEqual(self.sync.snapshot(self.owner['web_token'])['deliveries'],[])
        self.sync.refresh(self.owner['web_token'])
        self.assertEqual(self.sync.snapshot(self.owner['web_token'])['deliveries'][0]['head_sha'],'c'*40)

    def test_prior_matching_branch_pr_is_rechecked_after_it_closes(self):
        self.connect();self.sync.associate(self.member['agent_token'],self.task['id'],branch='feature')
        self.app.current['pull_requests'][0].update(head_repository_id=11,head_sha='a'*40,state='open')
        self.sync.refresh(self.owner['web_token'])
        requested=[]
        original=self.app.repository_state
        def closed(*args,**kwargs):
            requested.extend(kwargs['pr_numbers'])
            self.app.current['pull_requests'][0].update(state='closed',merged=True)
            return original(*args,**kwargs)
        self.app.repository_state=closed
        self.sync.refresh(self.owner['web_token'])
        self.assertIn(7,requested)
        self.assertEqual(self.sync.snapshot(self.owner['web_token'])['deliveries'][0]['state'],'merged')

    def test_worker_stop_preserves_partially_processed_event(self):
        self.connect()
        self.repositories.bind_repository(self.other['web_token'],'github.com/acme/demo')
        state=self.sync.begin_authorization(self.other['web_token'])['state']
        self.sync.complete_authorization(state,'code')
        self.sync.finish_authorization(self.other['web_token'],state)
        self.webhook('stop-between-rooms','installation',{'installation':{'id':22}})
        calls=[];original=self.app.repository_state
        def fetched(*args,**kwargs):
            calls.append(1)
            return original(*args,**kwargs)
        self.app.repository_state=fetched
        self.assertEqual(self.sync.process_pending(should_stop=lambda:bool(calls)),0)
        self.assertEqual(len(calls),1)
        with self.identity.db.connect() as c:
            row=c.execute("SELECT * FROM github_inbox WHERE delivery_id='stop-between-rooms'").fetchone()
        self.assertEqual(row['status'],'queued')
        self.assertEqual(row['attempts'],0)
        self.assertEqual(self.sync.process_pending(),1)
        calls.clear()
        self.assertEqual(self.sync.reconcile_all(should_stop=lambda:bool(calls)),1)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.sync.process_pending(should_stop=lambda:True),0)


if __name__ == '__main__': unittest.main()
