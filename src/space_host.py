"""Explicitly registered native owner connections may recover their own host."""
from contextlib import contextmanager
import os
import time

from .spaces import checked_path, private_write, protect, read_json, read_profile


def policy_path(profile_path):
    return checked_path(profile_path).with_name('native-host.json')


def policy(profile_path):
    path = policy_path(profile_path)
    if not path.exists():
        return None
    profile = read_profile(profile_path)
    document = read_json(path)
    if (not profile.get('control_token')
            or (document.get('room_id'), document.get('member_id')) != (profile['room_id'], profile['member_id'])):
        raise ValueError('Native host policy identity does not match its owner profile')
    if (set(document) != {'schema_version', 'room_id', 'member_id', 'desired_running', 'blocked'}
            or type(document.get('desired_running')) is not bool or type(document.get('blocked')) is not bool):
        raise ValueError('Invalid native host policy')
    return document


@contextmanager
def owner_lock(profile_path):
    """Serialize CLI intent changes and recovery across native processes."""
    path = checked_path(checked_path(profile_path).with_name('host-management.lock'))
    try:
        with path.open('xb') as stream:
            protect(path)
            stream.write(b'1')
    except FileExistsError:
        pass
    with path.open('r+b') as stream:
        deadline = time.monotonic() + 110
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Host management is busy; retry after the current operation') from None
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def register(profile_path):
    """Called only after explicit native connection registration succeeds."""
    profile = read_profile(profile_path)
    host_path = checked_path(profile_path).with_name('host.json')
    if not profile.get('control_token') or not host_path.exists():
        return {'enabled': False}
    if read_json(host_path).get('network') not in ('local', 'p2p'):
        return {'enabled': False}
    with owner_lock(profile_path):
        document = policy(profile_path)
        if document is None:
            document = dict(schema_version=1, room_id=profile['room_id'], member_id=profile['member_id'],
                            desired_running=True, blocked=False)
            private_write(policy_path(profile_path), document)
    return {'enabled': True, 'desired_running': document['desired_running'], 'blocked': document['blocked']}


def set_intent(profile_path, running):
    """Caller holds owner_lock. Never opt a legacy or member profile in."""
    document = policy(profile_path)
    if document is not None:
        document.update(desired_running=running, blocked=False)
        private_write(policy_path(profile_path), document, update=True)
    return document is not None


def ensure(profile_path):
    """Native MCP startup/reconnect only; diagnostics remain read-only."""
    if policy(profile_path) is None:
        return
    from . import space_runtime as runtime
    with owner_lock(profile_path):
        document = policy(profile_path)
        if not document['desired_running']:
            raise ValueError('The owner runtime was explicitly stopped; run start with this owner profile to resume')
        if runtime.status(profile_path)['status'] == 'running':
            return
        if document['blocked']:
            raise ValueError('Automatic host recovery failed; run start with this owner profile to retry explicitly')
        try:
            runtime._start(profile_path)
        except Exception:
            document['blocked'] = True
            private_write(policy_path(profile_path), document, update=True)
            raise ValueError('Automatic host recovery failed; run start with this owner profile to retry explicitly') from None
