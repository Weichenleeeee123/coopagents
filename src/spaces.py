"""Private agent-hosted space state. Files and historical versions are retained."""
import json
import os
from pathlib import Path
import subprocess
import stat
from urllib.parse import urlsplit
from uuid import uuid4

from .config import public_origin


def validate_origin(value):
    if not isinstance(value, str):
        raise ValueError('Origin must be a string')
    parsed = urlsplit(value)
    if parsed.scheme == 'https':
        return public_origin(value)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or not port or parsed.username or parsed.password or parsed.path
            or parsed.query or parsed.fragment or any(c.isspace() for c in value)
            or '\\' in value or '?' in value or '#' in value):
        raise ValueError('Origin must be HTTPS or explicit loopback HTTP')
    return value


def checked_path(value):
    if '..' in Path(value).parts:
        raise ValueError('State paths must not escape their directory')
    path = Path(value).absolute()
    for item in (path, *path.parents):
        try:
            metadata = os.lstat(item)
        except FileNotFoundError:
            continue
        # lstat's Windows attributes are available on every supported Python,
        # including 3.11 where pathlib has no junction detection. Fail closed
        # for all reparse points rather than following an unfamiliar tag.
        if (stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, 'st_file_attributes', 0) & 0x400
                or getattr(metadata, 'st_reparse_tag', 0)):
            raise ValueError('State paths must not contain links')
    return path


def private_directory(value):
    path = checked_path(value)
    # A tracked checkout must use its explicitly ignored local state directory.
    for parent in (path, *path.parents):
        if (parent / '.git').exists():
            if '.local' not in path.relative_to(parent).parts:
                raise ValueError('Repository state must be inside .local')
            break
    path.mkdir(parents=True, exist_ok=True)
    protect(path, directory=True)
    return path


def protect(path, directory=False):
    if os.name == 'nt':
        # Restrict the private state to the current account and SYSTEM. Never
        # inherit a checkout's potentially shared ACL for credential files.
        account = subprocess.run(['whoami'], capture_output=True, text=True, check=True).stdout.strip()
        permission = '(OI)(CI)F' if directory else 'F'
        reset = subprocess.run(['icacls', str(path), '/reset'], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        if reset.returncode:
            raise ValueError('Private state permissions could not be reset')
        result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                                 account + ':' + permission, '*S-1-5-18:' + permission],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError('Private state permissions could not be applied')
    else:
        path.chmod(0o700 if directory else 0o600)


def private_write(value, document, *, update=False):
    path = checked_path(value)
    private_directory(path.parent)
    encoded = (json.dumps(document, ensure_ascii=True, indent=2) + '\n').encode('utf-8')
    if path.exists() and not update:
        raise FileExistsError('Private state already exists')
    staging = path.with_name(path.name + '.' + uuid4().hex + '.pending')
    with staging.open('xb') as stream:
        protect(staging)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    if path.exists():
        # Preserve the previous credential state before the atomic replacement.
        history = path.with_name(path.name + '.' + uuid4().hex + '.history')
        with history.open('xb') as stream:
            protect(history)
            stream.write(path.read_bytes())
    elif update:
        raise ValueError('Cannot update absent private state')
    if update:
        os.replace(staging, path)
    else:
        # Atomic exclusive publication cannot replace a concurrent creator's
        # profile. Retain the staging hardlink as private evidence.
        os.link(staging, path)


def read_json(value):
    path = checked_path(value)
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Private state could not be read')
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict) or result.get('schema_version') != 1:
        raise ValueError('Unsupported private state schema')
    return result


def read_profile(value):
    result = read_json(value)
    for key in ('origin', 'room_id', 'member_id', 'agent_token'):
        if not isinstance(result.get(key), str) or not result[key]:
            raise ValueError('Incomplete personal profile')
    if 'web_token' in result and (not isinstance(result['web_token'], str) or not result['web_token']):
        raise ValueError('Invalid optional web credential')
    validate_origin(result['origin'])
    if 'p2p' in result:
        from .p2p import validate_link
        validate_link(result['p2p'])
        if urlsplit(result['origin']).hostname != '127.0.0.1':
            raise ValueError('Peer-to-peer profiles use a loopback origin')
    if 'control_origin' in result or 'control_token' in result:
        validate_origin(result.get('control_origin'))
        if urlsplit(result['control_origin']).hostname not in ('127.0.0.1', 'localhost') or not result.get('control_token'):
            raise ValueError('Invalid owner control state')
    return result


def safe_profile(profile, path):
    return {key: profile[key] for key in ('origin', 'room_id', 'member_id')} | {'profile': str(checked_path(path))}
