"""Git write path W1: allowlisted local writes, branch recording, and the gate read."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents.errors import AccessDenied, Conflict, ValidationError
from coopagents.git_workspace import branch_name, parse_task_branch_name, task_branch_name, validate_relative_paths
from coopagents.git_writer import GitWriter, commit_message, find_secret_paths
from coopagents.identity import IdentityStore
from coopagents.repositories import RepositoryStore, now
from coopagents.tasks import TaskStore


def git(path, *args, data=None, check=True):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull, '-C', str(path), *args],
                            input=data, capture_output=True, env=env, timeout=15, check=check)
    return result.stdout


def make_repo(root, remote=None):
    repo = root / ('repo-' + str(uuid4())[:8])
    repo.mkdir(parents=True)
    subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
    git(repo, 'config', 'commit.gpgsign', 'false')
    git(repo, 'config', 'user.name', 'Test')
    git(repo, 'config', 'user.email', 'test@example.com')
    (repo / 'README.md').write_text('hello\n', encoding='utf-8')
    git(repo, 'add', 'README.md')
    git(repo, 'commit', '-m', 'initial')
    git(repo, 'branch', '-M', 'main')
    if remote is not None:
        git(repo, 'remote', 'add', 'origin', str(Path(remote).resolve()))
    return repo


def clone_repo(remote, dest):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    subprocess.run(['git', 'clone', str(Path(remote).resolve()), str(dest)], check=True, capture_output=True, env=env)
    git(dest, 'config', 'commit.gpgsign', 'false')
    git(dest, 'config', 'user.name', 'Test')
    git(dest, 'config', 'user.email', 'test@example.com')
    return dest


def make_bare(root):
    bare = root / ('bare-' + str(uuid4())[:8] + '.git')
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    return bare


class Recorder:
    def __init__(self, code=0):
        self.calls = []
        self.code = code
        self.message_files = []

    def __call__(self, command, env):
        # Record only git-related environment keys; never retain the full env.
        kept = {k: v for k, v in env.items() if k.upper().startswith('GIT_')}
        self.calls.append((list(command), kept))
        if '-F' in command:
            path = command[command.index('-F') + 1]
            self.message_files.append(Path(path).read_text(encoding='utf-8'))
        return b'', self.code


class BranchNamingTests(unittest.TestCase):
    def test_task_branch_name_is_deterministic_and_safe(self):
        self.assertEqual(task_branch_name(3, 2, 'Build Login Page!'), 'coopagents/task-3-2-build-login-page')
        self.assertEqual(task_branch_name(3, 2, 'Build Login Page!'), task_branch_name(3, 2, 'Build Login Page!'))
        self.assertEqual(task_branch_name(1, 1, '你好世界'), 'coopagents/task-1-1-task')
        self.assertEqual(task_branch_name(1, 1, 'Fix: crash!! now'), 'coopagents/task-1-1-fix-crash-now')
        self.assertNotEqual(task_branch_name(3, 2, 'Build'), task_branch_name(3, 3, 'Build'))

    def test_parse_task_branch_name_round_trips_and_rejects_foreign_names(self):
        for task_id, epoch, title in [(3, 2, 'Build Login Page!'), (1, 0, 'x'), (1, 1, '你好世界'),
                                      (7, 12, 'a' * 100)]:
            name = task_branch_name(task_id, epoch, title)
            self.assertEqual(parse_task_branch_name(name), {'task_id': task_id, 'ownership_epoch': epoch})
        for foreign in ['main', 'feature/login', 'coopagents/task-3-2-', 'coopagents/task-0-2-build',
                        'coopagents/task-007-2-build', 'coopagents/task-3-02-build',
                        'coopagents/task-3-2-Build', 'coopagents/task-3-2--build',
                        'coopagents/task-3-2-build-', 'coopagents/task-3-2-' + 'a' * 41,
                        'coopagents/task-3-build', 'coopagents/task-3-2-build/extra',
                        'xcoopagents/task-3-2-build', '', None, 42]:
            self.assertIsNone(parse_task_branch_name(foreign), foreign)
        self.assertIsNone(parse_task_branch_name('coopagents/task-%d-0-build' % 2**63))

    def test_branch_name_rejects_injection_and_option_like_values(self):
        for bad in ('', 'main --force', '+main', '-x', 'a..b', 'a@{b}', 'a b', 'a/b/.c', 'a.lock', 'a/', '/a',
                    'a~1', 'a^b', 'a:b', 'a?b', 'a*b', 'a[b', 'a\nb', 'x' * 251, None, 7):
            with self.subTest(value=bad), self.assertRaises(ValidationError):
                branch_name(bad)

    def test_branch_name_reexport_is_the_same_validator(self):
        from coopagents.github_sync import branch_name as synced
        self.assertIs(branch_name, synced)

    def test_relative_paths_reject_traversal_and_absolute(self):
        self.assertEqual(validate_relative_paths(['b.py', 'a.py', 'b.py']), ['a.py', 'b.py'])
        for bad in (['../x'], ['/x'], ['a/../b'], ['.git/config'], ['a//b'], ['a\\b'], ['a:b'], [''], ['x' * 501], ['a'] * 1001, 'a.py', [None]):
            with self.subTest(value=bad), self.assertRaises(ValidationError):
                validate_relative_paths(bad)

    def test_commit_message_template_and_bounds(self):
        message = commit_message(7, 'Add  login\nform')
        self.assertTrue(message.startswith('Task 7: Add login form\n\nCoopagents-task: 7'))
        with self.assertRaises(ValidationError):
            commit_message(7, '  ')
        with self.assertRaises(ValidationError):
            commit_message(7, 'x' * 1001)

    def test_secret_path_scan_is_name_only(self):
        flagged = find_secret_paths(['.env', 'a/.env.local', 'keys/id_rsa', 'keys/id_rsa.pub',
                                     'credentials.json', 'my-secret-key.txt', 'secrets/plan.md',
                                     '.coopagents/state.sqlite3', 'cert.pem', 'cert.key'])
        self.assertEqual(len(flagged), 10)
        self.assertEqual(find_secret_paths(['src/app.py', 'docs/env.md', 'config.envx']), [])

    def test_secret_path_scan_is_case_insensitive(self):
        flagged = find_secret_paths(['.ENV', '.Env.production', 'a/.ENV.local', 'keys/ID_RSA',
                                     'KEYS/Id_Rsa.Pub', 'CREDENTIALS.json', 'CERT.PEM', 'CERT.Key',
                                     '.COOPAGENTS/token', '.SSH/id_ed25519', 'My-Secret-Plan.md'])
        self.assertEqual(len(flagged), 11)
        self.assertEqual(find_secret_paths(['src/app.py', 'docs/ENV.md', 'config.ENVX']), [])


class GitWriterCommandTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / str(uuid4())
        self.root.mkdir(parents=True)
        self.repo = make_repo(self.root)
        self.head = git(self.repo, 'rev-parse', 'HEAD').decode().strip()

    def writer(self, recorder=None):
        return GitWriter(self.repo, runner=recorder or Recorder())

    def test_fetch_command_is_one_fixed_refspec(self):
        recorder = Recorder()
        writer = self.writer(recorder)
        result = writer.fetch_base('main', preview=True)
        self.assertTrue(result['preview'])
        self.assertEqual(recorder.calls, [])
        command = result['commands'][0]
        self.assertEqual(command[-4:], ['fetch', '--no-tags', 'origin', 'main:refs/remotes/origin/main'])
        self.assertNotIn('--all', command)
        self.assertNotIn('--prune', command)
        writer.fetch_base('main')
        self.assertEqual(len(recorder.calls), 1)
        self.assertEqual(recorder.calls[0][0][-4:], ['fetch', '--no-tags', 'origin', 'main:refs/remotes/origin/main'])

    def test_write_env_strips_git_overrides_but_keeps_user_config(self):
        recorder = Recorder()
        with patch.dict(os.environ, {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'x', 'GIT_DIR': '/evil'}):
            self.writer(recorder).fetch_base('main')
        env = recorder.calls[0][1]
        self.assertNotIn('GIT_CONFIG_COUNT', env)
        self.assertNotIn('GIT_DIR', env)
        self.assertNotIn('GIT_CONFIG_GLOBAL', env)
        self.assertEqual(env['GIT_TERMINAL_PROMPT'], '0')
        self.assertIn('core.hooksPath=' + os.devnull, recorder.calls[0][0])

    def test_create_branch_command_and_injection_rejection(self):
        recorder = Recorder()
        writer = self.writer(recorder)
        preview = writer.create_branch('coopagents/task-1-1-build', self.head, preview=True)
        self.assertEqual(preview['commands'][0][-4:], ['checkout', '-b', 'coopagents/task-1-1-build', self.head])
        for bad_branch, bad_sha in (('x --force', self.head), ('+main', self.head), ('-b', self.head),
                                    ('coopagents/task-1-1-build', 'xyz'), ('coopagents/task-1-1-build', self.head + ' '),
                                    ('coopagents/task-1-1-build', '')):
            with self.subTest(branch=bad_branch, sha=bad_sha), self.assertRaises(ValidationError):
                writer.create_branch(bad_branch, bad_sha)
        self.assertEqual(recorder.calls, [])

    def test_push_command_is_plain_and_cannot_be_forced(self):
        recorder = Recorder()
        writer = self.writer(recorder)
        writer.push_branch('coopagents/task-1-1-build')
        command = recorder.calls[0][0]
        self.assertEqual(command[-3:], ['push', 'origin', 'coopagents/task-1-1-build'])
        self.assertNotIn('--force', command)
        self.assertNotIn('--force-with-lease', command)
        self.assertFalse(any('+' in part for part in command[-3:]))
        for bad in ('x --force', '+main', 'main --force-with-lease'):
            with self.assertRaises(ValidationError):
                writer.push_branch(bad)
        self.assertEqual(len(recorder.calls), 1)

    def test_commit_uses_temp_file_message_and_per_invocation_authorship(self):
        (self.repo / 'work.py').write_text('x=1\n', encoding='utf-8')
        git(self.repo, 'add', 'work.py')
        recorder = Recorder()
        writer = self.writer(recorder)
        message = commit_message(4, 'Add work module')
        result = writer.stage_and_commit('main', ['work.py'], message, 'Wei Chen', 'wei@example.com')
        self.assertEqual(result['head_sha'], self.head)
        self.assertEqual(len(recorder.calls), 2)
        add, commit = (call[0] for call in recorder.calls)
        self.assertEqual(add[-3:], ['add', '--', 'work.py'])
        self.assertIn('-c', commit)
        self.assertIn('user.name=Wei Chen', commit)
        self.assertIn('user.email=wei@example.com', commit)
        self.assertEqual(commit[-3:-1], ['commit', '-F'])
        self.assertEqual(recorder.message_files, [message])
        self.assertFalse(Path(commit[-1]).exists())

    def test_stage_and_commit_rejects_secrets_bad_authors_and_empty_paths(self):
        recorder = Recorder()
        writer = self.writer(recorder)
        message = commit_message(4, 'Work')
        with self.assertRaises(ValidationError):
            writer.stage_and_commit('main', ['.env'], message, 'A', 'a@example.com')
        with self.assertRaises(ValidationError):
            writer.stage_and_commit('main', [], message, 'A', 'a@example.com')
        with self.assertRaises(ValidationError):
            writer.stage_and_commit('main', ['a.py'], message, 'Bad\nName', 'a@example.com')
        with self.assertRaises(ValidationError):
            writer.stage_and_commit('main', ['a.py'], message, 'A', 'not-an-email')
        with self.assertRaises(ValidationError):
            writer.stage_and_commit('main', ['a.py'], message, 'A', 'a@b')
        with self.assertRaises(ValidationError):
            writer.stage_and_commit('main', ['../evil.py'], message, 'A', 'a@example.com')
        self.assertEqual(recorder.calls, [])

    def test_stage_and_commit_refuses_paths_beyond_symlinked_dirs(self):
        outside = self.root / 'outside-dir'
        outside.mkdir()
        (outside / 'evil.txt').write_text('secret\n', encoding='utf-8')
        link = self.repo / 'link'
        link.symlink_to(outside.resolve(), target_is_directory=True)
        self.assertEqual(link.resolve(), outside.resolve())
        self.assertTrue((link / 'evil.txt').is_file())
        writer = GitWriter(self.repo)
        with self.assertRaises(ValidationError):
            writer.stage_and_commit('main', ['link/evil.txt'], commit_message(4, 'Work'),
                                    'A', 'a@example.com')
        self.assertEqual(git(self.repo, 'status', '--porcelain').decode().strip(), '?? link')

    def test_preview_executes_zero_writes(self):
        recorder = Recorder()
        writer = self.writer(recorder)
        writer.fetch_base('main', preview=True)
        writer.create_branch('coopagents/task-1-1-build', self.head, preview=True)
        writer.stage_and_commit('main', ['a.py'], commit_message(1, 'Work'), 'A', 'a@example.com', preview=True)
        writer.push_branch('coopagents/task-1-1-build', preview=True)
        self.assertEqual(recorder.calls, [])

    def test_runner_failure_maps_to_fixed_messages(self):
        recorder = Recorder(code=128)
        writer = self.writer(recorder)
        with self.assertRaises(ValidationError) as caught:
            writer.push_branch('coopagents/task-1-1-build')
        self.assertIn('push was rejected', str(caught.exception))
        with self.assertRaises(ValidationError) as caught:
            writer.fetch_base('main')
        self.assertEqual(str(caught.exception), 'Git fetch failed')


class GitWriterRealGitTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / str(uuid4())
        self.root.mkdir(parents=True)

    def test_create_branch_reuse_and_conflict(self):
        repo = make_repo(self.root)
        head = git(repo, 'rev-parse', 'HEAD').decode().strip()
        writer = GitWriter(repo)
        created = writer.create_branch('coopagents/task-1-1-build', head)
        self.assertFalse(created['reused'])
        self.assertEqual(writer.current_branch(), 'coopagents/task-1-1-build')
        reused = writer.create_branch('coopagents/task-1-1-build', head)
        self.assertTrue(reused['reused'])
        (repo / 'work.py').write_text('x=1\n', encoding='utf-8')
        git(repo, 'add', 'work.py')
        git(repo, 'commit', '-m', 'work')
        with self.assertRaises(Conflict):
            writer.create_branch('coopagents/task-1-1-build', head)

    def test_fetch_base_updates_remote_tracking_ref(self):
        bare = make_bare(self.root)
        seed = make_repo(self.root, remote=bare)
        git(seed, 'push', 'origin', 'main')
        clone = clone_repo(bare, self.root / 'clone')
        (seed / 'second.txt').write_text('two\n', encoding='utf-8')
        git(seed, 'add', 'second.txt')
        git(seed, 'commit', '-m', 'second')
        git(seed, 'push', 'origin', 'main')
        writer = GitWriter(clone)
        before = writer.ref_sha('refs/remotes/origin/main')
        result = writer.fetch_base('main')
        self.assertEqual(result['before_sha'], before)
        self.assertNotEqual(result['after_sha'], before)
        self.assertEqual(result['after_sha'], git(seed, 'rev-parse', 'HEAD').decode().strip())

    def test_stage_commit_and_push_round_trip(self):
        bare = make_bare(self.root)
        repo = make_repo(self.root, remote=bare)
        git(repo, 'push', 'origin', 'main')
        writer = GitWriter(repo)
        head = git(repo, 'rev-parse', 'HEAD').decode().strip()
        writer.create_branch('coopagents/task-2-1-ship', head)
        (repo / 'ship.py').write_text('print(1)\n', encoding='utf-8')
        delivered = writer.stage_and_commit('coopagents/task-2-1-ship', ['ship.py'],
                                            commit_message(2, 'Ship it'), 'Wei Chen', 'wei@example.com')
        self.assertNotEqual(delivered['head_sha'], head)
        author = git(repo, 'log', '-1', '--format=%an <%ae>').decode().strip()
        self.assertEqual(author, 'Wei Chen <wei@example.com>')
        pushed = writer.push_branch('coopagents/task-2-1-ship')
        self.assertTrue(pushed['pushed'])
        remote_head = git(bare, 'rev-parse', 'refs/heads/coopagents/task-2-1-ship').decode().strip()
        self.assertEqual(remote_head, delivered['head_sha'])

    def test_push_rejected_when_remote_moved(self):
        bare = make_bare(self.root)
        first = make_repo(self.root, remote=bare)
        git(first, 'push', 'origin', 'main')
        second = clone_repo(bare, self.root / 'second')
        head = git(first, 'rev-parse', 'HEAD').decode().strip()
        GitWriter(first).create_branch('coopagents/task-3-1-diverge', head)
        (first / 'a.py').write_text('a\n', encoding='utf-8')
        git(first, 'add', 'a.py')
        git(first, 'commit', '-m', 'a')
        GitWriter(first).push_branch('coopagents/task-3-1-diverge')
        GitWriter(second).create_branch('coopagents/task-3-1-diverge', head)
        (second / 'b.py').write_text('b\n', encoding='utf-8')
        git(second, 'add', 'b.py')
        git(second, 'commit', '-m', 'b')
        with self.assertRaises(ValidationError) as caught:
            GitWriter(second).push_branch('coopagents/task-3-1-diverge')
        self.assertIn('push was rejected', str(caught.exception))

    def test_commit_with_no_changes_is_a_noop_error(self):
        repo = make_repo(self.root)
        writer = GitWriter(repo)
        with self.assertRaises(ValidationError):
            writer.stage_and_commit('main', ['README.md'], commit_message(1, 'Nothing'),
                                    'A', 'a@example.com')


class BranchRecordingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / str(uuid4())
        self.root.mkdir(parents=True)
        self.identity = IdentityStore(self.root / 'git-write.sqlite3')
        self.owner = self.identity.create_room('Team', 'Owner')
        self.member = self.identity.add_member(self.owner['web_token'], 'Member')
        self.other = self.identity.add_member(self.owner['web_token'], 'Other')
        self.repositories = RepositoryStore(self.identity)
        self.repositories.bind_repository(self.owner['web_token'], 'github.com/acme/demo')
        self.tasks = TaskStore(self.identity)
        self.task = self.tasks.create_task(self.owner['web_token'], 'task', 'Build Login', 'src')
        self.tasks.claim_task(self.member['agent_token'], self.task['id'], session_key='s1')

    def enable(self):
        return self.repositories.set_git_write_enabled(self.owner['web_token'], True)

    def record(self, **overrides):
        args = {'token': self.member['agent_token'], 'task_id': self.task['id'],
                'branch': 'coopagents/task-%d-1-build-login' % self.task['id'],
                'base_sha': 'a' * 40, 'request_key': 'r1',
                'session_key': 's1', 'ownership_epoch': 1}
        args.update(overrides)
        return self.repositories.record_branch(**args)

    def test_flag_defaults_off_and_requires_manager_and_binding(self):
        self.assertFalse(self.repositories.git_write_enabled_for_room(self.owner['room_id']))
        with self.assertRaises(Conflict):
            self.record()
        with self.assertRaises(AccessDenied):
            self.repositories.set_git_write_enabled(self.member['web_token'], True)
        self.enable()
        self.assertTrue(self.repositories.git_write_enabled_for_room(self.owner['room_id']))
        with self.assertRaises(ValidationError):
            self.repositories.set_git_write_enabled(self.owner['web_token'], 'yes')

    def test_record_branch_happy_path_and_idempotency(self):
        self.enable()
        first = self.record()
        self.assertEqual(first['branch'], 'coopagents/task-%d-1-build-login' % self.task['id'])
        self.assertEqual(first['base_sha'], 'a' * 40)
        self.assertEqual(first['ownership_epoch'], 1)
        again = self.record(request_key='r2')
        self.assertEqual(again['id'], first['id'])
        with self.assertRaises(Conflict):
            self.record(base_sha='b' * 40, request_key='r4')

    def test_record_branch_rejects_wrong_name_ownership_and_preview_writes(self):
        self.enable()
        with self.assertRaises(ValidationError):
            self.record(branch='feature/login')
        with self.assertRaises(ValidationError):
            self.record(branch='coopagents/task-%d-1-build-login; rm' % self.task['id'])
        with self.assertRaises(ValidationError):
            self.record(base_sha='xyz')
        with self.assertRaises(AccessDenied):
            self.record(token=self.other['agent_token'])
        with self.assertRaises(Conflict):
            self.record(ownership_epoch=99)
        preview = self.record(preview=True)
        self.assertTrue(preview['preview'])
        self.assertIsNone(self.repositories.get_branch(self.member['agent_token'], self.task['id'],
                                                         session_key='s1', ownership_epoch=1))

    def test_snapshot_reports_flag_and_branches(self):
        self.enable()
        self.record()
        view = self.repositories.snapshot(self.member['agent_token'])
        self.assertTrue(view['git_write_enabled'])
        self.assertEqual(len(view['branches']), 1)
        self.assertEqual(view['branches'][0]['branch'], 'coopagents/task-%d-1-build-login' % self.task['id'])
        self.repositories.set_git_write_enabled(self.owner['web_token'], False)
        view = self.repositories.snapshot(self.member['agent_token'])
        self.assertFalse(view['git_write_enabled'])

    def test_flag_changes_are_audited(self):
        self.enable()
        self.repositories.set_git_write_enabled(self.owner['web_token'], False)
        with self.identity.db.connect() as c:
            rows = c.execute('SELECT action,member_id FROM git_write_audit ORDER BY id').fetchall()
        self.assertEqual([r['action'] for r in rows], ['flag_enabled', 'flag_disabled'])
        self.assertTrue(all(r['member_id'] == self.owner['member_id'] for r in rows))


class OverlapGateReadTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / str(uuid4())
        self.root.mkdir(parents=True)
        self.identity = IdentityStore(self.root / 'gate.sqlite3')
        self.owner = self.identity.create_room('Team', 'Owner')
        self.member = self.identity.add_member(self.owner['web_token'], 'Member')
        self.other = self.identity.add_member(self.owner['web_token'], 'Other')
        self.repositories = RepositoryStore(self.identity)
        self.repositories.bind_repository(self.owner['web_token'], 'github.com/acme/demo')
        self.tasks = TaskStore(self.identity)
        self.first = self.tasks.create_task(self.owner['web_token'], 'a', 'First', 'src')
        self.second = self.tasks.create_task(self.owner['web_token'], 'b', 'Second', 'src')
        self.tasks.claim_task(self.member['agent_token'], self.first['id'], session_key='s1')
        self.tasks.claim_task(self.other['agent_token'], self.second['id'], session_key='s2')

    def observe(self, token, task_id, paths, captured_at, session_key, workspace_id):
        return self.repositories.observe(token, task_id, {
            'request_key': 'k-' + str(uuid4()), 'workspace_id': workspace_id,
            'repository': 'github.com/acme/demo', 'branch': 'main', 'head': 'a' * 40,
            'paths': paths, 'captured_at': captured_at}, session_key=session_key, ownership_epoch=1)

    def test_fresh_cross_task_overlap_is_reported_and_stale_is_not(self):
        from datetime import timedelta
        fresh = now().isoformat()
        stale = (now() - timedelta(minutes=10)).isoformat()
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh, 's2', 'workspace-second-111')
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], stale, 's1', 'workspace-first-1111')
        with self.identity.db.connect() as c:
            conflicts = self.repositories.overlap_conflicts(c, self.owner['room_id'], self.first['id'], ['src/shared.py', 'src/own.py'])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]['task_id'], self.second['id'])
        self.assertEqual(conflicts[0]['member_id'], self.other['member_id'])
        self.assertEqual(conflicts[0]['paths'], ['src/shared.py'])
        with self.identity.db.connect() as c:
            self.assertEqual(self.repositories.overlap_conflicts(c, self.owner['room_id'], self.first['id'], ['src/own.py']), [])
            self.assertEqual(self.repositories.overlap_conflicts(c, self.owner['room_id'], self.first['id'], []), [])

    def test_superseded_observation_does_not_block(self):
        from datetime import timedelta
        old = (now() - timedelta(minutes=2)).isoformat()
        new = now().isoformat()
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], old, 's2', 'workspace-second-222')
        self.observe(self.other['agent_token'], self.second['id'], ['src/other.py'], new, 's2', 'workspace-second-222')
        with self.identity.db.connect() as c:
            self.assertEqual(self.repositories.overlap_conflicts(c, self.owner['room_id'], self.first['id'], ['src/shared.py']), [])


if __name__ == '__main__':
    unittest.main()
