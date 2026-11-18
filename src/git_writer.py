"""Allowlisted local Git writes for spaces that opted into the git write path.

The shared service never runs git. This module runs only on the member's own
machine, through the local adapter. Every command is built from validated
parts against a fixed verb allowlist: fetch (one fixed refspec), checkout -b,
add (explicit paths only), commit (message via a bounded temp file), and plain
push. There is no force-push, no history rewrite, no destructive operation, no
shell, and no hooks.

Push authentication uses the member's own existing git credential setup, so
unlike the read-only inspector this runner keeps the user's git configuration
files and only strips GIT_* environment overrides (which could inject
configuration). Commit authorship is passed per invocation and never rewrites
the user's global git config. File contents are never read here: staging uses
path lists only, and commit messages are agent-supplied summaries.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import threading

from .errors import Conflict, ValidationError
from .git_workspace import GitWorkspace, _git, branch_name, validate_relative_paths
from .github_app import complete_sha


GIT_WRITE_TIMEOUT = 60
MAX_GIT_WRITE_OUTPUT = 4 * 1024 * 1024
MAX_COMMIT_MESSAGE = 2000
MAX_SUMMARY = 1000


def _write_env():
    # Strip GIT_* overrides (including numbered config injection) but keep the
    # user's configuration files: credential helpers and identity live there.
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith('GIT_')}
    env['GIT_TERMINAL_PROMPT'] = '0'
    return env


def _run(command, env):
    """Bounded subprocess run with stdout capped and stderr discarded (no leaks)."""
    output = bytearray()
    overflow = threading.Event()
    try:
        process = subprocess.Popen(command, env=env, shell=False,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
    except OSError:
        raise ValidationError('Git write could not start') from None

    def drain():
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                return
            if len(output) + len(chunk) > MAX_GIT_WRITE_OUTPUT:
                overflow.set()
                try:
                    process.kill()
                except OSError:
                    pass
                return
            output.extend(chunk)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        process.wait(timeout=GIT_WRITE_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        reader.join()
        raise ValidationError('Git write exceeded its time limit') from None
    finally:
        reader.join()
        process.stdout.close()
    if overflow.is_set():
        raise ValidationError('Git write exceeded its output limit')
    return bytes(output), process.returncode


def _author_name(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 200
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or value.startswith('-') or value != value.strip()):
        raise ValidationError('Expected a commit author name')
    return value


def _author_email(value):
    if (not isinstance(value, str) or not 3 <= len(value) <= 254
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
            or value.count('@') != 1 or value.startswith(('@', '-')) or value.endswith('@')):
        raise ValidationError('Expected a commit author email')
    local, domain = value.split('@')
    if not local or not domain or '.' not in domain:
        raise ValidationError('Expected a commit author email')
    return value


def commit_message(task_id, summary):
    """Template: first line carries the task id and a one-line summary."""
    if type(task_id) is not int or not 0 < task_id < 2**63:
        raise ValidationError('Expected a positive task identifier')
    if not isinstance(summary, str):
        raise ValidationError('Expected a delivery summary')
    line = ' '.join(summary.split())
    if not 1 <= len(line) <= MAX_SUMMARY:
        raise ValidationError('Delivery summary must contain 1 to 1000 characters')
    message = f'Task {task_id}: {line}\n\nCoopagents-task: {task_id}\n'
    if len(message.encode()) > MAX_COMMIT_MESSAGE:
        raise ValidationError('Commit message exceeds its size limit')
    return message


def find_secret_paths(paths):
    """Path-name-only secret scan; contents are never read (draft section 7a).

    All comparisons are case-insensitive: filesystems and tools differ in
    case handling, and a guard that `.ENV` slips past is no guard.
    """
    offenders = []
    for path in paths:
        parts = [part.lower() for part in path.split('/')]
        name = parts[-1]
        if (parts[0] in ('.coopagents', '.ssh')
                or name == '.env' or name.startswith('.env.')
                or name.endswith(('.pem', '.key'))
                or name.startswith('credentials')
                or name.startswith('id_rsa')
                or any('secret' in part for part in parts)):
            offenders.append(path)
    return offenders


class GitWriter:
    """Execute the allowlisted write verbs in one local worktree."""

    def __init__(self, path, *, runner=None):
        self.workspace = GitWorkspace(path)
        self._runner = runner

    @property
    def root(self):
        return self.workspace.root

    def _read(self, *arguments, allowed=(0,)):
        return _git(self.root, *arguments, allowed=allowed)

    def _command(self, *arguments, author=None):
        command = ['git', '--no-pager', '-c', 'core.fsmonitor=false',
                   '-c', 'core.hooksPath=' + os.devnull, '-c', 'status.renames=true',
                   '-C', str(self.root)]
        if author is not None:
            name, email = author
            command += ['-c', 'user.name=' + name, '-c', 'user.email=' + email]
        return command + list(arguments)

    def _execute(self, arguments, *, error, author=None):
        command = self._command(*arguments, author=author)
        runner = self._runner or _run
        _, code = runner(command, _write_env())
        if code != 0:
            raise ValidationError(error)
        return command

    def current_branch(self):
        data, code = self._read('symbolic-ref', '--quiet', '--short', 'HEAD', allowed=(0, 1))
        return data.decode('utf-8', 'surrogateescape').strip() if code == 0 else ''

    def head_sha(self):
        data, code = self._read('rev-parse', '--verify', '--quiet', 'HEAD', allowed=(0, 1))
        return data.decode('utf-8', 'surrogateescape').strip() if code == 0 else ''

    def ref_sha(self, ref):
        if not isinstance(ref, str) or not ref or any(ord(char) < 33 for char in ref) or '..' in ref:
            raise ValidationError('Expected a safe Git reference')
        data, code = self._read('rev-parse', '--verify', '--quiet', ref, allowed=(0, 1))
        return data.decode('utf-8', 'surrogateescape').strip() if code == 0 else ''

    def default_branch(self):
        """The remote default branch from origin/HEAD; never guessed."""
        data, code = self._read('symbolic-ref', '--quiet', 'refs/remotes/origin/HEAD', allowed=(0, 1))
        if code != 0:
            raise ValidationError('Remote default branch is unknown; set origin/HEAD first')
        ref = data.decode('utf-8', 'surrogateescape').strip()
        prefix = 'refs/remotes/origin/'
        if not ref.startswith(prefix):
            raise ValidationError('Remote default branch is unknown; set origin/HEAD first')
        return branch_name(ref[len(prefix):])

    def fetch_base(self, default_branch, *, preview=False):
        """Narrow fetch: one fixed refspec, no tags, no prune, no --all (D5)."""
        branch_name(default_branch)
        ref = 'refs/remotes/origin/' + default_branch
        before = self.ref_sha(ref)
        arguments = ['fetch', '--no-tags', 'origin', default_branch + ':' + ref]
        if preview:
            return {'preview': True, 'commands': [self._command(*arguments)],
                    'default_branch': default_branch, 'before_sha': before}
        self._execute(arguments, error='Git fetch failed')
        return {'default_branch': default_branch, 'before_sha': before, 'after_sha': self.ref_sha(ref)}

    def create_branch(self, branch, base_sha, *, preview=False):
        """Create and check out a task branch at a recorded base SHA (W1)."""
        branch_name(branch)
        complete_sha(base_sha)
        existing = self.ref_sha('refs/heads/' + branch)
        if existing:
            if existing == base_sha:
                return {'branch': branch, 'base_sha': base_sha, 'reused': True}
            raise Conflict('Task branch already exists from a different base')
        arguments = ['checkout', '-b', branch, base_sha]
        if preview:
            return {'preview': True, 'commands': [self._command(*arguments)],
                    'branch': branch, 'base_sha': base_sha, 'reused': False}
        self._execute(arguments, error='Git branch creation failed')
        return {'branch': branch, 'base_sha': base_sha, 'reused': False}

    def stage_and_commit(self, branch, paths, message, author_name, author_email, *, preview=False):
        """Stage exactly the given paths and commit with per-invocation authorship (W2)."""
        branch_name(branch)
        paths = validate_relative_paths(paths)
        if not paths:
            raise ValidationError('No paths to deliver')
        offenders = find_secret_paths(paths)
        if offenders:
            raise ValidationError('Secret-shaped paths cannot be staged: ' + ', '.join(offenders[:10]))
        if not isinstance(message, str) or not 1 <= len(message.encode()) <= MAX_COMMIT_MESSAGE:
            raise ValidationError('Commit message exceeds its size limit')
        name = _author_name(author_name)
        email = _author_email(author_email)
        if self.current_branch() != branch:
            raise Conflict('Task branch is not checked out')
        add = self._command('add', '--', *paths)
        if preview:
            return {'preview': True, 'commands': [add, self._command('commit', '-F', '<message-file>', author=(name, email))],
                    'branch': branch, 'paths': paths, 'message': message}
        self._execute(['add', '--', *paths], error='Git staging failed')
        _, staged = self._read('diff', '--cached', '--quiet', allowed=(0, 1))
        if staged == 0:
            raise ValidationError('No staged changes to commit')
        handle = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='coopagents-commit-',
                                             suffix='.txt', delete=False)
        try:
            handle.write(message)
            handle.close()
            self._execute(['commit', '-F', handle.name], author=(name, email),
                          error='Git commit failed')
        finally:
            try:
                Path(handle.name).unlink()
            except OSError:
                pass
        return {'branch': branch, 'head_sha': self.head_sha(), 'paths': paths}

    def push_branch(self, branch, *, preview=False):
        """Plain push only; force variants cannot be constructed (D2)."""
        branch_name(branch)
        arguments = ['push', 'origin', branch]
        if preview:
            return {'preview': True, 'commands': [self._command(*arguments)], 'branch': branch}
        self._execute(arguments, error='Git push was rejected; the remote branch moved or the push was not allowed')
        return {'branch': branch, 'pushed': True}
