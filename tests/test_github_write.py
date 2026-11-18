"""Offline write-path tests. The fake provider and mock transport are not live GitHub acceptance evidence."""
import json
import unittest
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from coopagents.api import create_app
from coopagents.errors import AccessDenied, Conflict, ValidationError
from coopagents.github_app import GitHubApp, GitHubError
from coopagents.github_sync import GitHubSync
from coopagents.identity import IdentityStore
from coopagents.repositories import RepositoryStore
from coopagents.tasks import TaskStore
from test_github_sync import FakeProvider


def write_token_response(**overrides):
    response = {'token': 'write-token', 'repositories': [{'id': 11}],
                'permissions': {'contents': 'write', 'pull_requests': 'write',
                                'checks': 'read', 'statuses': 'read', 'metadata': 'read'}}
    response.update(overrides)
    return response


def read_token_response(**overrides):
    response = {'token': 'read-token', 'repositories': [{'id': 11}],
                'permissions': {'contents': 'read', 'pull_requests': 'read',
                                'checks': 'read', 'statuses': 'read', 'metadata': 'read'}}
    response.update(overrides)
    return response


def protection_token_response(**overrides):
    response = {'token': 'protection-token', 'repositories': [{'id': 11}],
                'permissions': {'contents': 'read', 'pull_requests': 'read',
                                'checks': 'read', 'statuses': 'read', 'administration': 'read',
                                'metadata': 'read'}}
    response.update(overrides)
    return response


class GitHubAppWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pem = cls.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()).decode()

    def app(self, handler):
        app = GitHubApp('123', 'Iv1.app-client', 'secret', self.pem, 'webhook-secret',
                        'https://crew.example/api/git/github/callback')
        app._client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
        return app

    def test_write_token_requests_exact_write_set(self):
        seen = []

        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                seen.append(json.loads(request.content)['permissions'])
                return httpx.Response(201, json=write_token_response())
            raise AssertionError(request.url.path)
        app = self.app(handler)
        self.assertEqual(app.installation_token(22, 11, write=True), 'write-token')
        self.assertEqual(seen, [{'contents': 'write', 'pull_requests': 'write',
                                 'checks': 'read', 'statuses': 'read'}])

    def test_write_token_rejects_broader_or_narrower_grants(self):
        variants = [
            {'contents': 'admin', 'pull_requests': 'write', 'checks': 'read', 'statuses': 'read'},
            {'contents': 'write', 'pull_requests': 'write', 'checks': 'read', 'statuses': 'read',
             'issues': 'read'},
            {'contents': 'read', 'pull_requests': 'write', 'checks': 'read', 'statuses': 'read'},
            {'contents': 'write', 'pull_requests': 'write', 'checks': 'read'},
            {'contents': 'write', 'pull_requests': 'write', 'checks': 'read', 'statuses': 'read',
             'metadata': 'write'},
        ]
        for permissions in variants:
            with self.subTest(permissions=permissions):
                app = self.app(lambda r: httpx.Response(201, json=write_token_response(permissions=permissions)))
                with self.assertRaises(GitHubError):
                    app.installation_token(22, 11, write=True)

    def test_read_token_still_rejects_write_levels(self):
        app = self.app(lambda r: httpx.Response(201, json=read_token_response(
            permissions={'contents': 'write', 'pull_requests': 'read', 'checks': 'read', 'statuses': 'read'})))
        with self.assertRaises(GitHubError):
            app.installation_token(22, 11)
        app = self.app(lambda r: httpx.Response(201, json=read_token_response()))
        self.assertEqual(app.installation_token(22, 11), 'read-token')

    def test_default_token_request_is_unchanged_without_administration(self):
        seen = []

        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                seen.append(json.loads(request.content)['permissions'])
                return httpx.Response(201, json=read_token_response())
            raise AssertionError(request.url.path)
        app = self.app(handler)
        self.assertEqual(app.installation_token(22, 11), 'read-token')
        self.assertEqual(seen, [{'contents': 'read', 'pull_requests': 'read',
                                 'checks': 'read', 'statuses': 'read'}])

    def test_administration_token_requests_exact_read_set_with_administration(self):
        seen = []

        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                seen.append(json.loads(request.content)['permissions'])
                return httpx.Response(201, json=protection_token_response())
            raise AssertionError(request.url.path)
        app = self.app(handler)
        self.assertEqual(app.installation_token(22, 11, administration=True), 'protection-token')
        self.assertEqual(seen, [{'contents': 'read', 'pull_requests': 'read',
                                 'checks': 'read', 'statuses': 'read', 'administration': 'read'}])

    def test_administration_token_rejects_grants_beyond_request(self):
        base = {'contents': 'read', 'pull_requests': 'read', 'checks': 'read', 'statuses': 'read'}
        variants = [
            dict(base, administration='read', issues='read'),
            dict(base, administration='write'),
            dict(base),
            dict(base, administration='read', contents='write'),
            dict(base, administration='read', metadata='write'),
        ]
        for permissions in variants:
            with self.subTest(permissions=permissions):
                app = self.app(lambda r: httpx.Response(
                    201, json=protection_token_response(permissions=permissions)))
                with self.assertRaises(GitHubError):
                    app.installation_token(22, 11, administration=True)

    def test_default_and_write_tokens_reject_administration_grants(self):
        granted = {'contents': 'read', 'pull_requests': 'read', 'checks': 'read', 'statuses': 'read',
                   'administration': 'read'}
        app = self.app(lambda r: httpx.Response(201, json=read_token_response(permissions=granted)))
        with self.assertRaises(GitHubError):
            app.installation_token(22, 11)
        write_granted = dict(granted, contents='write', pull_requests='write')
        app = self.app(lambda r: httpx.Response(201, json=write_token_response(permissions=write_granted)))
        with self.assertRaises(GitHubError):
            app.installation_token(22, 11, write=True)

    def test_write_and_administration_scopes_cannot_combine(self):
        app = self.app(lambda r: httpx.Response(201, json=protection_token_response()))
        with self.assertRaises(ValidationError):
            app.installation_token(22, 11, write=True, administration=True)
        with self.assertRaises(ValidationError):
            app.installation_token(22, 11, administration='read')

    def test_create_pull_request_posts_draft_and_builds_safe_url(self):
        seen = []

        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                return httpx.Response(201, json=write_token_response())
            if request.url.path == '/repos/acme/demo/pulls' and request.method == 'POST':
                seen.append((request.headers['authorization'], json.loads(request.content)))
                return httpx.Response(201, json={'number': 42, 'state': 'open', 'draft': True,
                                                 'html_url': 'https://evil.example/steal',
                                                 'base': {'repo': {'id': 11}},
                                                 'head': {'sha': 'c' * 40, 'ref': 'coopagents/task-1-1-x'}})
            raise AssertionError(request.url.path)
        app = self.app(handler)
        pr = app.create_pull_request(22, 11, 'acme/demo', 'coopagents/task-1-1-x', 'main',
                                     'Task 1: Build it', 'Delivery body')
        self.assertEqual(pr['number'], 42)
        self.assertEqual(pr['url'], 'https://github.com/acme/demo/pull/42')
        self.assertTrue(pr['draft'])
        self.assertNotIn('evil.example', str(pr))
        authorization, body = seen[0]
        self.assertEqual(authorization, 'Bearer write-token')
        self.assertEqual(body, {'title': 'Task 1: Build it', 'head': 'coopagents/task-1-1-x',
                                'base': 'main', 'body': 'Delivery body', 'draft': True})

    def test_create_pull_request_validates_inputs_and_response(self):
        app = self.app(lambda r: httpx.Response(201, json=write_token_response()))
        with self.assertRaises(ValidationError):
            app.create_pull_request(22, 11, 'acme/demo', 'main', 'main', 'Title', '')
        with self.assertRaises(ValidationError):
            app.create_pull_request(22, 11, 'acme/demo', 'feature', 'main', '', '')
        with self.assertRaises(ValidationError):
            app.create_pull_request(22, 11, 'acme/demo', 'feature', 'main', 'Title', 'x' * 10001)
        with self.assertRaises(ValidationError):
            app.create_pull_request(22, 11, 'not-a-repo', 'feature', 'main', 'Title', '')

        def wrong_repo(request):
            if request.url.path.endswith('/access_tokens'):
                return httpx.Response(201, json=write_token_response())
            return httpx.Response(201, json={'number': 42, 'state': 'open',
                                             'base': {'repo': {'id': 99}},
                                             'head': {'sha': 'c' * 40, 'ref': 'feature'}})
        with self.assertRaises(GitHubError):
            self.app(wrong_repo).create_pull_request(22, 11, 'acme/demo', 'feature', 'main', 'Title', '')

    def test_find_open_pr_uses_read_token_and_matches_same_repo_branch(self):
        requested = []

        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                requested.append(json.loads(request.content)['permissions'])
                return httpx.Response(201, json=read_token_response())
            if request.url.path == '/repos/acme/demo/pulls':
                self.assertEqual(request.url.params['state'], 'open')
                self.assertEqual(request.url.params['head'], 'acme:coopagents/task-1-1-x')
                return httpx.Response(200, json=[
                    {'number': 1, 'state': 'open', 'base': {'repo': {'id': 11}},
                     'head': {'sha': 'a' * 40, 'ref': 'coopagents/task-1-1-x', 'repo': {'id': 99}}},
                    {'number': 2, 'state': 'open', 'base': {'repo': {'id': 11}},
                     'head': {'sha': 'b' * 40, 'ref': 'other', 'repo': {'id': 11}}},
                    {'number': 3, 'state': 'open', 'base': {'repo': {'id': 11}},
                     'head': {'sha': 'c' * 40, 'ref': 'coopagents/task-1-1-x', 'repo': {'id': 11}}}])
            raise AssertionError(request.url.path)
        app = self.app(handler)
        found = app.find_open_pr(22, 11, 'acme/demo', 'coopagents/task-1-1-x')
        self.assertEqual(found['number'], 3)
        self.assertEqual(found['head_sha'], 'c' * 40)
        self.assertEqual(requested, [{'contents': 'read', 'pull_requests': 'read',
                                      'checks': 'read', 'statuses': 'read'}])

    def test_find_open_pr_returns_none_when_empty(self):
        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                return httpx.Response(201, json=read_token_response())
            return httpx.Response(200, json=[])
        app = self.app(handler)
        self.assertIsNone(app.find_open_pr(22, 11, 'acme/demo', 'feature'))


class WriteFakeProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.lookups = []
        self.creates = []
        self.open_prs = {}
        self.fail_create = False
        self.fail_lookup = False

    def find_open_pr(self, installation_id, repository_id, full_name, head):
        self.lookups.append(head)
        if self.fail_lookup:
            raise GitHubError('GitHub unavailable', retryable=True)
        found = self.open_prs.get(head)
        return dict(found) if found else None

    def create_pull_request(self, installation_id, repository_id, full_name, head, base, title, body):
        self.creates.append({'head': head, 'base': base, 'title': title, 'body': body})
        if self.fail_create:
            raise GitHubError('GitHub unavailable', retryable=True)
        pr = {'number': 42, 'state': 'open', 'head_sha': 'c' * 40, 'head_branch': head,
              'url': 'https://github.com/%s/pull/42' % full_name}
        self.open_prs[head] = pr
        return dict(pr)


class GitHubSyncWriteTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / str(uuid4())
        self.root.mkdir(parents=True)
        self.identity = IdentityStore(self.root / 'github-write.sqlite3')
        self.owner = self.identity.create_room('Team', 'Owner')
        self.member = self.identity.add_member(self.owner['web_token'], 'Member')
        self.repositories = RepositoryStore(self.identity)
        self.repositories.bind_repository(self.owner['web_token'], 'github.com/acme/demo')
        self.repositories.set_git_write_enabled(self.owner['web_token'], True)
        self.tasks = TaskStore(self.identity)
        self.task = self.tasks.create_task(self.owner['web_token'], 'task', 'Build Login', 'src')
        self.tasks.claim_task(self.member['agent_token'], self.task['id'], session_key='s1')
        self.app = WriteFakeProvider()
        self.sync = GitHubSync(self.identity, self.repositories, self.app)
        begun = self.sync.begin_authorization(self.owner['web_token'])
        self.sync.complete_authorization(begun['state'], 'code')
        self.sync.finish_authorization(self.owner['web_token'], begun['state'])
        self.branch = 'coopagents/task-%d-1-build-login' % self.task['id']
        self.repositories.record_branch(self.member['agent_token'], self.task['id'], self.branch,
                                        'a' * 40, 'branch-key', session_key='s1', ownership_epoch=1)
        from coopagents.repositories import now
        self.repositories.observe(self.member['agent_token'], self.task['id'], {
            'request_key': 'k-' + str(uuid4()), 'workspace_id': 'workspace-deliver-1',
            'repository': 'github.com/acme/demo', 'branch': self.branch, 'head': 'c' * 40,
            'paths': ['src/login.py'], 'captured_at': now().isoformat()},
            session_key='s1', ownership_epoch=1)

    def deliver(self, **overrides):
        args = {'token': self.member['agent_token'], 'task_id': self.task['id'], 'branch': self.branch,
                'head_sha': 'c' * 40, 'base_branch': 'main', 'title': 'Task 1: Build it',
                'body': 'Delivery body', 'request_key': 'd1', 'session_key': 's1', 'ownership_epoch': 1}
        args.update(overrides)
        return self.sync.open_pr(**args)

    def delivery_row(self, request_key='d1'):
        with self.identity.db.connect() as c:
            row = c.execute('SELECT * FROM git_deliveries WHERE task_id=? AND request_key=?',
                            (self.task['id'], request_key)).fetchone()
            return dict(row) if row else None

    def test_open_pr_creates_draft_pr_and_records_delivery(self):
        result = self.deliver()
        self.assertEqual(result['state'], 'pr_opened')
        self.assertEqual(result['pr_number'], 42)
        self.assertTrue(result['created'])
        self.assertEqual(result['pr_url'], 'https://github.com/acme/demo/pull/42')
        self.assertEqual(self.app.lookups, [self.branch])
        self.assertEqual(len(self.app.creates), 1)
        self.assertEqual(self.app.creates[0]['base'], 'main')
        row = self.delivery_row()
        self.assertEqual(row['head_sha'], 'c' * 40)
        self.assertEqual(row['delivered_by'], self.member['member_id'])
        with self.identity.db.connect() as c:
            branch = c.execute('SELECT pushed_sha,pushed_at FROM git_branches WHERE task_id=?',
                               (self.task['id'],)).fetchone()
            self.assertEqual(branch['pushed_sha'], 'c' * 40)
            self.assertTrue(branch['pushed_at'])
            refs = c.execute("SELECT branch,pr_number FROM github_refs WHERE task_id=?",
                             (self.task['id'],)).fetchall()
            self.assertEqual({(r['branch'], r['pr_number']) for r in refs},
                             {(self.branch, 0), ('', 42)})
            verified = c.execute('SELECT write_scope_verified FROM github_connections').fetchone()
            self.assertEqual(verified['write_scope_verified'], 1)

    def test_lookup_before_create_reuses_open_pr(self):
        self.app.open_prs[self.branch] = {'number': 9, 'state': 'open', 'head_sha': 'c' * 40,
                                          'head_branch': self.branch,
                                          'url': 'https://github.com/acme/demo/pull/9'}
        result = self.deliver()
        self.assertEqual(result['pr_number'], 9)
        self.assertFalse(result['created'])
        self.assertEqual(self.app.creates, [])
        with self.identity.db.connect() as c:
            verified = c.execute('SELECT write_scope_verified FROM github_connections').fetchone()
            self.assertEqual(verified['write_scope_verified'], 0)

    def test_same_request_key_returns_recorded_pr_without_api_call(self):
        first = self.deliver()
        second = self.deliver()
        self.assertEqual(second['pr_number'], first['pr_number'])
        self.assertFalse(second['created'])
        self.assertEqual(len(self.app.lookups), 1)
        self.assertEqual(len(self.app.creates), 1)

    def test_create_failure_records_pushed_and_retry_succeeds(self):
        self.app.fail_create = True
        with self.assertRaises(GitHubError):
            self.deliver()
        row = self.delivery_row()
        self.assertEqual(row['state'], 'pushed')
        self.assertIsNone(row['pr_number'])
        with self.identity.db.connect() as c:
            refs = c.execute("SELECT branch,pr_number FROM github_refs WHERE task_id=?",
                             (self.task['id'],)).fetchall()
            self.assertEqual([(r['branch'], r['pr_number']) for r in refs], [(self.branch, 0)])
        self.app.fail_create = False
        result = self.deliver()
        self.assertEqual(result['state'], 'pr_opened')
        self.assertEqual(result['pr_number'], 42)
        self.assertEqual(self.delivery_row()['state'], 'pr_opened')

    def test_create_race_resolves_through_relookup(self):
        def racing_create(installation_id, repository_id, full_name, head, base, title, body):
            self.app.open_prs[head] = {'number': 33, 'state': 'open', 'head_sha': 'c' * 40,
                                       'head_branch': head, 'url': 'https://github.com/acme/demo/pull/33'}
            raise GitHubError('A pull request already exists')
        self.app.create_pull_request = racing_create
        result = self.deliver()
        self.assertEqual(result['pr_number'], 33)
        self.assertFalse(result['created'])
        self.assertEqual(len(self.app.lookups), 2)
        self.assertEqual(self.delivery_row()['state'], 'pr_opened')

    def test_flag_off_and_unrecorded_branch_block_before_provider_calls(self):
        self.repositories.set_git_write_enabled(self.owner['web_token'], False)
        with self.assertRaises(Conflict):
            self.deliver()
        self.repositories.set_git_write_enabled(self.owner['web_token'], True)
        with self.assertRaises(Conflict):
            self.deliver(branch='feature/other')
        with self.assertRaises(Conflict):
            self.deliver(ownership_epoch=99)
        self.assertEqual(self.app.lookups, [])
        self.assertEqual(self.app.creates, [])

    def test_missing_connection_blocks(self):
        with self.identity.db.connect(write=True) as c:
            c.execute('DELETE FROM github_connections')
        with self.assertRaises(Conflict):
            self.deliver()
        self.assertEqual(self.app.lookups, [])

    def test_preview_writes_nothing_and_describes_call(self):
        result = self.deliver(preview=True)
        self.assertTrue(result['preview'])
        self.assertEqual(result['api_call'], {'method': 'POST', 'path': '/repos/acme/demo/pulls',
                                              'head': self.branch, 'base': 'main', 'draft': True})
        self.assertEqual(result['connection'], 'active')
        self.assertIsNone(result['existing_state'])
        self.assertEqual(self.app.lookups, [])
        self.assertEqual(self.app.creates, [])
        self.assertIsNone(self.delivery_row())
        with self.identity.db.connect() as c:
            branch = c.execute('SELECT pushed_sha FROM git_branches WHERE task_id=?',
                               (self.task['id'],)).fetchone()
            self.assertFalse(branch['pushed_sha'])

    def test_preview_without_connection_reports_missing(self):
        with self.identity.db.connect(write=True) as c:
            c.execute('DELETE FROM github_connections')
        result = self.deliver(preview=True)
        self.assertEqual(result['connection'], 'missing')

    def test_validation_rejects_bad_inputs(self):
        for overrides in ({'head_sha': 'xyz'}, {'base_branch': self.branch}, {'title': ''},
                          {'title': ' x '}, {'body': 'x' * 10001}, {'request_key': ''},
                          {'preview': 'yes'}):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.deliver(**overrides)
        self.assertEqual(self.app.lookups, [])


class GitHubWriteHttpTests(unittest.TestCase):
    def test_deliver_route_opens_pr_through_http(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        app = create_app(root / 'http.sqlite3', base_url='http://127.0.0.1', github_app=WriteFakeProvider())
        service = app.state.service
        owner = service.identity.create_room('Team', 'Owner')
        member = service.identity.add_member(owner['web_token'], 'Member')
        service.repositories.bind_repository(owner['web_token'], 'github.com/acme/demo')
        service.repositories.set_git_write_enabled(owner['web_token'], True)
        task = service.tasks.create_task(owner['web_token'], 'task', 'Build Login', 'src')
        service.tasks.claim_task(member['agent_token'], task['id'], session_key='s1')
        branch = 'coopagents/task-%d-1-build-login' % task['id']
        service.repositories.record_branch(member['agent_token'], task['id'], branch,
                                           'a' * 40, 'branch-key', session_key='s1', ownership_epoch=1)
        from coopagents.repositories import now
        service.repositories.observe(member['agent_token'], task['id'], {
            'request_key': 'k-' + str(uuid4()), 'workspace_id': 'workspace-http-deliver',
            'repository': 'github.com/acme/demo', 'branch': branch, 'head': 'c' * 40,
            'paths': ['src/login.py'], 'captured_at': now().isoformat()},
            session_key='s1', ownership_epoch=1)
        web = {'Authorization': 'Bearer ' + owner['web_token']}
        agent = {'Authorization': 'Bearer ' + member['agent_token']}
        with TestClient(app, base_url='http://127.0.0.1') as client:
            begun = client.post('/api/git/github/authorize', headers=web, json={})
            self.assertEqual(begun.status_code, 200, begun.text)
            state = begun.json()['state']
            self.assertEqual(client.get('/api/git/github/callback',
                                        params={'state': state, 'code': 'code'}).status_code, 200)
            self.assertEqual(client.post('/api/git/github/finish', headers=web,
                                         json={'state': state}).status_code, 200)
            payload = {'task_id': task['id'], 'branch': branch, 'head_sha': 'c' * 40,
                       'base_branch': 'main', 'title': 'Task 1: Build it', 'body': 'Delivery body',
                       'request_key': 'd1', 'session_key': 's1', 'ownership_epoch': 1}
            missing_key = client.post('/api/git/deliveries', headers=agent,
                                      json={k: v for k, v in payload.items() if k != 'request_key'})
            self.assertEqual(missing_key.status_code, 400, missing_key.text)
            delivered = client.post('/api/git/deliveries', headers=agent, json=payload)
            self.assertEqual(delivered.status_code, 200, delivered.text)
            self.assertEqual(delivered.json()['pr_number'], 42)
            self.assertEqual(delivered.json()['state'], 'pr_opened')
            service.repositories.set_git_write_enabled(owner['web_token'], False)
            blocked = client.post('/api/git/deliveries', headers=agent,
                                  json=dict(payload, request_key='d2'))
            self.assertEqual(blocked.status_code, 409, blocked.text)


if __name__ == '__main__':
    unittest.main()
