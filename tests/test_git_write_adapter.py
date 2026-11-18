import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from coopagents.errors import Conflict, ValidationError
from coopagents.git_adapter import LocalAdapter
from coopagents.local_outbox import OutboxError


def git(path, *args):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull, '-C', str(path), *args],
                            capture_output=True, env=env, check=True)
    return result.stdout


def make_bare(root):
    bare = root / ('bare-' + str(uuid4())[:8] + '.git')
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    git(bare, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    return bare


def make_seed(root, remote):
    repo = root / ('seed-' + str(uuid4())[:8])
    repo.mkdir(parents=True)
    subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
    git(repo, 'config', 'commit.gpgsign', 'false')
    git(repo, 'config', 'user.name', 'Test')
    git(repo, 'config', 'user.email', 'test@example.com')
    (repo / 'README.md').write_text('hello\n', encoding='utf-8')
    git(repo, 'add', 'README.md')
    git(repo, 'commit', '-m', 'initial')
    git(repo, 'branch', '-M', 'main')
    git(repo, 'remote', 'add', 'origin', str(Path(remote).resolve()))
    git(repo, 'push', 'origin', 'main')
    return repo


def clone_repo(remote, dest):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    subprocess.run(['git', 'clone', str(Path(remote).resolve()), str(dest)], check=True,
                   capture_output=True, env=env)
    git(dest, 'config', 'commit.gpgsign', 'false')
    git(dest, 'config', 'user.name', 'Test')
    git(dest, 'config', 'user.email', 'test@example.com')
    # Keep a GitHub-shaped origin identity (inspect() requires one) while the
    # transport rewrites to the local bare repo, so fetch/push stay offline.
    git(dest, 'remote', 'set-url', 'origin', 'https://github.com/acme/demo.git')
    git(dest, 'config', 'url.%s.insteadOf' % Path(remote).resolve(),
        'https://github.com/acme/demo.git')
    return dest


class CreateBranchAdapterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / str(uuid4())
        self.root.mkdir(parents=True)
        self.bare = make_bare(self.root)
        self.seed = make_seed(self.root, self.bare)
        self.head = git(self.seed, 'rev-parse', 'HEAD').decode().strip()
        self.repo = clone_repo(self.bare, self.root / 'clone')
        self.project = str(uuid4())
        self.adapter = LocalAdapter(self.repo, 'http://127.0.0.1:1', self.project, 'valid-token',
                                    state_root=self.root / 'queue')
        self.repository = self.adapter.workspace.inspect()['repository']
        self.tasks = [{'id': 7, 'title': 'Build Login', 'ownership_epoch': 1}]

    def stub(self, enabled=True, tasks=None, fail_network=False, blocked=False):
        calls = []

        def request(path, data=None):
            calls.append((path, data))
            if fail_network:
                raise OutboxError('network')
            if path == '/api/me':
                return {'me': {'room_id': self.project}}
            if path == '/api/git/binding':
                return {'repository': self.repository, 'git_write_enabled': enabled}
            if path == '/api/git/team':
                return {'tasks': self.tasks if tasks is None else tasks}
            if path == '/api/git/overlap-check':
                return {'blocked': blocked, 'paths_checked': ['src/shared.py'],
                        'conflicts': [{'task_id': 9, 'member_id': 'm2', 'paths': ['src/shared.py'],
                                       'path_count': 1}] if blocked else []}
            if path == '/api/git/branches':
                return {'id': 1, 'branch': data['branch'], 'base_sha': data['base_sha']}
            if path == '/api/operations/request_merge':
                return {'id': 1, 'state': 'pending', 'pr_number': data['pr_number']}
            raise AssertionError('unexpected path ' + path)

        self.adapter.request = request
        return calls

    def branch_calls(self, calls):
        return [data for path, data in calls if path == '/api/git/branches']

    def test_create_branch_end_to_end_and_stays_local(self):
        calls = self.stub()
        result = self.adapter.create_branch(7, session_key='s1')
        self.assertEqual(result['status'], 'created')
        self.assertEqual(result['branch'], 'coopagents/task-7-1-build-login')
        self.assertEqual(result['base_sha'], self.head)
        self.assertEqual(result['default_branch'], 'main')
        self.assertEqual(git(self.repo, 'branch', '--show-current').decode().strip(),
                         'coopagents/task-7-1-build-login')
        recorded = self.branch_calls(calls)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]['task_id'], 7)
        self.assertEqual(recorded[0]['base_sha'], self.head)
        self.assertEqual(recorded[0]['session_key'], 's1')
        self.assertEqual(recorded[0]['ownership_epoch'], 1)
        self.assertNotIn('preview', recorded[0])
        self.assertTrue(recorded[0]['request_key'])
        self.assertEqual(git(self.bare, 'branch', '--list', 'coopagents/*').decode(), '')

    def test_create_branch_reuses_existing_branch_at_same_base(self):
        self.stub()
        self.adapter.create_branch(7, session_key='s1', ownership_epoch=1)
        again = self.adapter.create_branch(7, session_key='s1', ownership_epoch=1)
        self.assertEqual(again['status'], 'reused')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), self.head)

    def test_create_branch_reuse_from_another_branch_is_a_conflict(self):
        self.stub()
        self.adapter.create_branch(7, session_key='s1', ownership_epoch=1)
        git(self.repo, 'checkout', 'main')
        with self.assertRaises(Conflict):
            self.adapter.create_branch(7, session_key='s1', ownership_epoch=1)

    def test_preview_executes_no_writes(self):
        calls = self.stub()
        result = self.adapter.create_branch(7, session_key='s1', preview=True)
        self.assertEqual(result['status'], 'preview')
        self.assertTrue(result['preview'])
        self.assertEqual(result['branch'], 'coopagents/task-7-1-build-login')
        self.assertEqual(result['base_sha'], self.head)
        commands = [' '.join(command) for command in result['commands']]
        self.assertTrue(any('fetch' in command for command in commands))
        self.assertTrue(any('checkout -b' in command for command in commands))
        self.assertEqual(git(self.repo, 'branch', '--show-current').decode().strip(), 'main')
        self.assertEqual(git(self.repo, 'branch', '--list', 'coopagents/*').decode(), '')
        recorded = self.branch_calls(calls)
        self.assertEqual(len(recorded), 1)
        self.assertTrue(recorded[0]['preview'])

    def test_dirty_tree_blocks_without_any_service_write(self):
        calls = self.stub()
        (self.repo / 'README.md').write_text('dirty\n', encoding='utf-8')
        result = self.adapter.create_branch(7, session_key='s1')
        self.assertEqual(result['status'], 'blocked_dirty')
        self.assertEqual(result['paths'], ['README.md'])
        self.assertEqual(self.branch_calls(calls), [])
        self.assertEqual(git(self.repo, 'branch', '--show-current').decode().strip(), 'main')

    def test_flag_off_fails_closed_before_any_git_write(self):
        calls = self.stub(enabled=False)
        result = self.adapter.create_branch(7, session_key='s1')
        self.assertEqual(result['status'], 'git_write_disabled')
        self.assertEqual(self.branch_calls(calls), [])
        self.assertEqual(git(self.repo, 'branch', '--list', 'coopagents/*').decode(), '')

    def test_offline_fails_fast_and_queues_nothing(self):
        self.stub(fail_network=True)
        result = self.adapter.create_branch(7, session_key='s1')
        self.assertEqual(result, {'status': 'service_unavailable', 'retryable': False})
        self.assertEqual(list((self.root / 'queue').glob('*.sqlite3')), [])
        self.assertEqual(git(self.repo, 'branch', '--list', 'coopagents/*').decode(), '')

    def test_bad_task_ids_and_missing_task_raise(self):
        self.stub()
        for bad in [-1, 0, True, '7']:
            with self.assertRaises(ValidationError):
                self.adapter.create_branch(bad)
        with self.assertRaises(ValidationError):
            self.adapter.create_branch(7, session_key='s1', preview='yes')
        self.stub(tasks=[])
        with self.assertRaises(ValidationError):
            self.adapter.create_branch(7, session_key='s1')

    def test_conflict_precheck_returns_without_git_writes(self):
        calls = self.stub(blocked=True)
        result = self.adapter.create_branch(7, session_key='s1', ownership_epoch=1)
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['conflicts'][0]['task_id'], 9)
        self.assertEqual(git(self.repo, 'branch', '--show-current').decode().strip(), 'main')
        self.assertEqual(git(self.repo, 'branch', '--list', 'coopagents/*').decode(), '')
        self.assertEqual(self.branch_calls(calls), [])
        gate = [data for path, data in calls if path == '/api/git/overlap-check']
        self.assertEqual(len(gate), 1)
        self.assertEqual(gate[0]['gate'], 'claim')
        self.assertEqual(gate[0]['task_id'], 7)
        self.assertNotIn('paths', gate[0])

    def test_request_merge_forwards_to_operations_endpoint(self):
        calls = self.stub()
        result = self.adapter.forward('request_merge', {'task_id': 7, 'pr_number': 42,
                                                       'request_key': 'm1', 'session_key': 's1',
                                                       'ownership_epoch': 1})
        self.assertEqual(result['state'], 'pending')
        forwarded = [(path, data) for path, data in calls if path == '/api/operations/request_merge']
        self.assertEqual(len(forwarded), 1)
        self.assertEqual(forwarded[0][1]['pr_number'], 42)


if __name__ == '__main__':
    unittest.main()


class DeliverAdapterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / str(uuid4())
        self.root.mkdir(parents=True)
        self.bare = make_bare(self.root)
        self.seed = make_seed(self.root, self.bare)
        self.head = git(self.seed, 'rev-parse', 'HEAD').decode().strip()
        self.repo = clone_repo(self.bare, self.root / 'clone')
        self.branch = 'coopagents/task-7-1-build-login'
        git(self.repo, 'checkout', '-b', self.branch)
        self.project = str(uuid4())
        self.adapter = LocalAdapter(self.repo, 'http://127.0.0.1:1', self.project, 'valid-token',
                                    state_root=self.root / 'queue')
        self.repository = self.adapter.workspace.inspect()['repository']
        self.tasks = [{'id': 7, 'title': 'Build Login', 'ownership_epoch': 1}]
        self.connection = {'status': 'active'}
        self.env = patch.dict(os.environ, {'COOPAGENTS_GIT_AUTHOR_EMAIL': 'wei@example.com'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def stub(self, enabled=True, connection='default', fail_network=False, blocked=False, fail_deliveries=0):
        calls = []
        remaining_failures = [fail_deliveries]

        def request(path, data=None):
            calls.append((path, data))
            if fail_network:
                raise OutboxError('network')
            if path == '/api/me':
                return {'me': {'room_id': self.project}}
            if path == '/api/git/binding':
                return {'repository': self.repository, 'git_write_enabled': enabled}
            if path == '/api/git/team':
                return {'tasks': self.tasks,
                        'me': {'member_id': 'm1', 'display_name': 'Wei Chen'},
                        'git': {'connection': self.connection if connection == 'default' else connection}}
            if path == '/api/git/checkpoint':
                return {'observation': data['observation'], 'team': {}, 'inbox': []}
            if path == '/api/git/overlap-check':
                return {'blocked': blocked, 'paths_checked': data.get('paths', []),
                        'conflicts': [{'task_id': 9, 'member_id': 'm2', 'paths': ['src/shared.py'],
                                       'path_count': 1}] if blocked else []}
            if path == '/api/git/deliveries':
                if remaining_failures[0] > 0:
                    remaining_failures[0] -= 1
                    raise OutboxError('network')
                return {'state': 'pr_opened', 'pr_number': 42,
                        'pr_url': 'https://github.com/acme/demo/pull/42',
                        'branch': data['branch'], 'head_sha': data['head_sha']}
            raise AssertionError('unexpected path ' + path)

        self.adapter.request = request
        return calls

    def attempt_path(self):
        return self.adapter._attempt_path(self.adapter.workspace.inspect(), 7, self.branch)

    def paths_called(self, calls, path):
        return [data for called, data in calls if called == path]

    def test_deliver_end_to_end_commits_pushes_and_opens_pr(self):
        calls = self.stub()
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        result = self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertEqual(result['status'], 'pr_opened')
        self.assertEqual(result['pr_number'], 42)
        self.assertEqual(result['pr_url'], 'https://github.com/acme/demo/pull/42')
        new_head = git(self.repo, 'rev-parse', 'HEAD').decode().strip()
        self.assertNotEqual(new_head, self.head)
        self.assertEqual(result['head_sha'], new_head)
        author = git(self.repo, 'log', '-1', '--format=%an <%ae>').decode().strip()
        self.assertEqual(author, 'Wei Chen <wei@example.com>')
        message = git(self.repo, 'log', '-1', '--format=%B').decode()
        self.assertTrue(message.startswith('Task 7: Ship the login\n\nCoopagents-task: 7'))
        remote_head = git(self.bare, 'rev-parse', 'refs/heads/' + self.branch).decode().strip()
        self.assertEqual(remote_head, new_head)
        checkpoints = self.paths_called(calls, '/api/git/checkpoint')
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(checkpoints[0]['observation']['paths'], ['README.md'])
        delivered = self.paths_called(calls, '/api/git/deliveries')
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]['branch'], self.branch)
        self.assertEqual(delivered[0]['head_sha'], new_head)
        self.assertEqual(delivered[0]['base_branch'], 'main')
        self.assertEqual(delivered[0]['title'], 'Task 7: Ship the login')
        self.assertIn('Branch: ' + self.branch, delivered[0]['body'])
        self.assertIn('Commit: ' + new_head, delivered[0]['body'])
        self.assertEqual(delivered[0]['session_key'], 's1')
        self.assertEqual(delivered[0]['ownership_epoch'], 1)
        self.assertTrue(delivered[0]['request_key'])

    def test_deliver_uses_env_author_name_when_set(self):
        self.stub()
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        with patch.dict(os.environ, {'COOPAGENTS_GIT_AUTHOR_NAME': 'Custom Name'}):
            self.adapter.deliver(7, 'Ship it', session_key='s1')
        author = git(self.repo, 'log', '-1', '--format=%an <%ae>').decode().strip()
        self.assertEqual(author, 'Custom Name <wei@example.com>')

    def test_retry_after_registration_failure_resumes_without_new_edits(self):
        calls = self.stub(fail_deliveries=1)
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        with self.assertRaises(OutboxError):
            self.adapter.deliver(7, 'Ship the login', session_key='s1')
        head = git(self.repo, 'rev-parse', 'HEAD').decode().strip()
        self.assertNotEqual(head, self.head)
        self.assertEqual(git(self.bare, 'rev-parse', 'refs/heads/' + self.branch).decode().strip(), head)
        self.assertTrue(self.attempt_path().is_file())
        result = self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertEqual(result['status'], 'pr_opened')
        self.assertEqual(result['head_sha'], head)
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), head)
        delivered = self.paths_called(calls, '/api/git/deliveries')
        self.assertEqual(len(delivered), 2)
        self.assertEqual(delivered[0]['request_key'], delivered[1]['request_key'])
        self.assertFalse(self.attempt_path().exists())

    def test_retry_after_push_failure_resumes_without_new_edits(self):
        from coopagents.git_writer import GitWriter
        calls = self.stub()
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        original = GitWriter.push_branch
        state = {'failed': False}

        def flaky(self, branch, preview=False):
            if not state['failed']:
                state['failed'] = True
                raise ValidationError('Git push was rejected')
            return original(self, branch, preview=preview)

        with patch.object(GitWriter, 'push_branch', flaky):
            with self.assertRaises(ValidationError):
                self.adapter.deliver(7, 'Ship the login', session_key='s1')
        head = git(self.repo, 'rev-parse', 'HEAD').decode().strip()
        self.assertEqual(git(self.bare, 'branch', '--list', 'coopagents/*').decode(), '')
        self.assertTrue(self.attempt_path().is_file())
        result = self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertEqual(result['status'], 'pr_opened')
        self.assertEqual(result['head_sha'], head)
        self.assertEqual(git(self.bare, 'rev-parse', 'refs/heads/' + self.branch).decode().strip(), head)
        self.assertFalse(self.attempt_path().exists())

    def test_resume_honors_overlap_gate_and_keeps_attempt(self):
        calls = self.stub(fail_deliveries=1)
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        with self.assertRaises(OutboxError):
            self.adapter.deliver(7, 'Ship the login', session_key='s1')
        blocked_calls = self.stub(blocked=True)
        result = self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertEqual(result['status'], 'conflict')
        self.assertTrue(self.attempt_path().is_file())
        gate = self.paths_called(blocked_calls, '/api/git/overlap-check')
        self.assertEqual(gate[-1]['paths'], ['README.md'])
        self.assertEqual(gate[-1]['gate'], 'delivery')
        self.stub()
        result = self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertEqual(result['status'], 'pr_opened')
        self.assertFalse(self.attempt_path().exists())

    def test_stale_attempt_is_discarded_when_head_moves(self):
        self.stub(fail_deliveries=1)
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        with self.assertRaises(OutboxError):
            self.adapter.deliver(7, 'Ship the login', session_key='s1')
        (self.repo / 'extra.py').write_text('x=1\n', encoding='utf-8')
        git(self.repo, 'add', 'extra.py')
        git(self.repo, 'commit', '-m', 'own tools')
        with self.assertRaises(ValidationError) as caught:
            self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertIn('No changes to deliver', str(caught.exception))
        self.assertFalse(self.attempt_path().exists())

    def test_corrupt_attempt_file_is_ignored(self):
        self.stub()
        path = self.attempt_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{not json', encoding='utf-8')
        with self.assertRaises(ValidationError) as caught:
            self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertIn('No changes to deliver', str(caught.exception))

    def test_pending_attempt_adopted_when_post_commit_write_fails(self):
        import json
        from coopagents.git_adapter import LocalAdapter
        calls = self.stub()
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        original = LocalAdapter.__dict__['_write_attempt'].__func__
        state = {'writes': 0}

        def flaky(path, attempt):
            state['writes'] += 1
            if state['writes'] == 2:
                raise OSError('disk full')
            return original(path, attempt)

        with patch.object(LocalAdapter, '_write_attempt', staticmethod(flaky)):
            with self.assertRaises(OSError):
                self.adapter.deliver(7, 'Ship the login', session_key='s1')
        head = git(self.repo, 'rev-parse', 'HEAD').decode().strip()
        self.assertNotEqual(head, self.head)
        pending = json.loads(self.attempt_path().read_text(encoding='utf-8'))
        self.assertIsNone(pending['head_sha'])
        self.assertEqual(pending['parent_sha'], self.head)
        result = self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertEqual(result['status'], 'pr_opened')
        self.assertEqual(result['head_sha'], head)
        delivered = self.paths_called(calls, '/api/git/deliveries')
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]['request_key'], pending['request_key'])
        self.assertIn('Commit: ' + head, delivered[0]['body'])
        self.assertFalse(self.attempt_path().exists())

    def test_pre_commit_write_failure_blocks_before_any_commit(self):
        from coopagents.git_adapter import LocalAdapter
        self.stub()
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')

        def failing(path, attempt):
            raise OSError('read-only filesystem')

        with patch.object(LocalAdapter, '_write_attempt', staticmethod(failing)):
            with self.assertRaises(OSError):
                self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), self.head)
        self.assertFalse(self.attempt_path().exists())
        result = self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertEqual(result['status'], 'pr_opened')
        self.assertFalse(self.attempt_path().exists())

    def test_pending_attempt_rejected_when_head_touches_other_paths(self):
        self.stub()
        path = self.attempt_path()
        self.adapter._write_attempt(path, {
            'schema_version': 1, 'task_id': 7, 'ownership_epoch': 1,
            'branch': self.branch, 'head_sha': None, 'parent_sha': self.head,
            'paths': ['README.md'], 'request_key': 'k-pending',
            'base_branch': 'main', 'title': 'Task 7: Ship the login', 'body': None,
            'task_title': 'Build Login', 'summary': 'Ship the login'})
        (self.repo / 'extra.py').write_text('x=1\n', encoding='utf-8')
        git(self.repo, 'add', 'extra.py')
        git(self.repo, 'commit', '-m', 'own tools')
        with self.assertRaises(ValidationError) as caught:
            self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertIn('No changes to deliver', str(caught.exception))
        self.assertFalse(path.exists())

    def test_pending_attempt_discarded_when_no_commit_happened(self):
        self.stub()
        path = self.attempt_path()
        self.adapter._write_attempt(path, {
            'schema_version': 1, 'task_id': 7, 'ownership_epoch': 1,
            'branch': self.branch, 'head_sha': None, 'parent_sha': self.head,
            'paths': ['README.md'], 'request_key': 'k-pending',
            'base_branch': 'main', 'title': 'Task 7: Ship the login', 'body': None,
            'task_title': 'Build Login', 'summary': 'Ship the login'})
        with self.assertRaises(ValidationError) as caught:
            self.adapter.deliver(7, 'Ship the login', session_key='s1')
        self.assertIn('No changes to deliver', str(caught.exception))
        self.assertFalse(path.exists())

    def test_deliver_preview_executes_no_writes(self):
        calls = self.stub()
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        result = self.adapter.deliver(7, 'Ship the login', session_key='s1', preview=True)
        self.assertEqual(result['status'], 'preview')
        self.assertTrue(result['preview'])
        self.assertEqual(result['paths'], ['README.md'])
        commands = [' '.join(command) for command in result['commands']]
        self.assertTrue(any('add -- README.md' in command for command in commands))
        self.assertTrue(any('commit -F' in command for command in commands))
        self.assertTrue(any('push origin refs/heads/' + self.branch + ':refs/heads/' + self.branch in command for command in commands))
        self.assertTrue(any('push.followTags=false' in command for command in commands))
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), self.head)
        self.assertEqual(git(self.bare, 'branch', '--list', 'coopagents/*').decode(), '')
        self.assertEqual(self.paths_called(calls, '/api/git/checkpoint'), [])
        delivered = self.paths_called(calls, '/api/git/deliveries')
        self.assertEqual(len(delivered), 1)
        self.assertTrue(delivered[0]['preview'])

    def test_deliver_flag_off_and_untrusted_connection_block_before_writes(self):
        calls = self.stub(enabled=False)
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        result = self.adapter.deliver(7, 'Ship it', session_key='s1')
        self.assertEqual(result['status'], 'git_write_disabled')
        calls = self.stub(connection=None)
        result = self.adapter.deliver(7, 'Ship it', session_key='s1')
        self.assertEqual(result['status'], 'github_not_authorized')
        calls = self.stub(connection={'status': 'revoked'})
        result = self.adapter.deliver(7, 'Ship it', session_key='s1')
        self.assertEqual(result['status'], 'github_not_authorized')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), self.head)
        self.assertEqual(self.paths_called(calls, '/api/git/deliveries'), [])

    def test_deliver_wrong_branch_reports_without_writing(self):
        self.stub()
        git(self.repo, 'checkout', 'main')
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        result = self.adapter.deliver(7, 'Ship it', session_key='s1')
        self.assertEqual(result['status'], 'wrong_branch')
        self.assertEqual(result['branch'], 'main')
        self.assertEqual(result['expected_branch'], self.branch)
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), self.head)

    def test_deliver_no_changes_and_secret_paths_raise(self):
        calls = self.stub()
        with self.assertRaises(ValidationError):
            self.adapter.deliver(7, 'Nothing here', session_key='s1')
        self.assertEqual(self.paths_called(calls, '/api/git/deliveries'), [])
        (self.repo / 'credentials.json').write_text('{}', encoding='utf-8')
        git(self.repo, 'add', 'credentials.json')
        git(self.repo, 'commit', '-m', 'track secret-shaped file')
        committed = git(self.repo, 'rev-parse', 'HEAD').decode().strip()
        (self.repo / 'credentials.json').write_text('{"k":1}', encoding='utf-8')
        with self.assertRaises(ValidationError):
            self.adapter.deliver(7, 'Ship it', session_key='s1')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), committed)
        self.assertEqual(self.paths_called(calls, '/api/git/deliveries'), [])

    def test_deliver_offline_fails_fast_and_queues_nothing(self):
        self.stub(fail_network=True)
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        result = self.adapter.deliver(7, 'Ship it', session_key='s1')
        self.assertEqual(result, {'status': 'service_unavailable', 'retryable': False})
        self.assertEqual(list((self.root / 'queue').glob('*.sqlite3')), [])
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), self.head)

    def test_deliver_requires_author_email(self):
        self.stub()
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        with patch.dict(os.environ):
            os.environ.pop('COOPAGENTS_GIT_AUTHOR_EMAIL', None)
            with self.assertRaises(ValidationError) as caught:
                self.adapter.deliver(7, 'Ship it', session_key='s1')
        self.assertIn('COOPAGENTS_GIT_AUTHOR_EMAIL', str(caught.exception))
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), self.head)

    def test_deliver_rechecks_overlap_before_git_add(self):
        calls = self.stub(blocked=True)
        (self.repo / 'README.md').write_text('shipped\n', encoding='utf-8')
        result = self.adapter.deliver(7, 'Ship it', session_key='s1', ownership_epoch=1)
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['conflicts'][0]['task_id'], 9)
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), self.head)
        self.assertNotEqual(git(self.repo, 'status', '--porcelain').decode(), '')
        self.assertEqual([path for path, _ in calls if path == '/api/git/deliveries'], [])
        gate = [data for path, data in calls if path == '/api/git/overlap-check']
        self.assertEqual(len(gate), 1)
        self.assertEqual(gate[0]['gate'], 'delivery')
        self.assertEqual(gate[0]['paths'], ['README.md'])
