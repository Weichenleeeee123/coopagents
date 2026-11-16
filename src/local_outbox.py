"""Private, identity-bound technical intents; local persistence is not delivery.

Callbacks are synchronous. The verifier must observe the current agent /me;
the sender must use the unchanged payload against the authoritative service.
Nothing here starts a host, grants authority, resolves work or deletes files.
"""
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError, URLError

from .errors import AccessDenied, Conflict, ValidationError
from .protocol import fields, validate
from .spaces import checked_path, private_directory, protect

OPERATIONS = frozenset(('ask_owner', 'send_request', 'reply', 'reply_dependency', 'create_dependency'))
MAX_ENTRIES = 1000
MAX_PAYLOAD_BYTES = 32768
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_ATTEMPTS = 5
BASE_DELAY_SECONDS = 2
MAX_DELAY_SECONDS = 60
LEASE_SECONDS = 30
RETRYABLE = frozenset(('network', 'server'))
_BATCH_STOP = frozenset(('auth', 'quota', 'identity_mismatch'))
REASONS = RETRYABLE | {'auth', 'conflict', 'validation', 'quota', 'identity_mismatch',
                       'retry_exhausted', 'capacity', 'local_storage', 'unknown'}


class OutboxError(ValidationError):
    def __init__(self, reason='unknown', *, status_code=None):
        self.reason = reason if isinstance(reason, str) and reason in REASONS else 'unknown'
        self.status_code = status_code if type(status_code) is int else None
        self.retryable = self.reason in RETRYABLE
        super().__init__('Coopagents recovery blocked: ' + self.reason)


class _IntentConflict(Conflict, ValidationError):
    pass


def supports(operation):
    return isinstance(operation, str) and operation in OPERATIONS


def stopped_safely(callback):
    try:
        return bool(callback())
    except Exception:
        return True  # Unknown local stop state cannot authorize networking.


def classify_error(error):
    if isinstance(error, OutboxError):
        return error.reason
    status = error.code if isinstance(error, HTTPError) else getattr(error, 'status_code', None)
    if type(status) is int:
        if status in (401, 403): return 'auth'
        if status == 409: return 'conflict'
        if status == 429: return 'quota'
        if 500 <= status < 600: return 'server'
        if 400 <= status < 500: return 'validation'
    if isinstance(error, (AccessDenied, PermissionError)): return 'auth'
    if isinstance(error, Conflict): return 'conflict'
    if isinstance(error, ValidationError): return 'validation'
    if isinstance(error, (URLError, OSError, TimeoutError, ConnectionError)): return 'network'
    return 'unknown'


def _payload(operation, arguments):
    if not supports(operation) or not isinstance(arguments, dict):
        raise OutboxError('validation')
    from .workflow import schemas as workflow_schemas
    from .dependencies import schemas as dependency_schemas
    schemas = {**workflow_schemas(), **dependency_schemas(fields),
        'send_request': fields('request_key context_version body', {'receiver_member_id': None, 'task_id': None}),
        'reply': fields('request_id request_key context_version body', {'evidence': ''})}
    validate(dict(arguments), schemas[operation])  # Validate a copy; never inject defaults into the intent.
    request_key = arguments.get('request_key')
    if not isinstance(request_key, str) or not 1 <= len(request_key.strip()) <= 200:
        raise OutboxError('validation')
    serialized = json.dumps(arguments, sort_keys=True, ensure_ascii=True, allow_nan=False)
    if len(serialized.encode()) > MAX_PAYLOAD_BYTES:
        raise OutboxError('capacity')
    return request_key.strip(), serialized, hashlib.sha256(serialized.encode()).hexdigest()


def _successful(result):
    if (not isinstance(result, dict) or result.get('is_error') is True or result.get('isError') is True
            or result.get('error') is not None or result.get('status') in ('ambiguous', 'not_found', 'queued_locally')):
        code = result.get('error') if isinstance(result, dict) else None
        if isinstance(result, dict) and result.get('status') in ('ambiguous', 'not_found'):
            raise OutboxError('validation')
        raise OutboxError({'AccessDenied': 'auth', 'Conflict': 'conflict',
                           'ValidationError': 'validation'}.get(code, 'unknown') if isinstance(code, str) else 'unknown')


def stored_identity(path):
    """Read only the originally verified binding; never create or rebind state."""
    path = checked_path(path)
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('SELECT room_id,member_id FROM outbox_identity WHERE singleton=1').fetchone()
        return {'room_id': row[0], 'member_id': row[1]} if row else None
    except sqlite3.Error:
        raise OutboxError('local_storage') from None


class LocalOutbox:
    supports = staticmethod(supports)

    def __init__(self, path, room_id, member_id):
        if not all(isinstance(value, str) and 1 <= len(value) <= 200 for value in (room_id, member_id)):
            raise OutboxError('validation')
        self.path, self.room_id, self.member_id = checked_path(path), room_id, member_id
        private_directory(self.path.parent)
        if not self.path.exists():
            try:
                with self.path.open('xb'):
                    protect(self.path)
            except FileExistsError:
                pass
        protect(self.path)
        with self._connect(write=True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS outbox_identity (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),room_id TEXT NOT NULL,member_id TEXT NOT NULL)''')
            row = db.execute('SELECT room_id,member_id FROM outbox_identity WHERE singleton=1').fetchone()
            if row and tuple(row) != (room_id, member_id):
                raise OutboxError('identity_mismatch')
            if not row:
                db.execute('INSERT INTO outbox_identity VALUES(1,?,?)', (room_id, member_id))
            db.execute('''CREATE TABLE IF NOT EXISTS outbox_intents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,operation TEXT NOT NULL,request_key TEXT NOT NULL,
                payload_hash TEXT NOT NULL,arguments_json TEXT NOT NULL,payload_bytes INTEGER NOT NULL,
                status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,reason TEXT,
                next_attempt_at REAL NOT NULL DEFAULT 0,created_at REAL NOT NULL,applied_at REAL,
                UNIQUE(operation,request_key))''')

    @contextmanager
    def _connect(self, write=False):
        db = None
        try:
            db = sqlite3.connect(self.path if write else self.path.as_uri() + '?mode=ro',
                                 uri=not write, timeout=5, isolation_level=None)
            db.row_factory = sqlite3.Row
            if write:
                db.execute('PRAGMA journal_mode=TRUNCATE')
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write: db.commit()
        except sqlite3.Error:
            if write and db is not None: db.rollback()
            raise OutboxError('local_storage') from None
        except BaseException:
            if write and db is not None: db.rollback()
            raise
        finally:
            if db is not None: db.close()

    @staticmethod
    def _safe(row):
        reason = row['reason'] if row['reason'] is None or row['reason'] in REASONS else 'unknown'
        status = row['status'] if row['status'] in ('queued_locally', 'blocked', 'synced_to_service') else 'blocked'
        action = ('none' if status == 'synced_to_service' else
                  'wait_for_bounded_retry' if status == 'queued_locally' else
                  'verify_original_identity' if reason in ('auth', 'identity_mismatch') else
                  'refresh_authority_and_review_intent' if reason in ('conflict', 'validation') else
                  'wait_or_review_quota' if reason == 'quota' else 'review_and_retry_explicitly')
        return {'outbox_id': row['id'], 'operation': row['operation'] if supports(row['operation']) else 'unsupported', 'status': status,
                'attempts': row['attempts'], 'reason': reason, 'next_action': action}

    def summary(self):
        with self._connect() as db:
            rows = db.execute('SELECT id,operation,status,attempts,reason FROM outbox_intents ORDER BY id').fetchall()
        items = [self._safe(r) for r in rows]
        counts = {status: sum(row['status'] == status for row in items)
                  for status in ('queued_locally', 'blocked', 'synced_to_service')}
        return {'counts': counts, 'items': items, 'model_consumption_proven': False}

    def enqueue(self, operation, arguments):
        key, payload, payload_hash = _payload(operation, arguments)
        with self._connect(write=True) as db:
            row = db.execute('SELECT * FROM outbox_intents WHERE operation=? AND request_key=?', (operation, key)).fetchone()
            if row and row['payload_hash'] != payload_hash:
                raise _IntentConflict('Request key already has a different locally queued payload')
            if not row:
                count, size = db.execute('SELECT COUNT(*),COALESCE(SUM(payload_bytes),0) FROM outbox_intents').fetchone()
                if count >= MAX_ENTRIES or size + len(payload.encode()) > MAX_TOTAL_BYTES:
                    raise OutboxError('capacity')
                identifier = db.execute('''INSERT INTO outbox_intents
                    (operation,request_key,payload_hash,arguments_json,payload_bytes,status,created_at)
                    VALUES(?,?,?,?,?,'queued_locally',?)''',
                    (operation, key, payload_hash, payload, len(payload.encode()), time.time())).lastrowid
                row = db.execute('SELECT * FROM outbox_intents WHERE id=?', (identifier,)).fetchone()
            return {**self._safe(row), 'delivered': False, 'service_applied': row['status'] == 'synced_to_service',
                    'model_consumption_proven': False}

    def complete(self, operation, arguments, result):
        _successful(result)
        key, _, payload_hash = _payload(operation, arguments)
        with self._connect(write=True) as db:
            row = db.execute('SELECT * FROM outbox_intents WHERE operation=? AND request_key=?', (operation, key)).fetchone()
            if row and row['payload_hash'] != payload_hash:
                raise _IntentConflict('Successful response does not match the original queued payload')
            if row:
                db.execute("UPDATE outbox_intents SET status='synced_to_service',reason=NULL,applied_at=?,next_attempt_at=0 WHERE id=?",
                           (time.time(), row['id']))
                row = db.execute('SELECT * FROM outbox_intents WHERE id=?', (row['id'],)).fetchone()
        return {**(self._safe(row) if row else {'outbox_id': None, 'operation': operation, 'status': 'synced_to_service'}),
                'service_applied': True, 'model_consumption_proven': False}

    def _failure(self, identifier, reason):
        with self._connect(write=True) as db:
            row = db.execute('SELECT * FROM outbox_intents WHERE id=?', (identifier,)).fetchone()
            if row is None or row['status'] == 'synced_to_service': return
            retry = reason in RETRYABLE and row['attempts'] < MAX_ATTEMPTS
            if reason in RETRYABLE and not retry: reason = 'retry_exhausted'
            delay = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * 2 ** min(row['attempts'], 10))
            db.execute('UPDATE outbox_intents SET status=?,reason=?,next_attempt_at=? WHERE id=?',
                       ('queued_locally' if retry else 'blocked', reason, time.time() + delay if retry else 0, identifier))

    def record_failure(self, operation, arguments, error):
        key, _, payload_hash = _payload(operation, arguments)
        with self._connect() as db:
            row = db.execute('SELECT id,payload_hash FROM outbox_intents WHERE operation=? AND request_key=?', (operation, key)).fetchone()
        if row and row['payload_hash'] == payload_hash:
            self._failure(row['id'], classify_error(error))
        return self.summary()

    def _claim(self, identifier):
        with self._connect(write=True) as db:
            row = db.execute('SELECT * FROM outbox_intents WHERE id=?', (identifier,)).fetchone()
            if row is None or row['status'] != 'queued_locally' or row['next_attempt_at'] > time.time(): return None
            if row['attempts'] >= MAX_ATTEMPTS:
                db.execute("UPDATE outbox_intents SET status='blocked',reason='retry_exhausted' WHERE id=?", (identifier,))
                return None
            db.execute('UPDATE outbox_intents SET attempts=attempts+1,next_attempt_at=? WHERE id=?',
                       (time.time() + LEASE_SECONDS, identifier))
            return dict(row)

    def flush(self, verify_identity, sender, stopped=lambda: False, limit=20):
        if type(limit) is not int or not 1 <= limit <= 50: raise OutboxError('validation')
        if stopped_safely(stopped): return self.summary()
        with self._connect() as db:
            pending = db.execute('''SELECT id FROM outbox_intents WHERE status='queued_locally'
                AND next_attempt_at<=? ORDER BY id LIMIT ?''', (time.time(), limit)).fetchall()
        if not pending: return self.summary()
        try:
            identity = verify_identity()
            identity = identity.get('me', identity) if isinstance(identity, dict) else {}
            if (identity.get('room_id'), identity.get('member_id'), identity.get('kind')) != (self.room_id, self.member_id, 'agent'):
                raise OutboxError('identity_mismatch')
        except Exception as error:
            reason = classify_error(error)
            for row in pending:
                if stopped_safely(stopped): break
                if self._claim(row['id']) is not None:
                    self._failure(row['id'], reason)
                    if reason in _BATCH_STOP: break
            return self.summary()
        for pending_row in pending:
            if stopped_safely(stopped): break
            row = self._claim(pending_row['id'])
            if row is None: continue
            try:
                try:
                    arguments = json.loads(row['arguments_json'])
                    key, _, payload_hash = _payload(row['operation'], arguments)
                    if key != row['request_key'] or payload_hash != row['payload_hash']:
                        raise OutboxError('validation')
                except OutboxError:
                    raise
                except (ValueError, TypeError):
                    raise OutboxError('validation') from None
                result = sender(row['operation'], json.loads(row['arguments_json']))
                _successful(result)
                self.complete(row['operation'], arguments, result)
            except Exception as error:
                reason = classify_error(error)
                self._failure(row['id'], reason)
                if reason in _BATCH_STOP: break
        return self.summary()
