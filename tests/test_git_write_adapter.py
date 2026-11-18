import os
import subprocess
import unittest
from pathlib import Path
from uuid import uuid4

from coopagents.errors import ValidationError
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

    def stub(self, enabled=True, tasks=None, fail_network=False):
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
            if path == '/api/git/branches':
                return {'id': 1, 'branch': data['branch'], 'base_sha': data['base_sha']}
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
        git(self.repo, 'checkout', 'main')
        again = self.adapter.create_branch(7, session_key='s1', ownership_epoch=1)
        self.assertEqual(again['status'], 'reused')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), self.head)

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


if __name__ == '__main__':
    unittest.main()
