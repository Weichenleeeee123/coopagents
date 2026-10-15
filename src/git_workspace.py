"""Read-only local Git evidence and a strictly data-only project configuration."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import urlsplit
from uuid import UUID

from .errors import ValidationError


GIT_TIMEOUT = 10
MAX_GIT_OUTPUT = 4 * 1024 * 1024
MAX_PROJECT_BYTES = 64 * 1024
_HOST = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+'
                   r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
_COMPONENT = re.compile(r'[a-z0-9_.-]+\Z')


def normalize_repository(value):
    """Canonicalize a secure remote identity; reject credentials and local paths."""
    invalid = ValidationError('Invalid repository identity')
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise invalid
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise invalid
    if any(char in value for char in '\\%?#'):
        raise invalid
    value = value.lower()
    if value.startswith('git@'):
        match = re.fullmatch(r'git@([^:]+):([^/].*)', value)
        if not match:
            raise invalid
        host, path = match.groups()
    elif '://' in value:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in ('https', 'ssh') or parsed.port is not None:
                raise invalid
            if parsed.password is not None or (parsed.username is not None and
                                               not (parsed.scheme == 'ssh' and parsed.username == 'git')):
                raise invalid
            host, path = parsed.hostname or '', parsed.path.removeprefix('/')
        except ValueError:
            raise invalid from None
    else:
        host, separator, path = value.partition('/')
        if not separator:
            raise invalid
    if not _HOST.fullmatch(host):
        raise invalid
    if path.endswith('.git'):
        path = path[:-4]
    components = path.split('/')
    if len(components) < 2 or (host == 'github.com' and len(components) != 2):
        raise invalid
    if any(part in ('.', '..') or not _COMPONENT.fullmatch(part) for part in components):
        raise invalid
    return host + '/' + '/'.join(components)


def _remote_identity(remote):
    """Discard HTTPS authentication before producing any externally visible value."""
    if remote.lower().startswith('https://'):
        try:
            parsed = urlsplit(remote)
            remote = 'https://' + parsed.netloc.rsplit('@', 1)[-1] + parsed.path
            if parsed.query or parsed.fragment or '?' in parsed.geturl() or '#' in parsed.geturl():
                raise ValidationError('Invalid repository identity')
        except ValueError:
            raise ValidationError('Invalid repository identity') from None
    return normalize_repository(remote)


def _git(path, *arguments, allowed=(0,)):
    # Strip all Git environment overrides, including numbered config injection.
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    command = ['git', '--no-pager', '-c', 'core.fsmonitor=false',
               '-c', 'core.hooksPath=' + os.devnull, '-c', 'status.renames=true',
               '-C', str(path), *arguments]
    output = bytearray()
    overflow = threading.Event()
    try:
        process = subprocess.Popen(command, env=env, shell=False,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
    except OSError:
        raise ValidationError('Git workspace could not be inspected') from None

    def drain():
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                return
            if len(output) + len(chunk) > MAX_GIT_OUTPUT:
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
        process.wait(timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        reader.join()
        raise ValidationError('Git inspection exceeded its time limit') from None
    finally:
        reader.join()
        process.stdout.close()
    if overflow.is_set():
        raise ValidationError('Git inspection exceeded its output limit')
    if process.returncode not in allowed:
        raise ValidationError('Git workspace could not be inspected')
    return bytes(output), process.returncode


def _line(data):
    return data.removesuffix(b'\n').removesuffix(b'\r').decode('utf-8', 'surrogateescape')


def _changed_paths(data):
    paths = set()
    fields = data.split(b'\0')
    index = 0
    while index < len(fields) and fields[index]:
        item = fields[index]
        if len(item) < 4 or item[2:3] != b' ':
            raise ValidationError('Invalid Git status evidence')
        status = item[:2]
        paths.add(item[3:].decode('utf-8', 'surrogateescape'))
        index += 1
        if b'R' in status or b'C' in status:
            if index >= len(fields) or not fields[index]:
                raise ValidationError('Invalid Git status evidence')
            paths.add(fields[index].decode('utf-8', 'surrogateescape'))
            index += 1
    return sorted(paths)


class GitWorkspace:
    """Inspect a repository or any subdirectory without publishing its local path."""

    def __init__(self, path):
        try:
            self.path = Path(path).resolve(strict=True)
        except (OSError, ValueError, TypeError):
            raise ValidationError('Invalid Git workspace') from None
        if not self.path.is_dir():
            raise ValidationError('Invalid Git workspace')

    @property
    def root(self):
        """The real worktree root for local configuration access only."""
        root_data, _ = _git(self.path, 'rev-parse', '--show-toplevel')
        try:
            return Path(_line(root_data)).resolve(strict=True)
        except (OSError, ValueError):
            raise ValidationError('Invalid Git workspace') from None

    def inspect(self, include_untracked=False):
        if not isinstance(include_untracked, bool):
            raise ValidationError('Invalid untracked option')
        root = self.root
        remote, _ = _git(root, 'config', '--get', 'remote.origin.url')
        repository = _remote_identity(_line(remote))
        branch, branch_code = _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD', allowed=(0, 1))
        head, head_code = _git(root, 'rev-parse', '--verify', '--quiet', 'HEAD', allowed=(0, 1))
        status, _ = _git(root, 'status', '--porcelain=v1', '-z', '--no-ahead-behind',
                         '--untracked-files=' + ('all' if include_untracked else 'no'))
        identity = os.path.normcase(str(root)).encode('utf-8', 'surrogateescape')
        return {'repository': repository,
                'branch': _line(branch) if branch_code == 0 else '',
                'head': _line(head) if head_code == 0 else '',
                'paths': _changed_paths(status),
                'captured_at': datetime.now(timezone.utc).isoformat(),
                'workspace_id': hashlib.sha256(identity).hexdigest()}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError('Invalid project configuration')
        result[key] = value
    return result


def load_project(path):
    """Read .coopagents/project.json; no endpoints, commands, or extensions allowed."""
    try:
        with (Path(path) / '.coopagents' / 'project.json').open('rb') as stream:
            data = stream.read(MAX_PROJECT_BYTES + 1)
        if len(data) > MAX_PROJECT_BYTES:
            raise ValidationError('Project configuration exceeded its size limit')
        config = json.loads(data.decode('utf-8'), object_pairs_hook=_unique_object)
    except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
        raise ValidationError('Invalid project configuration') from None
    if not isinstance(config, dict) or set(config) != {'schema_version', 'project_ref', 'repository'}:
        raise ValidationError('Invalid project configuration')
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ValidationError('Unsupported project configuration version')
    try:
        reference = config['project_ref']
        if not isinstance(reference, str) or str(UUID(reference)) != reference:
            raise ValueError
        if normalize_repository(config['repository']) != config['repository']:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Invalid project configuration') from None
    return config
