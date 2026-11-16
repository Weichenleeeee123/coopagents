"""Private brief cache: opaque bound cursors over frozen snapshot/delta batches.

Only these cache tables are mutated. Expiry/retention prune cache rows, never
business history or files. A terminal cursor is the baseline for the next diff;
an unfinished cursor always continues its frozen batch first.
"""
import hashlib
import json
import re
import secrets
import time

from .errors import ValidationError

TTL_SECONDS = 900
MAX_SNAPSHOTS = 128
MAX_PER_BINDING = 8
MAX_BYTES = 16000


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def item_key(kind, record):
    if kind in ('task', 'dependency', 'request'):
        identity = record['id']
    elif kind == 'owner_question':
        identity = [record['requester_member_id'], record['question_key'], record['target_task_id']]
    elif kind == 'agreement':
        identity = record['contract_id']
    elif kind == 'agreement_change':
        identity = [record['task_id'], record['contract_id']]
    elif kind == 'decision':
        identity = [record['kind'], record['id'], record.get('task_id', record.get('payload', {}).get('task_id'))]
    elif kind == 'member_activity':
        identity = record['member_id']
    else:
        raise ValidationError('Unknown brief item kind')
    return kind + ':' + (str(identity) if isinstance(identity, (str, int)) else digest(identity))


def _removed(entry):
    item = entry['item']
    result = {k: item[k] for k in ('item_key', 'kind', 'id', 'task_id', 'contract_id',
        'question_key', 'target_task_id', 'requester_member_id', 'member_id') if k in item}
    if item['kind'] == 'decision':
        result['decision'] = {k: item['decision'][k] for k in ('kind', 'id', 'task_id') if k in item['decision']}
    return {**result, 'change': 'removed', 'removed': True}


class BriefDeltaStore:
    def __init__(self, database):
        self.db = database
        with self.db.connect(write=True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS brief_delta_snapshots (
                snapshot_id TEXT PRIMARY KEY,binding TEXT NOT NULL,digest TEXT NOT NULL,
                created_at REAL NOT NULL,expires_at REAL NOT NULL,state_json TEXT NOT NULL,
                meta_json TEXT NOT NULL,batch_json TEXT NOT NULL,mode TEXT NOT NULL,reset_reason TEXT)''')
            db.execute('CREATE INDEX IF NOT EXISTS brief_delta_binding ON brief_delta_snapshots(binding,created_at)')
            db.execute('''CREATE TABLE IF NOT EXISTS brief_delta_cursors (
                cursor_id TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL,position INTEGER NOT NULL,
                binding TEXT NOT NULL,UNIQUE(snapshot_id,position),
                FOREIGN KEY(snapshot_id) REFERENCES brief_delta_snapshots(snapshot_id) ON DELETE CASCADE)''')

    @staticmethod
    def _load(db, binding, cursor, now):
        if not isinstance(cursor, str) or not re.fullmatch(r'brief2\.[A-Za-z0-9_-]{32}', cursor):
            return None, 'invalid_cursor'
        row = db.execute('''SELECT s.*,c.position,c.binding AS cursor_binding FROM brief_delta_cursors c
            JOIN brief_delta_snapshots s ON s.snapshot_id=c.snapshot_id WHERE c.cursor_id=?''', (cursor,)).fetchone()
        if row is None:
            return None, 'cursor_missing'
        if row['binding'] != binding or row['cursor_binding'] != binding:
            return None, 'scope_changed'
        if row['expires_at'] <= now:
            return None, 'cursor_expired'
        try:
            result = dict(row)
            for name in ('state', 'meta', 'batch'):
                result[name] = json.loads(row[name + '_json'])
            if (not isinstance(result['state'], dict) or not isinstance(result['meta'], dict)
                    or not isinstance(result['batch'], list) or type(row['position']) is not int
                    or not 0 <= row['position'] <= len(result['batch']) or row['mode'] not in ('snapshot', 'delta')):
                raise ValueError()
            if digest({'state': result['state'], 'meta': result['meta']}) != row['digest']:
                raise ValueError()
            for key, entry in result['state'].items():
                if (not isinstance(entry, dict) or not isinstance(entry.get('hash'), str)
                        or not isinstance(entry.get('item'), dict) or entry['item'].get('item_key') != key):
                    raise ValueError()
            for item in result['batch']:
                if (not isinstance(item, dict) or item.get('change') not in ('snapshot', 'added', 'updated', 'removed')
                        or not isinstance(item.get('item_key'), str)):
                    raise ValueError()
            return result, None
        except (ValueError, TypeError):
            return None, 'cursor_unrecoverable'

    @staticmethod
    def _cursor(db, snapshot_id, position, binding):
        row = db.execute('SELECT cursor_id FROM brief_delta_cursors WHERE snapshot_id=? AND position=?',
                         (snapshot_id, position)).fetchone()
        if row:
            return row[0]
        cursor = 'brief2.' + secrets.token_urlsafe(24)
        db.execute('INSERT INTO brief_delta_cursors VALUES(?,?,?,?)', (cursor, snapshot_id, position, binding))
        return cursor

    @staticmethod
    def _prune(db, binding, now):
        db.execute('DELETE FROM brief_delta_snapshots WHERE expires_at<=?', (now,))
        db.execute('''DELETE FROM brief_delta_snapshots WHERE binding=? AND snapshot_id NOT IN
            (SELECT snapshot_id FROM brief_delta_snapshots WHERE binding=? ORDER BY rowid DESC LIMIT ?)''',
            (binding, binding, max(1, MAX_PER_BINDING)))
        db.execute('''DELETE FROM brief_delta_snapshots WHERE snapshot_id NOT IN
            (SELECT snapshot_id FROM brief_delta_snapshots ORDER BY rowid DESC LIMIT ?)''', (max(1, MAX_SNAPSHOTS),))

    def read(self, db, binding, after_cursor, limit, collect):
        now, previous, reset = time.time(), None, None
        if after_cursor is not None:
            previous, reset = self._load(db, binding, after_cursor, now)
        if previous and previous['position'] < len(previous['batch']):
            return self._page(db, previous, binding, previous['position'], limit)
        state, meta = collect()
        content_digest = digest({'state': state, 'meta': meta})
        if previous and previous['digest'] == content_digest:
            return {**meta, 'items': [], 'limit': limit, 'delta': False, 'mode': 'unchanged',
                'reset': False, 'resync': False, 'reset_reason': None, 'unchanged': True,
                'has_more': False, 'truncated': False, 'batch_total': 0,
                'snapshot_id': previous['snapshot_id'], 'cursor': after_cursor, 'next_cursor': None}
        mode = 'delta' if previous else 'snapshot'
        batch = []
        old = previous['state'] if previous else {}
        for key, entry in state.items():
            change = 'snapshot' if previous is None else 'added' if key not in old else 'updated'
            if previous is None or key not in old or entry['hash'] != old[key]['hash']:
                batch.append({**entry['item'], 'change': change})
        batch.extend(_removed(entry) for key, entry in old.items() if key not in state)
        existing = None
        if after_cursor is None:
            existing = db.execute('''SELECT * FROM brief_delta_snapshots WHERE binding=? AND digest=?
                AND mode='snapshot' AND reset_reason IS NULL AND expires_at>? ORDER BY rowid DESC LIMIT 1''',
                (binding, content_digest, now)).fetchone()
        if existing:
            snapshot = {**dict(existing), 'meta': meta, 'batch': batch}
        else:
            snapshot = {'snapshot_id': secrets.token_urlsafe(24), 'binding': binding, 'digest': content_digest,
                'created_at': now, 'expires_at': now + TTL_SECONDS, 'state_json': encoded(state),
                'meta_json': encoded(meta), 'batch_json': encoded(batch), 'mode': mode, 'reset_reason': reset,
                'meta': meta, 'batch': batch}
            db.execute('''INSERT INTO brief_delta_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)''', tuple(snapshot[k] for k in (
                'snapshot_id', 'binding', 'digest', 'created_at', 'expires_at', 'state_json',
                'meta_json', 'batch_json', 'mode', 'reset_reason')))
        result = self._page(db, snapshot, binding, 0, limit)
        self._prune(db, binding, now)
        return result

    def _page(self, db, snapshot, binding, start, limit):
        batch = snapshot['batch']
        reason = snapshot['reset_reason'] if start == 0 else None
        result = {**snapshot['meta'], 'items': [], 'limit': limit, 'delta': snapshot['mode'] == 'delta',
            'mode': snapshot['mode'], 'reset': reason is not None, 'resync': reason is not None,
            'reset_reason': reason, 'unchanged': False, 'batch_total': len(batch), 'snapshot_id': snapshot['snapshot_id']}

        def progress():
            result['has_more'] = start + len(result['items']) < len(batch)
            result['truncated'] = result['has_more']
            # A fixed-length placeholder makes the wire-size check exact before
            # persisting only the cursor position that was actually returned.
            result['cursor'] = 'brief2.' + 'x' * 32
            result['next_cursor'] = result['cursor'] if result['has_more'] else None

        progress()
        for item in batch[start:start+limit]:
            result['items'].append(item)
            progress()
            if len(encoded(result).encode()) > MAX_BYTES:
                result['items'].pop()
                progress()
                break
        if result['has_more'] and not result['items']:
            raise ValidationError('A brief item exceeds the bounded cache representation; resync from source records')
        if len(encoded(result).encode()) > MAX_BYTES:
            raise ValidationError('Brief metadata exceeds the fixed response budget')
        result['cursor'] = self._cursor(db, snapshot['snapshot_id'], start + len(result['items']), binding)
        result['next_cursor'] = result['cursor'] if result['has_more'] else None
        return result
