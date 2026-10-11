from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
import json
from uuid import uuid4

from crewmesh.identity import IdentityStore
from crewmesh.tasks import TaskStore
from crewmesh.errors import AccessDenied, Conflict, NotFound, ValidationError
from crewmesh.repositories import RepositoryStore


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / str(uuid4())
        self.root.mkdir(parents=True)
        self.identity = IdentityStore(self.root / 'repositories.sqlite3')
        self.owner = self.identity.create_room('Team', 'Owner')
        self.member = self.identity.add_member(self.owner['web_token'], 'Member')
        self.other = self.identity.create_room('Other', 'Other owner')
        self.tasks = TaskStore(self.identity)
        self.store = RepositoryStore(self.identity)
        self.repo = 'github.com/acme/demo'

    def task(self, member=None):
        member = member or self.member
        task = self.tasks.create_task(self.owner['web_token'], str(uuid4()), 'Task', 'src')
        return self.tasks.claim_task(member['agent_token'], task['id'])

    def observation(self, **changes):
        result = dict(request_key=str(uuid4()), workspace_id='a'*64, repository=self.repo,
                      branch='feature', head='b'*40, paths=['src/auth.py'],
                      captured_at=datetime.now(timezone.utc).isoformat())
        result.update(changes)
        return result

    def bind(self):
        return self.store.bind_repository(self.owner['web_token'], 'git@github.com:acme/demo.git')

    def test_binding_permissions_normalization_and_rebind(self):
        self.assertIsNone(self.store.get_binding(self.owner['web_token']))
        for token in [self.owner['agent_token'], self.member['web_token']]:
            with self.assertRaises(AccessDenied): self.store.bind_repository(token, self.repo)
        self.assertEqual(self.bind()['repository'], self.repo)
        self.assertEqual(self.bind()['repository'], self.repo)
        self.store.observe(self.member['agent_token'], self.task()['id'], self.observation())
        with self.assertRaises(Conflict):
            self.store.bind_repository(self.owner['web_token'], 'github.com/acme/other')
        self.assertIsNone(self.store.get_binding(self.other['web_token']))

    def test_observation_requires_binding_task_owner_and_project(self):
        task = self.task()
        with self.assertRaises(Conflict): self.store.observe(self.member['agent_token'], task['id'], self.observation())
        self.bind()
        for token in [self.owner['agent_token'], self.member['web_token']]:
            with self.assertRaises(AccessDenied): self.store.observe(token, task['id'], self.observation())
        with self.assertRaises(NotFound): self.store.observe(self.other['agent_token'], task['id'], self.observation())
        with self.assertRaises(Conflict):
            self.store.observe(self.member['agent_token'], task['id'], self.observation(repository='github.com/acme/other'))

    def test_idempotency_payload_integrity_and_immutable_history(self):
        self.bind(); task = self.task(); payload = self.observation()
        first = self.store.observe(self.member['agent_token'], task['id'], payload)
        self.assertEqual(first, self.store.observe(self.member['agent_token'], task['id'], payload))
        with self.assertRaises(Conflict):
            self.store.observe(self.member['agent_token'], task['id'], dict(payload, paths=['src/other.py']))
        self.store.observe(self.member['agent_token'], task['id'], self.observation(head='c'*40))
        reopened = RepositoryStore(self.identity).snapshot(self.owner['web_token'])
        self.assertEqual(len(reopened['events']), 2)
        self.assertEqual(reopened['workspaces'][0]['head'], 'c'*40)
        self.assertEqual(reopened['workspaces'][0]['source'], 'local_git')

    def test_actual_overlap_freshness_and_out_of_order(self):
        self.bind(); a = self.task(); b = self.task(self.owner)
        self.store.observe(self.member['agent_token'], a['id'], self.observation(paths=['src/auth.py','src/a.py']))
        self.store.observe(self.owner['agent_token'], b['id'], self.observation(workspace_id='d'*64))
        view = self.store.snapshot(self.member['agent_token'])
        self.assertEqual(view['overlaps'][0]['paths'], ['src/auth.py'])
        self.assertEqual(set(view['overlaps'][0]['task_ids']), {a['id'],b['id']})
        old = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        self.store.observe(self.member['agent_token'], a['id'], self.observation(captured_at=old, head='e'*40))
        self.assertEqual(self.store.snapshot(self.owner['web_token'])['workspaces'][0]['head'], 'b'*40)
        with self.store.db.connect(write=True) as c:
            c.execute('UPDATE git_observations SET captured_at=?', (old,))
        stale = self.store.snapshot(self.owner['web_token'])
        self.assertEqual(stale['overlaps'], [])
        self.assertTrue(all(w['stale'] for w in stale['workspaces']))
        self.assertEqual(self.store.snapshot(self.other['web_token'])['workspaces'], [])

    def test_bounded_untrusted_input_never_persists(self):
        self.bind(); task = self.task()
        for changes in [dict(paths=['../secret']),dict(paths=['C:/secret']),dict(paths=['/etc/passwd']),
                        dict(paths=['.git/config']),dict(paths=['src\\secret']),dict(paths=['a\x00b']),
                        dict(paths=['x']*1001),dict(head='fake'),dict(captured_at='yesterday'),
                        dict(captured_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()),
                        dict(extra='unsupported'),dict(workspace_id=''),dict(branch='a\n'),dict(paths='src')]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.store.observe(self.member['agent_token'], task['id'], self.observation(**changes))
        self.assertEqual(self.store.snapshot(self.owner['web_token'])['events'], [])

    def test_clean_unborn_and_detached_workspaces_are_valid(self):
        self.bind(); task = self.task()
        self.store.observe(self.member['agent_token'], task['id'], self.observation(head='', paths=[]))
        self.store.observe(self.member['agent_token'], task['id'], self.observation(branch='', paths=[]))
        self.assertEqual(self.store.snapshot(self.owner['web_token'])['workspaces'][0]['branch'], '')

    def test_large_legal_history_is_compact_and_bounded(self):
        self.bind();task=self.task();paths=['src/'+('x'*55)+str(i) for i in range(400)]
        for _ in range(100):
            self.store.observe(self.member['agent_token'],task['id'],self.observation(paths=paths))
        snapshot=self.store.snapshot(self.owner['web_token'])
        self.assertLess(len(json.dumps(snapshot).encode()),200_000)
        self.assertEqual(snapshot['workspaces'][0]['path_count'],400)
        self.assertTrue(snapshot['workspaces'][0]['paths_truncated'])
        self.assertNotIn('paths',snapshot['events'][0])
