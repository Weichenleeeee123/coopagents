"""Merge policy: human-only execution, live preconditions, manager overrides (W4).

All GitHub interaction is offline: a mock transport for the App adapter and a
fake provider for the sync layer. Nothing here is live App acceptance evidence.
"""
import json
import unittest
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from coopagents.api import create_app
from coopagents.coordination import CoordinationService
from coopagents.errors import AccessDenied, Conflict, NotFound, ValidationError
from coopagents.github_app import GitHubApp, GitHubError
from coopagents.github_sync import GitHubSync
from coopagents.identity import IdentityStore
from coopagents.repositories import RepositoryStore, now
from coopagents.tasks import TaskStore
from test_github_write import WriteFakeProvider, read_token_response, write_token_response


def fresh():
    return now().isoformat()


class MergeFakeProvider(WriteFakeProvider):
    """Offline provider with a configurable PR, protection, reviews, and merge."""

    def __init__(self):
        super().__init__()
        self.pr = {'number': 42, 'state': 'open', 'merged': False, 'head_sha': 'c' * 40,
                   'head_repository_id': 11, 'head_branch': 'coopagents/task-1-1-build-login',
                   'base_branch': 'main', 'author': 'author-login', 'mergeable': True, 'merge_commit_sha': None,
                   'checks': [], 'statuses': [], 'checks_truncated': False,
                   'statuses_truncated': False, 'checks_verified': True}
        self.protection = None
        self.review_payload = {'reviews': [], 'truncated': False}
        self.review_calls = []
        self.merges = []
        self.fail_merge = False
        self.flip_on_fail = False

    def repository_state(self, installation_id, repository_id, full_name, branches=(),
                         pr_numbers=(), commit_shas=(), release_ids=()):
        if self.fail:
            raise GitHubError('GitHub unavailable', retryable=True)
        self.verify_repository(installation_id, repository_id, full_name)
        return {'repository_id': 11, 'full_name': 'acme/demo', 'branches': {},
                'pull_requests': [deepcopy(self.pr)], 'commits': {},
                'releases': [], 'unavailable_release_ids': [],
                'release_discovery': {'limit': 20, 'truncated': False}}

    def read_branch_protection(self, installation_id, repository_id, full_name, branch):
        return deepcopy(self.protection)

    def read_pull_reviews(self, installation_id, repository_id, full_name, number):
        self.review_calls.append(number)
        return deepcopy(self.review_payload)

    def merge_pull_request(self, installation_id, repository_id, full_name, number, head_sha):
        self.merges.append({'number': number, 'head_sha': head_sha})
        if self.fail_merge:
            if self.flip_on_fail:
                self.pr['merged'] = True
                self.pr['state'] = 'closed'
                self.pr['merge_commit_sha'] = 'd' * 40
            raise GitHubError('GitHub refused the merge')
        if head_sha != self.pr['head_sha']:
            raise GitHubError('GitHub refused the merge')
        self.pr['merged'] = True
        self.pr['state'] = 'closed'
        self.pr['merge_commit_sha'] = 'd' * 40
        return {'merged': True, 'sha': 'd' * 40, 'number': number}


class GitHubAppMergeTests(unittest.TestCase):
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

    def test_put_allowlisted_to_merge_path_only(self):
        seen = []

        def handler(request):
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={'merged': True, 'sha': 'd' * 40})
        app = self.app(handler)
        app.request('PUT', '/repos/acme/demo/pulls/42/merge', 'token')
        self.assertEqual(seen, [('PUT', '/repos/acme/demo/pulls/42/merge')])
        for bad in ('/repos/acme/demo/pulls/42', '/repos/acme/demo/issues',
                    '/repos/acme/demo/pulls/42/merge/extra', '/repos/acme/demo/pulls/x/merge',
                    '/repos/acme/demo/pulls/42/merge?x=1'):
            with self.subTest(path=bad):
                with self.assertRaises(ValidationError):
                    app.request('PUT', bad, 'token')

    def test_read_branch_protection_normalizes_sections(self):
        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                return httpx.Response(201, json=read_token_response())
            payload = {'required_status_checks': {'contexts': ['ci'], 'strict': True},
                       'required_pull_request_reviews': {'required_approving_review_count': 2},
                       'restrictions': {'users': [{'login': 'octo'}], 'teams': [], 'apps': []},
                       'enforce_admins': {'enabled': True}}
            return httpx.Response(200, json=payload)
        result = self.app(handler).read_branch_protection(22, 11, 'acme/demo', 'main')
        self.assertEqual(result['required_status_checks'], {'contexts': ['ci']})
        self.assertEqual(result['required_pull_request_reviews'],
                         {'required_approving_review_count': 2})
        self.assertEqual(result['restrictions'], {'users': ['octo'], 'teams': [], 'apps': []})

    def test_read_branch_protection_missing_branch_is_unprotected(self):
        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                return httpx.Response(201, json=read_token_response())
            return httpx.Response(404, json={'message': 'Not Found'})
        self.assertIsNone(self.app(handler).read_branch_protection(22, 11, 'acme/demo', 'main'))

    def test_read_pull_reviews_preserves_order_and_flags_truncation(self):
        reviews = [{'user': {'login': 'a'}, 'state': 'APPROVED'},
                   {'user': {'login': 'b'}, 'state': 'CHANGES_REQUESTED'}]

        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                return httpx.Response(201, json=read_token_response())
            return httpx.Response(200, json=reviews)
        result = self.app(handler).read_pull_reviews(22, 11, 'acme/demo', 42)
        self.assertEqual(result, {'reviews': [{'reviewer': 'a', 'state': 'APPROVED'},
                                              {'reviewer': 'b', 'state': 'CHANGES_REQUESTED'}],
                                  'truncated': False})

        def full_handler(request):
            if request.url.path.endswith('/access_tokens'):
                return httpx.Response(201, json=read_token_response())
            return httpx.Response(200, json=[{'user': {'login': 'u%d' % i}, 'state': 'COMMENTED'}
                                             for i in range(100)])
        result = self.app(full_handler).read_pull_reviews(22, 11, 'acme/demo', 42)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['reviews']), 100)

    def test_merge_pull_request_sends_sha_and_merge_method_with_write_token(self):
        seen = []

        def handler(request):
            if request.url.path.endswith('/access_tokens'):
                seen.append(('token', json.loads(request.content)['permissions']))
                return httpx.Response(201, json=write_token_response())
            seen.append(('merge', request.method, json.loads(request.content)))
            return httpx.Response(200, json={'merged': True, 'sha': 'd' * 40})
        result = self.app(handler).merge_pull_request(22, 11, 'acme/demo', 42, 'c' * 40)
        self.assertEqual(result, {'merged': True, 'sha': 'd' * 40, 'number': 42})
        self.assertEqual(seen[0][1], {'contents': 'write', 'pull_requests': 'write',
                                      'checks': 'read', 'statuses': 'read'})
        self.assertEqual(seen[1], ('merge', 'PUT', {'sha': 'c' * 40, 'merge_method': 'merge'}))

    def test_merge_pull_request_refusal_and_bad_response(self):
        def refused(request):
            if request.url.path.endswith('/access_tokens'):
                return httpx.Response(201, json=write_token_response())
            return httpx.Response(409, json={'message': 'Merge conflict'})
        with self.assertRaises(GitHubError) as caught:
            self.app(refused).merge_pull_request(22, 11, 'acme/demo', 42, 'c' * 40)
        self.assertIn('refused', str(caught.exception))
        self.assertFalse(caught.exception.retryable)

        def unmerged(request):
            if request.url.path.endswith('/access_tokens'):
                return httpx.Response(201, json=write_token_response())
            return httpx.Response(200, json={'merged': False, 'sha': 'd' * 40})
        with self.assertRaises(GitHubError):
            self.app(unmerged).merge_pull_request(22, 11, 'acme/demo', 42, 'c' * 40)

    def test_repository_state_detail_carries_merge_fields(self):
        sha = 'c' * 40

        def handler(request):
            path = request.url.path
            if path.endswith('/access_tokens'):
                return httpx.Response(201, json=read_token_response())
            if path == '/app/installations/22':
                return httpx.Response(200, json={'id': 22, 'app_id': 123})
            if path == '/repositories/11':
                return httpx.Response(200, json={'id': 11, 'full_name': 'acme/demo'})
            if path == '/repos/acme/demo/pulls' and 'state=open' in str(request.url):
                return httpx.Response(200, json=[])
            if path == '/repos/acme/demo/pulls/42':
                return httpx.Response(200, json={
                    'number': 42, 'state': 'open', 'merged': False, 'mergeable': True,
                    'merge_commit_sha': None, 'user': {'login': 'author-login'},
                    'head': {'sha': sha, 'ref': 'feature', 'repo': {'id': 11}},
                    'base': {'ref': 'main', 'repo': {'id': 11}}})
            if path.endswith('/check-runs'):
                return httpx.Response(200, json={'check_runs': [], 'total_count': 0})
            if path.endswith('/statuses'):
                return httpx.Response(200, json=[])
            if path == '/repos/acme/demo/releases':
                return httpx.Response(200, json=[])
            raise AssertionError(path)
        state = self.app(handler).repository_state(22, 11, 'acme/demo', pr_numbers=(42,))
        pr = state['pull_requests'][0]
        self.assertEqual(pr['base_branch'], 'main')
        self.assertEqual(pr['author'], 'author-login')
        self.assertTrue(pr['mergeable'])
        self.assertIsNone(pr['merge_commit_sha'])


class MergeFixture:
    def build(self, root):
        self.identity = IdentityStore(root)
        self.owner = self.identity.create_room('Team', 'Owner')
        self.member = self.identity.add_member(self.owner['web_token'], 'Member')
        self.repositories = RepositoryStore(self.identity)
        self.repositories.bind_repository(self.owner['web_token'], 'github.com/acme/demo')
        self.repositories.set_git_write_enabled(self.owner['web_token'], True)
        self.tasks = TaskStore(self.identity)
        self.task = self.tasks.create_task(self.owner['web_token'], 'task', 'Build Login', 'src')
        self.tasks.claim_task(self.member['agent_token'], self.task['id'], session_key='s1')
        self.app = MergeFakeProvider()
        self.sync = GitHubSync(self.identity, self.repositories, self.app)
        begun = self.sync.begin_authorization(self.owner['web_token'])
        self.sync.complete_authorization(begun['state'], 'code')
        self.sync.finish_authorization(self.owner['web_token'], begun['state'])
        self.branch = 'coopagents/task-%d-1-build-login' % self.task['id']
        self.app.pr['head_branch'] = self.branch
        self.repositories.record_branch(self.member['agent_token'], self.task['id'], self.branch,
                                        'a' * 40, 'branch-key', session_key='s1', ownership_epoch=1)
        self.repositories.observe(self.member['agent_token'], self.task['id'], {
            'request_key': 'k-' + str(uuid4()), 'workspace_id': 'workspace-merge-1',
            'repository': 'github.com/acme/demo', 'branch': self.branch, 'head': 'c' * 40,
            'paths': ['src/login.py'], 'captured_at': fresh()},
            session_key='s1', ownership_epoch=1)
        self.sync.open_pr(self.member['agent_token'], self.task['id'], self.branch, 'c' * 40,
                          'main', 'Task 1: Build it', 'Delivery body', 'd1', 's1', 1)

    def request_merge(self, **overrides):
        args = {'token': self.member['agent_token'], 'task_id': self.task['id'], 'pr_number': 42,
                'request_key': 'm1', 'session_key': 's1', 'ownership_epoch': 1}
        args.update(overrides)
        return self.sync.request_merge(**args)

    def merge_request_row(self):
        with self.identity.db.connect() as c:
            row = c.execute('SELECT * FROM git_merge_requests WHERE task_id=?', (self.task['id'],)).fetchone()
            return dict(row) if row else None

    def delivery_row(self):
        with self.identity.db.connect() as c:
            row = c.execute('SELECT * FROM git_deliveries WHERE task_id=? AND request_key=?',
                            (self.task['id'], 'd1')).fetchone()
            return dict(row) if row else None


class RequestMergeTests(MergeFixture, unittest.TestCase):
    def setUp(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        self.build(root / 'merge.sqlite3')

    def test_request_creates_pending_row_and_is_idempotent(self):
        first = self.request_merge()
        self.assertEqual(first['state'], 'pending')
        self.assertEqual(first['pr_number'], 42)
        self.assertEqual(first['head_sha'], 'c' * 40)
        self.assertEqual(first['requested_by'], self.member['member_id'])
        again = self.request_merge(request_key='m2')
        self.assertEqual(again['id'], first['id'])
        self.assertEqual(again['state'], 'pending')

    def test_preview_describes_without_writing(self):
        result = self.request_merge(preview=True)
        self.assertTrue(result['preview'])
        self.assertEqual(result['pr_number'], 42)
        self.assertIsNone(self.merge_request_row())

    def test_request_rejects_wrong_pr_flag_off_and_missing_delivery(self):
        with self.assertRaises(Conflict):
            self.request_merge(pr_number=7)
        self.repositories.set_git_write_enabled(self.owner['web_token'], False)
        with self.assertRaises(Conflict):
            self.request_merge()
        self.repositories.set_git_write_enabled(self.owner['web_token'], True)
        other = self.tasks.create_task(self.owner['web_token'], 'other', 'Other', 'src')
        self.tasks.claim_task(self.member['agent_token'], other['id'], session_key='s3')
        with self.assertRaises(Conflict):
            self.request_merge(task_id=other['id'], session_key='s3')

    def test_re_request_refreshes_head_after_redelivery(self):
        self.request_merge()
        self.sync.open_pr(self.member['agent_token'], self.task['id'], self.branch, 'e' * 40,
                          'main', 'Task 1: Build it', 'Delivery body', 'd2', 's1', 1)
        refreshed = self.request_merge(request_key='m2')
        self.assertEqual(refreshed['head_sha'], 'e' * 40)


class MergePrTests(MergeFixture, unittest.TestCase):
    def setUp(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        self.build(root / 'merge.sqlite3')
        self.request = self.request_merge()

    def merge(self, **overrides):
        args = {'token': self.owner['web_token'], 'merge_request_id': self.request['id']}
        args.update(overrides)
        return self.sync.merge_pr(**args)

    def test_merge_succeeds_and_records_delivery_merged(self):
        with self.identity.db.connect() as c:
            before = c.execute('SELECT state FROM tasks WHERE id=?', (self.task['id'],)).fetchone()['state']
        result = self.merge()
        self.assertEqual(result['state'], 'merged')
        self.assertEqual(result['merge_sha'], 'd' * 40)
        self.assertEqual(result['merged_by'], self.owner['member_id'])
        self.assertEqual(self.delivery_row()['state'], 'merged')
        self.assertEqual(self.app.merges, [{'number': 42, 'head_sha': 'c' * 40}])
        # D6: the merge records delivery; it never accepts the task and creates
        # no delivery suggestion on its own.
        with self.identity.db.connect() as c:
            task = c.execute('SELECT state FROM tasks WHERE id=?', (self.task['id'],)).fetchone()
            has_table = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='delivery_suggestions'").fetchone()
            suggestions = c.execute('SELECT COUNT(*) FROM delivery_suggestions').fetchone()[0] if has_table else 0
        self.assertEqual(task['state'], before)
        self.assertEqual(suggestions, 0)

    def test_merge_is_idempotent_and_previews_without_merging(self):
        preview = self.merge(preview=True)
        self.assertTrue(preview['preview'])
        self.assertFalse(preview['blocked'])
        self.assertEqual(preview['api_call']['method'], 'PUT')
        self.assertEqual(preview['api_call']['sha'], 'c' * 40)
        self.assertEqual(preview['api_call']['merge_method'], 'merge')
        self.assertEqual(self.app.merges, [])
        self.merge()
        again = self.merge()
        self.assertEqual(again['state'], 'merged')
        self.assertEqual(len(self.app.merges), 1)

    def test_preview_of_already_merged_pr_writes_nothing(self):
        self.app.pr['merged'] = True
        self.app.pr['state'] = 'closed'
        self.app.pr['merge_commit_sha'] = 'd' * 40
        before_request = self.merge_request_row()
        before_delivery = self.delivery_row()
        preview = self.merge(preview=True)
        self.assertTrue(preview['preview'])
        self.assertTrue(preview['already_merged'])
        self.assertEqual(preview['merge_commit_sha'], 'd' * 40)
        self.assertIsNone(preview['api_call'])
        self.assertEqual(self.app.merges, [])
        self.assertEqual(self.merge_request_row(), before_request)
        self.assertEqual(self.delivery_row(), before_delivery)

    def test_merge_requires_manager_web_token(self):
        with self.assertRaises(AccessDenied):
            self.merge(token=self.member['agent_token'])
        with self.assertRaises(AccessDenied):
            self.merge(token=self.member['web_token'])
        self.assertEqual(self.app.merges, [])

    def test_merge_rejects_unknown_request_and_disabled_flag(self):
        with self.assertRaises(NotFound):
            self.merge(merge_request_id=999)
        self.repositories.set_git_write_enabled(self.owner['web_token'], False)
        with self.assertRaises(Conflict):
            self.merge()
        self.assertEqual(self.app.merges, [])

    def test_head_moved_blocks_without_api_merge(self):
        self.app.pr['head_sha'] = 'e' * 40
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('head moved', str(caught.exception))
        self.assertEqual(self.app.merges, [])
        self.assertEqual(self.merge_request_row()['state'], 'pending')

    def test_mergeable_false_blocks(self):
        self.app.pr['mergeable'] = False
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('conflicts', str(caught.exception))
        self.assertEqual(self.app.merges, [])

    def test_failing_checks_block_with_names(self):
        self.app.pr['checks'] = [
            {'head_sha': 'c' * 40, 'name': 'lint', 'status': 'completed', 'conclusion': 'failure'},
            {'head_sha': 'c' * 40, 'name': 'tests', 'status': 'completed', 'conclusion': 'success'}]
        self.app.pr['statuses'] = [{'head_sha': 'c' * 40, 'context': 'deploy', 'state': 'error'}]
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('lint', str(caught.exception))
        self.assertIn('deploy', str(caught.exception))
        self.assertEqual(self.app.merges, [])

    def test_truncated_checks_block(self):
        self.app.pr['checks_truncated'] = True
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('truncated', str(caught.exception))
        self.assertEqual(self.app.merges, [])

    def test_protection_restrictions_block(self):
        self.app.protection = {'required_status_checks': {'contexts': []},
                               'required_pull_request_reviews': {'required_approving_review_count': 0},
                               'restrictions': {'users': ['octo'], 'teams': [], 'apps': []}}
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('restrictions', str(caught.exception))
        self.assertEqual(self.app.merges, [])

    def test_required_context_must_pass(self):
        self.app.protection = {'required_status_checks': {'contexts': ['ci']},
                               'required_pull_request_reviews': {'required_approving_review_count': 0},
                               'restrictions': None}
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('ci', str(caught.exception))
        self.app.pr['checks'] = [{'head_sha': 'c' * 40, 'name': 'ci', 'status': 'completed',
                                  'conclusion': 'success'}]
        self.assertEqual(self.merge()['state'], 'merged')

    def test_required_approvals_count_latest_review_per_reviewer(self):
        self.app.protection = {'required_status_checks': {'contexts': []},
                               'required_pull_request_reviews': {'required_approving_review_count': 2},
                               'restrictions': None}
        self.app.review_payload = {'reviews': [
            {'reviewer': 'a', 'state': 'APPROVED'},
            {'reviewer': 'a', 'state': 'CHANGES_REQUESTED'},
            {'reviewer': 'b', 'state': 'APPROVED'},
            {'reviewer': 'c', 'state': 'COMMENTED'}], 'truncated': False}
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('2 approving', str(caught.exception))
        self.assertEqual(self.app.review_calls, [42])
        self.app.review_payload['reviews'].append({'reviewer': 'a', 'state': 'APPROVED'})
        self.assertEqual(self.merge()['state'], 'merged')

    def test_author_approval_never_counts_toward_required_reviews(self):
        self.app.pr['author'] = 'a'
        self.app.protection = {'required_status_checks': {'contexts': []},
                               'required_pull_request_reviews': {'required_approving_review_count': 1},
                               'restrictions': None}
        self.app.review_payload = {'reviews': [{'reviewer': 'a', 'state': 'APPROVED'}], 'truncated': False}
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('1 approving', str(caught.exception))
        self.app.review_payload['reviews'].append({'reviewer': 'b', 'state': 'APPROVED'})
        self.assertEqual(self.merge()['state'], 'merged')

    def test_unknown_author_blocks_when_approvals_required(self):
        self.app.pr['author'] = None
        self.app.protection = {'required_status_checks': {'contexts': []},
                               'required_pull_request_reviews': {'required_approving_review_count': 1},
                               'restrictions': None}
        self.app.review_payload = {'reviews': [{'reviewer': 'a', 'state': 'APPROVED'}], 'truncated': False}
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('cannot verify the PR author', str(caught.exception))
        self.assertEqual(self.app.merges, [])

    def test_unknown_author_without_required_approvals_still_merges(self):
        self.app.pr['author'] = None
        self.assertEqual(self.merge()['state'], 'merged')

    def test_truncated_reviews_block_when_approvals_required(self):
        self.app.protection = {'required_status_checks': {'contexts': []},
                               'required_pull_request_reviews': {'required_approving_review_count': 1},
                               'restrictions': None}
        self.app.review_payload = {'reviews': [{'reviewer': 'a', 'state': 'APPROVED'}], 'truncated': True}
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('truncated', str(caught.exception))

    def test_already_merged_pr_marks_merged_without_put(self):
        self.app.pr['merged'] = True
        self.app.pr['state'] = 'closed'
        self.app.pr['merge_commit_sha'] = 'd' * 40
        result = self.merge()
        self.assertEqual(result['state'], 'merged')
        self.assertEqual(result['merge_sha'], 'd' * 40)
        self.assertEqual(self.app.merges, [])

    def test_put_refusal_blocks_but_concurrent_merge_recovers(self):
        self.app.fail_merge = True
        with self.assertRaises(Conflict) as caught:
            self.merge()
        self.assertIn('refused', str(caught.exception))
        self.assertEqual(self.merge_request_row()['state'], 'pending')
        self.app.flip_on_fail = True
        result = self.merge()
        self.assertEqual(result['state'], 'merged')
        self.assertEqual(result['merge_sha'], 'd' * 40)


class OverrideTests(unittest.TestCase):
    def setUp(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        self.identity = IdentityStore(root / 'override.sqlite3')
        self.owner = self.identity.create_room('Team', 'Owner')
        self.member = self.identity.add_member(self.owner['web_token'], 'Member')
        self.other = self.identity.add_member(self.owner['web_token'], 'Other')
        self.repositories = RepositoryStore(self.identity)
        self.repositories.bind_repository(self.owner['web_token'], 'github.com/acme/demo')
        self.repositories.set_git_write_enabled(self.owner['web_token'], True)
        self.tasks = TaskStore(self.identity)
        self.first = self.tasks.create_task(self.owner['web_token'], 'first', 'Build Login', 'src')
        self.tasks.claim_task(self.member['agent_token'], self.first['id'], session_key='s1')
        self.second = self.tasks.create_task(self.owner['web_token'], 'second', 'Fix Shared', 'src')
        self.tasks.claim_task(self.other['agent_token'], self.second['id'], session_key='s2')

        def observe(token, task_id, session_key, workspace_id):
            self.repositories.observe(token, task_id, {
                'request_key': 'k-' + str(uuid4()), 'workspace_id': workspace_id,
                'repository': 'github.com/acme/demo', 'branch': 'main', 'head': 'a' * 40,
                'paths': ['src/shared.py'], 'captured_at': fresh()},
                session_key=session_key, ownership_epoch=1)

        observe(self.member['agent_token'], self.first['id'], 's1', 'workspace-first-1')
        observe(self.other['agent_token'], self.second['id'], 's2', 'workspace-second-1')
        self.repositories.check_overlap(self.member['agent_token'], self.first['id'],
                                        session_key='s1', ownership_epoch=1, gate='claim')
        with self.identity.db.connect() as c:
            self.block = dict(c.execute('SELECT * FROM git_conflict_blocks').fetchone())

    def test_override_clears_block_unblocks_gate_and_audits(self):
        result = self.repositories.override_overlap(self.owner['web_token'], self.block['id'],
                                                    'Coordinated in standup')
        self.assertEqual(result['task_id'], self.first['id'])
        self.assertEqual(json.loads(result['paths_json']), ['src/shared.py'])
        self.assertEqual(result['overridden_by'], self.owner['member_id'])
        with self.identity.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM git_conflict_blocks').fetchone()[0], 0)
            audit = c.execute("SELECT * FROM git_write_audit WHERE action='overlap_override'").fetchone()
        self.assertEqual(audit['member_id'], self.owner['member_id'])
        self.assertIn('standup', audit['scope_json'])
        check = self.repositories.check_overlap(self.member['agent_token'], self.first['id'],
                                                session_key='s1', ownership_epoch=1)
        self.assertFalse(check['blocked'])

    def test_override_requires_manager_and_valid_reason(self):
        with self.assertRaises(AccessDenied):
            self.repositories.override_overlap(self.member['agent_token'], self.block['id'], 'ok')
        with self.assertRaises(AccessDenied):
            self.repositories.override_overlap(self.member['web_token'], self.block['id'], 'ok')
        with self.assertRaises(ValidationError):
            self.repositories.override_overlap(self.owner['web_token'], self.block['id'], '')
        with self.assertRaises(ValidationError):
            self.repositories.override_overlap(self.owner['web_token'], self.block['id'], 'x' * 501)

    def test_override_rejects_unknown_block_and_disabled_flag(self):
        with self.assertRaises(NotFound):
            self.repositories.override_overlap(self.owner['web_token'], 999, 'ok')
        self.repositories.set_git_write_enabled(self.owner['web_token'], False)
        with self.assertRaises(Conflict):
            self.repositories.override_overlap(self.owner['web_token'], self.block['id'], 'ok')


class MergeCardTests(unittest.TestCase):
    def test_merge_request_surfaces_as_card_until_merged(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        app = MergeFakeProvider()
        service = CoordinationService(root / 'cards.sqlite3', github_app=app)
        owner = service.identity.create_room('Team', 'Owner')
        member = service.identity.add_member(owner['web_token'], 'Member')
        service.repositories.bind_repository(owner['web_token'], 'github.com/acme/demo')
        service.repositories.set_git_write_enabled(owner['web_token'], True)
        task = service.tasks.create_task(owner['web_token'], 'task', 'Build Login', 'src')
        service.tasks.claim_task(member['agent_token'], task['id'], session_key='s1')
        begun = service.github.begin_authorization(owner['web_token'])
        service.github.complete_authorization(begun['state'], 'code')
        service.github.finish_authorization(owner['web_token'], begun['state'])
        branch = 'coopagents/task-%d-1-build-login' % task['id']
        app.pr['head_branch'] = branch
        service.repositories.record_branch(member['agent_token'], task['id'], branch, 'a' * 40,
                                           'branch-key', session_key='s1', ownership_epoch=1)
        service.repositories.observe(member['agent_token'], task['id'], {
            'request_key': 'k-' + str(uuid4()), 'workspace_id': 'workspace-card-1',
            'repository': 'github.com/acme/demo', 'branch': branch, 'head': 'c' * 40,
            'paths': ['src/login.py'], 'captured_at': fresh()}, session_key='s1', ownership_epoch=1)
        service.github.open_pr(member['agent_token'], task['id'], branch, 'c' * 40, 'main',
                               'Task 1: Build it', 'Delivery body', 'd1', 's1', 1)
        requested = service.call('request_merge', member['agent_token'], {
            'task_id': task['id'], 'pr_number': 42, 'request_key': 'm1',
            'session_key': 's1', 'ownership_epoch': 1})
        workflow = service.call('read_workflow', owner['web_token'], {})
        cards = [card for card in workflow['decisions'] if card['kind'] == 'git_merge']
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card['pr_number'], 42)
        self.assertEqual(card['operation'], 'merge_pr')
        self.assertEqual(card['payload'], {'merge_request_id': requested['id']})
        self.assertTrue(card['eligible'])
        self.assertTrue(card['requires_human'])
        merged = service.call('merge_pr', owner['web_token'], {'merge_request_id': requested['id']})
        self.assertEqual(merged['state'], 'merged')
        workflow = service.call('read_workflow', owner['web_token'], {})
        self.assertEqual([card for card in workflow['decisions'] if card['kind'] == 'git_merge'], [])


class MergeRouteTests(unittest.TestCase):
    def test_merge_and_override_routes_enforce_web_manager(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        app = MergeFakeProvider()
        http = create_app(root / 'routes.sqlite3', base_url='http://127.0.0.1', github_app=app)
        service = http.state.service
        owner = service.identity.create_room('Team', 'Owner')
        member = service.identity.add_member(owner['web_token'], 'Member')
        service.repositories.bind_repository(owner['web_token'], 'github.com/acme/demo')
        service.repositories.set_git_write_enabled(owner['web_token'], True)
        task = service.tasks.create_task(owner['web_token'], 'task', 'Build Login', 'src')
        service.tasks.claim_task(member['agent_token'], task['id'], session_key='s1')
        branch = 'coopagents/task-%d-1-build-login' % task['id']
        app.pr['head_branch'] = branch
        service.repositories.record_branch(member['agent_token'], task['id'], branch, 'a' * 40,
                                           'branch-key', session_key='s1', ownership_epoch=1)
        service.repositories.observe(member['agent_token'], task['id'], {
            'request_key': 'k-' + str(uuid4()), 'workspace_id': 'workspace-route-1',
            'repository': 'github.com/acme/demo', 'branch': branch, 'head': 'c' * 40,
            'paths': ['src/login.py'], 'captured_at': fresh()}, session_key='s1', ownership_epoch=1)
        web = {'Authorization': 'Bearer ' + owner['web_token']}
        agent = {'Authorization': 'Bearer ' + member['agent_token']}
        with TestClient(http, base_url='http://127.0.0.1') as client:
            begun = client.post('/api/git/github/authorize', headers=web, json={})
            state = begun.json()['state']
            client.get('/api/git/github/callback', params={'state': state, 'code': 'code'})
            client.post('/api/git/github/finish', headers=web, json={'state': state})
            delivered = client.post('/api/git/deliveries', headers=agent, json={
                'task_id': task['id'], 'branch': branch, 'head_sha': 'c' * 40,
                'base_branch': 'main', 'title': 'Task 1: Build it', 'body': '',
                'request_key': 'd1', 'session_key': 's1', 'ownership_epoch': 1})
            self.assertEqual(delivered.status_code, 200, delivered.text)
            requested = client.post('/api/operations/request_merge', headers=agent, json={
                'task_id': task['id'], 'pr_number': 42, 'request_key': 'm1',
                'session_key': 's1', 'ownership_epoch': 1})
            self.assertEqual(requested.status_code, 200, requested.text)
            merge_id = requested.json()['id']
            denied = client.post('/api/git/merge', headers=agent, json={'merge_request_id': merge_id})
            self.assertEqual(denied.status_code, 401, denied.text)
            merged = client.post('/api/git/merge', headers=web, json={'merge_request_id': merge_id})
            self.assertEqual(merged.status_code, 200, merged.text)
            self.assertEqual(merged.json()['state'], 'merged')
            missing = client.post('/api/git/overlap-overrides', headers=web,
                                  json={'block_id': 999, 'reason': 'ok'})
            self.assertEqual(missing.status_code, 404, missing.text)


if __name__ == '__main__':
    unittest.main()
