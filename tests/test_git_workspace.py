import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents.errors import ValidationError


def api():
    from coopagents.git_workspace import GitWorkspace, load_project, normalize_repository
    return GitWorkspace, load_project, normalize_repository


def git(path, *args, data=None):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull,
                             '-C', str(path), *args], input=data, capture_output=True,
                            env=env, timeout=15, check=True)
    return result.stdout


class RepositoryNormalizationTests(unittest.TestCase):
    def test_secure_repository_forms_share_one_identity(self):
        normalize = api()[2]
        for value in ('github.com/Owner/Repo', 'https://GitHub.com/Owner/Repo.git',
                      'git@github.com:Owner/Repo.git', 'ssh://git@github.com/Owner/Repo.git'):
            self.assertEqual('github.com/owner/repo', normalize(value))
        self.assertEqual('gitlab.com/group/nested/repo',
                         normalize('https://gitlab.com/group/nested/repo.git'))

    def test_credentials_and_ambiguous_repository_values_are_rejected(self):
        normalize = api()[2]
        values = ('https://token@github.com/o/r', 'https://u:p@github.com/o/r',
                  'https://github.com/o/r?secret=x', 'https://github.com/o/r#x',
                  'file:///tmp/repo', 'C:/repo', '../repo', '/tmp/repo',
                  'http://github.com/o/r', 'github.com/o/../r',
                  'github.com/o/%2e%2e', 'https://localhost/o/r',
                  'https://github.com:443/o/r', 'git@github.com:/o/r',
                  'github.com/o/r\n', 'github.com/o/r\\x', '', None)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValidationError) as raised:
                normalize(value)
            self.assertNotIn('secret', str(raised.exception))


class GitWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence/git-workspace') / str(uuid4())
        self.root.mkdir(parents=True)
        self.repo = self.root / 'source repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-b', 'main')
        git(self.repo, 'config', 'user.name', 'Fixture')
        git(self.repo, 'config', 'user.email', 'fixture@example.invalid')
        git(self.repo, 'remote', 'add', 'origin', 'https://github.com/Owner/Repo.git')

    def commit(self):
        git(self.repo, 'add', '--all')
        git(self.repo, 'commit', '-m', 'fixture')

    def inspect(self, path=None, **kwargs):
        return api()[0](path or self.repo).inspect(**kwargs)

    def test_tracked_staged_unstaged_and_optional_untracked_paths(self):
        (self.repo / '.gitignore').write_text('ignored*\n')
        (self.repo / 'space name.txt').write_text('baseline')
        (self.repo / 'tracked.txt').write_text('baseline')
        self.commit()
        (self.repo / 'space name.txt').write_text('changed')
        (self.repo / 'staged.txt').write_text('new tracked')
        git(self.repo, 'add', 'staged.txt')
        (self.repo / 'untracked.txt').write_text('local')
        (self.repo / 'ignored.secret').write_text('secret')
        result = self.inspect()
        self.assertEqual(['space name.txt', 'staged.txt'], result['paths'])
        self.assertEqual(['space name.txt', 'staged.txt', 'untracked.txt'],
                         self.inspect(include_untracked=True)['paths'])
        self.assertEqual('github.com/owner/repo', result['repository'])
        self.assertEqual('main', result['branch'])
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD').decode().strip(), result['head'])
        self.assertRegex(result['captured_at'], r'^\d{4}-\d{2}-\d{2}T.+(?:Z|\+00:00)$')
        self.assertRegex(result['workspace_id'], r'^[a-zA-Z0-9_-]{20,}$')
        self.assertNotIn(str(self.repo.resolve()), json.dumps(result))

    def test_rename_contains_old_and_new_paths(self):
        (self.repo / 'old space.txt').write_text('unchanged')
        self.commit()
        git(self.repo, 'mv', 'old space.txt', 'new space.txt')
        self.assertEqual(['new space.txt', 'old space.txt'], self.inspect()['paths'])

    def test_tracked_files_stay_visible_under_ignore_rules_and_index_removal(self):
        (self.repo / 'tracked.txt').write_text('baseline')
        (self.repo / 'retained.txt').write_text('baseline')
        self.commit()
        (self.repo / '.gitignore').write_text('tracked.txt\n')
        (self.repo / 'tracked.txt').write_text('changed')
        # Keep the file on disk; remove only its tracked index entry.
        git(self.repo, 'update-index', '--force-remove', 'retained.txt')
        self.assertEqual(['retained.txt', 'tracked.txt'], self.inspect()['paths'])
        self.assertTrue((self.repo / 'retained.txt').exists())

    def test_newline_paths_are_not_split(self):
        # Windows cannot create this file; the real Git index can represent it.
        git(self.repo, 'config', 'core.protectNTFS', 'false')
        blob = git(self.repo, 'hash-object', '-w', '--stdin', data=b'fixture').strip()
        git(self.repo, 'update-index', '-z', '--index-info',
            data=b'100644 ' + blob + b'\tline\nbreak.txt\0')
        self.assertEqual(['line\nbreak.txt'], self.inspect()['paths'])

    def test_two_clones_have_different_local_workspace_ids(self):
        (self.repo / 'file').write_text('fixture')
        self.commit()
        snapshots = []
        for name in ('clone one', 'clone two'):
            clone = self.root / name
            git(self.root, 'clone', str(self.repo.resolve()), str(clone.resolve()))
            git(clone, 'remote', 'set-url', 'origin', 'git@github.com:Owner/Repo.git')
            snapshots.append(self.inspect(clone))
        self.assertEqual(snapshots[0]['repository'], snapshots[1]['repository'])
        self.assertEqual(snapshots[0]['head'], snapshots[1]['head'])
        self.assertNotEqual(snapshots[0]['workspace_id'], snapshots[1]['workspace_id'])

    def test_subdirectory_and_linked_worktree_identity(self):
        (self.repo / 'nested').mkdir()
        (self.repo / 'nested' / 'tracked.txt').write_text('fixture')
        self.commit()
        base = self.inspect()
        self.assertEqual(base['workspace_id'], self.inspect(self.repo / 'nested')['workspace_id'])
        linked = self.root / 'linked worktree'
        git(self.repo, 'worktree', 'add', '-b', 'feature', str(linked.resolve()))
        result = self.inspect(linked)
        self.assertEqual('feature', result['branch'])
        self.assertNotEqual(base['workspace_id'], result['workspace_id'])
        self.assertEqual(base['head'], result['head'])

    def test_root_is_read_only_and_resolves_the_true_worktree(self):
        (self.repo / 'nested').mkdir()
        workspace = api()[0](self.repo / 'nested')
        self.assertEqual(self.repo.resolve(), workspace.root)
        with self.assertRaises(AttributeError):
            workspace.root = self.root

    def test_detached_and_unborn_branches(self):
        self.assertEqual('', self.inspect()['head'])
        self.assertEqual('main', self.inspect()['branch'])
        (self.repo / 'file').write_text('fixture')
        self.commit()
        git(self.repo, 'checkout', '--detach')
        self.assertEqual('', self.inspect()['branch'])
        self.assertNotEqual('', self.inspect()['head'])

    def test_credentials_are_redacted_from_origin(self):
        git(self.repo, 'remote', 'set-url', 'origin',
            'https://user:secret-token@github.com/Owner/Repo.git')
        result = self.inspect()
        self.assertEqual('github.com/owner/repo', result['repository'])
        self.assertNotIn('secret-token', json.dumps(result))

    def test_invalid_remote_error_does_not_include_credentials(self):
        git(self.repo, 'remote', 'set-url', 'origin',
            'https://user:secret-token@github.com/Owner/Repo.git?token=secret-token')
        with self.assertRaises(ValidationError) as raised:
            self.inspect()
        self.assertNotIn('secret-token', str(raised.exception))

    def test_inherited_git_environment_does_not_redirect_inspection(self):
        with patch.dict(os.environ, {'GIT_DIR': str(self.root / 'invalid'),
                                     'GIT_WORK_TREE': str(self.root),
                                     'GIT_INDEX_FILE': str(self.root / 'fake-index'),
                                     'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'remote.origin.url',
                                     'GIT_CONFIG_VALUE_0': 'https://secret@bad.invalid/o/r'}):
            self.assertEqual('github.com/owner/repo', self.inspect()['repository'])

    def test_no_origin_and_non_repository_fail_safely(self):
        git(self.repo, 'remote', 'remove', 'origin')
        nonrepo = self.root / 'non-repository'
        nonrepo.mkdir()
        (nonrepo / '.git').write_text('gitdir: absent-git-directory\n')
        for path in (self.repo, nonrepo, self.root / 'missing'):
            with self.subTest(path=path), self.assertRaises(ValidationError) as raised:
                self.inspect(path)
            self.assertNotIn(str(self.root), str(raised.exception))

    def test_fsmonitor_executable_is_never_run(self):
        marker = self.root / 'hook-ran'
        git(self.repo, 'config', 'core.fsmonitor', 'echo unexpected > ' + str(marker.resolve()))
        self.inspect()
        self.assertFalse(marker.exists())

    def test_subprocess_output_and_time_are_bounded(self):
        module = __import__('coopagents.git_workspace', fromlist=['GitWorkspace'])
        with patch.object(module, 'MAX_GIT_OUTPUT', 8):
            with self.assertRaises(ValidationError):
                self.inspect()
        with patch.object(module, 'GIT_TIMEOUT', 0):
            with self.assertRaises(ValidationError):
                self.inspect()


class ProjectConfigTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence/git-project') / str(uuid4())
        (self.root / '.coopagents').mkdir(parents=True)
        self.config = self.root / '.coopagents' / 'project.json'
        self.valid = {'schema_version': 1, 'project_ref': str(uuid4()),
                      'repository': 'github.com/owner/repo'}

    def write(self, value):
        self.config.write_text(json.dumps(value), encoding='utf-8')

    def test_loads_only_versioned_data_config(self):
        self.write(self.valid)
        self.assertEqual(self.valid, api()[1](self.root))

    def test_missing_invalid_and_executable_config_rejected(self):
        with self.assertRaises(ValidationError):
            api()[1](self.root)
        variants = [[], {}, {**self.valid, 'schema_version': True},
                    {**self.valid, 'schema_version': 2}, {**self.valid, 'project_ref': 'bad'},
                    {**self.valid, 'repository': 'https://github.com/owner/repo'},
                    {**self.valid, 'endpoint': 'https://evil.invalid'},
                    {**self.valid, 'rules': {'command': 'echo execute'}},
                    {**self.valid, 'repository': 'https://secret@github.com/o/r'}]
        for value in variants:
            self.write(value)
            with self.subTest(value=value), self.assertRaises(ValidationError):
                api()[1](self.root)
        self.config.write_text('{invalid', encoding='utf-8')
        with self.assertRaises(ValidationError):
            api()[1](self.root)

    def test_config_size_and_duplicate_keys_are_rejected(self):
        self.config.write_text(' ' * 70000, encoding='utf-8')
        with self.assertRaises(ValidationError):
            api()[1](self.root)
        self.config.write_text('[' * 20000 + '0' + ']' * 20000, encoding='utf-8')
        with self.assertRaises(ValidationError):
            api()[1](self.root)
        self.config.write_text(json.dumps(self.valid)[:-1] + ',"schema_version":1}', encoding='utf-8')
        with self.assertRaises(ValidationError):
            api()[1](self.root)


class GitWorkspaceAvailabilityTests(unittest.TestCase):
    def test_local_git_workspace_inspector_is_available(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.git_workspace'))
