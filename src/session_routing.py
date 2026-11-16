"""Reported native aliases and short watcher leases, never execution authority."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

from .activity import TOOLS
from .errors import AccessDenied, Conflict, ValidationError
from .identity import IdentityStore, _expired, _token_hash
from .tasks import _text

MAX_TTL_SECONDS = 300


def _same_tool(first, second):
    return first == second or first in ('codex-cli', 'codex-desktop') and second in ('codex-cli', 'codex-desktop')


def _now():
    return datetime.now(timezone.utc)


def native_key(value):
    value = _text(value, 'Native session key', 200)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValidationError('Native session key must not contain control characters')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise ValidationError('Native session key must contain valid Unicode') from None
    return value


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS session_presence (
        room_id TEXT NOT NULL, member_id TEXT NOT NULL, session_key TEXT NOT NULL,
        tool TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN('watching','stopped')),
        credential_hash TEXT NOT NULL, generation INTEGER NOT NULL,
        expires_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY(room_id,member_id,session_key),
        FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
        FOREIGN KEY(credential_hash) REFERENCES credentials(token_hash))''')
    db.execute('''CREATE TABLE IF NOT EXISTS task_session_routes (
        task_id INTEGER NOT NULL, room_id TEXT NOT NULL, member_id TEXT NOT NULL,
        logical_session_key TEXT NOT NULL, ownership_epoch INTEGER NOT NULL,
        native_session_key TEXT NOT NULL, tool TEXT NOT NULL, credential_hash TEXT NOT NULL,
        generation INTEGER NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY(task_id,ownership_epoch,logical_session_key),
        FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id),
        FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
        FOREIGN KEY(credential_hash) REFERENCES credentials(token_hash))''')


def _credential_active(db, credential_hash, member_id, room_id, now):
    row = db.execute('''SELECT c.kind,c.revoked_at,c.expires_at FROM credentials c
        JOIN members m ON m.id=c.member_id WHERE c.token_hash=? AND c.member_id=? AND m.room_id=?''',
        (credential_hash, member_id, room_id)).fetchone()
    if not row or row['kind'] != 'agent' or row['revoked_at'] or _expired(row['expires_at'], now):
        return False
    if IdentityStore._has_table(db, 'project_members'):
        membership = db.execute('''SELECT p.active,t.active AS team_active FROM project_members p
            JOIN team_projects r ON r.room_id=p.room_id
            JOIN team_members t ON t.team_id=r.team_id AND t.account_id=p.account_id
            WHERE p.member_id=?''', (member_id,)).fetchone()
        if membership and (not membership['active'] or not membership['team_active']):
            return False
        session = db.execute('''SELECT s.revoked_at,s.expires_at FROM session_project_credentials p
            JOIN account_sessions s ON s.token_hash=p.session_hash WHERE p.credential_hash=?''',
            (credential_hash,)).fetchone()
        if session and (session['revoked_at'] or _expired(session['expires_at'], now)):
            return False
    return True


def _presence_active(db, row, now):
    return bool(row and row['state'] == 'watching' and not _expired(row['expires_at'], now)
                and _credential_active(db, row['credential_hash'], row['member_id'], row['room_id'], now))


def _lease(db, binding):
    if not binding:
        return None
    return db.execute('''SELECT * FROM session_presence WHERE room_id=? AND member_id=? AND session_key=?''',
        (binding['room_id'], binding['member_id'], binding['native_session_key'])).fetchone()


def _binding_active(db, binding, now):
    if not binding:
        return False
    task = db.execute('SELECT * FROM tasks WHERE id=? AND room_id=?',
                      (binding['task_id'], binding['room_id'])).fetchone()
    if (not task or task['cancelled_at'] or task['state'] != 'claimed'
            or task['owner_member_id'] != binding['member_id']
            or task['execution_session_key'] != binding['logical_session_key']
            or task['ownership_epoch'] != binding['ownership_epoch']
            or not _credential_active(db, binding['credential_hash'], binding['member_id'], binding['room_id'], now)):
        return False
    presence = _lease(db, binding)
    return bool(_presence_active(db, presence, now) and _same_tool(presence['tool'], binding['tool'])
                and presence['credential_hash'] == binding['credential_hash'])


def bind_execution(db, principal, token, task, logical_session_key, tool, native_session_id=None):
    """Called only after execution_task validated the caller in this transaction."""
    digest, now = _token_hash(token), _now()
    previous = db.execute('''SELECT * FROM task_session_routes
        WHERE task_id=? AND ownership_epoch=? AND logical_session_key=?''',
        (task['id'], task['ownership_epoch'], logical_session_key)).fetchone()
    # A normal capability/session refresh may omit the alias. It must not
    # silently retarget an already reported current-execution binding.
    native = native_key(native_session_id if native_session_id is not None else
                        previous['native_session_key'] if previous else logical_session_key)
    changed = bool(previous and (previous['native_session_key'] != native
                   or not _same_tool(previous['tool'], tool) or previous['credential_hash'] != digest))
    if changed and _binding_active(db, previous, now):
        raise Conflict('Current execution is already bound to an active native session')
    generation = previous['generation'] + int(changed) if previous else 1
    db.execute('''INSERT INTO task_session_routes(task_id,room_id,member_id,logical_session_key,
        ownership_epoch,native_session_key,tool,credential_hash,generation,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id,ownership_epoch,logical_session_key)
        DO UPDATE SET native_session_key=excluded.native_session_key,tool=excluded.tool,
            credential_hash=excluded.credential_hash,generation=excluded.generation,updated_at=excluded.updated_at''',
        (task['id'], principal.room_id, principal.member_id, logical_session_key, task['ownership_epoch'],
         native, tool, digest, generation, now.isoformat()))


class SessionRoutingStore:
    def __init__(self, identity):
        self.identity, self.db = identity, identity.db
        with self.db.connect(write=True) as db:
            initialize(db)

    def presence(self, token, session_key, tool, state='watching', ttl_seconds=90):
        session_key = native_key(session_key)
        if tool not in TOOLS:
            raise ValidationError('Unsupported watcher tool')
        if state not in ('watching', 'stopped'):
            raise ValidationError('Watcher state must be watching or stopped')
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
            raise ValidationError('Watcher TTL must be an integer from 1 to 300 seconds')
        with self.db.connect(write=True) as db:
            p = self.identity.resolve(db, token, required_kind='agent')
            now, digest = _now(), _token_hash(token)
            previous = db.execute('''SELECT * FROM session_presence
                WHERE room_id=? AND member_id=? AND session_key=?''', (p.room_id, p.member_id, session_key)).fetchone()
            active = _presence_active(db, previous, now)
            if active and previous['credential_hash'] != digest:
                raise AccessDenied('Active native presence belongs to another agent credential')
            if active and not _same_tool(previous['tool'], tool):
                raise Conflict('Active native presence belongs to another coding agent tool')
            same_lease = bool(previous and previous['state'] == state and _same_tool(previous['tool'], tool)
                              and previous['credential_hash'] == digest and (active or state == 'stopped'))
            generation = previous['generation'] + int(not same_lease) if previous else 1
            expires = now + timedelta(seconds=ttl_seconds) if state == 'watching' else now
            db.execute('''INSERT INTO session_presence
                (room_id,member_id,session_key,tool,state,credential_hash,generation,expires_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(room_id,member_id,session_key) DO UPDATE SET
                    tool=excluded.tool,state=excluded.state,credential_hash=excluded.credential_hash,
                    generation=excluded.generation,expires_at=excluded.expires_at,updated_at=excluded.updated_at''',
                (p.room_id, p.member_id, session_key, tool, state, digest, generation, expires.isoformat(), now.isoformat()))
            return {'room_id': p.room_id, 'member_id': p.member_id, 'session_key': session_key,
                    'tool': tool, 'state': state, 'generation': generation,
                    'expires_at': expires.isoformat(), 'updated_at': now.isoformat(),
                    'source': 'agent_report', 'credential_status': 'valid',
                    'availability_proven': False, 'model_consumption_proven': False}


def route_item(db, principal, item, task_id, requested_session, caller_credential_hash, now):
    """Return one filtered, credential-safe routing projection without writes."""
    task = db.execute('SELECT * FROM tasks WHERE room_id=? AND id=?',
                      (principal.room_id, task_id)).fetchone() if task_id is not None else None
    current = bool(task and not task['cancelled_at'] and task['state'] == 'claimed'
                   and task['owner_member_id'] == principal.member_id)
    execution = ({'task_id': task['id'], 'session_key': task['execution_session_key'],
                  'ownership_epoch': task['ownership_epoch']} if current else None)
    binding = db.execute('''SELECT * FROM task_session_routes
        WHERE task_id=? AND room_id=? AND member_id=? AND ownership_epoch=? AND logical_session_key=?''',
        (task['id'], principal.room_id, principal.member_id, task['ownership_epoch'], task['execution_session_key'])).fetchone() if current and task['execution_session_key'] else None
    presence = _lease(db, binding)
    directed = _binding_active(db, binding, now)
    if directed and (requested_session != binding['native_session_key'] or caller_credential_hash != binding['credential_hash']):
        return None
    scope = 'session' if directed else 'member'
    observation = ({'state': presence['state'], 'generation': presence['generation'],
                    'expires_at': presence['expires_at'], 'updated_at': presence['updated_at'],
                    'credential_status': 'valid' if _credential_active(db, presence['credential_hash'], principal.member_id, principal.room_id, now) else 'unavailable',
                    'active': _presence_active(db, presence, now)} if presence else None)
    # Heartbeat timestamps/expiry extensions deliberately do not alter a live
    # delivery key. State, lease generation and execution changes do.
    signature = [scope, item['kind'], item['id'], item.get('route_version'),
                 [task['id'], task['owner_member_id'], task['execution_session_key'], task['ownership_epoch'], task['state'], bool(task['cancelled_at'])] if task else None,
                 [binding['generation'], binding['native_session_key'], binding['credential_hash']] if binding else None,
                 [presence['generation'], presence['state'], bool(observation['active']), observation['credential_status']] if presence else None]
    fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:24]
    return {**item, 'delivery_scope': scope,
            'target_session_key': binding['native_session_key'] if directed else None,
            'delivery_key': f"{item['kind']}:{item['id']}:{scope}:{fingerprint}",
            'execution_target': execution, 'presence_observation': observation,
            'model_consumption_proven': False}
