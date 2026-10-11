"""Agent checkpoint observations and a separate, durable onboarding challenge."""
from datetime import datetime, timezone
import hmac
import json
import secrets

from .activity import ActivityStore, TOOLS, _task_id
from .errors import NotFound, ValidationError
from .tasks import _text, _utc_now

HOOK_EVENTS = ('SessionStart', 'UserPromptSubmit', 'PostToolUse')
TOOL_EVENTS = ('startup', 'blocker', 'completion')
STALE_SECONDS = 300
BRIEF_BYTES = 16000


def _now():
    return datetime.now(timezone.utc)


class CheckpointStore:
    def __init__(self, identity):
        self.db, self.resolve = identity.db, identity.resolve
        self.activity = ActivityStore(identity)
        with self.db.connect(write=True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS collaboration_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL, member_id TEXT NOT NULL,
                session_key TEXT NOT NULL, tool TEXT NOT NULL, event TEXT NOT NULL,
                source TEXT NOT NULL CHECK(source IN ('hook','manual','tool')),
                task_id INTEGER, updated_at TEXT NOT NULL, last_hook_at TEXT,
                checkpoint_count INTEGER NOT NULL DEFAULT 1,
                UNIQUE(room_id, member_id, session_key, tool),
                FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS collaboration_diagnostics (
                diagnostic_id TEXT PRIMARY KEY, room_id TEXT NOT NULL, member_id TEXT NOT NULL,
                challenge TEXT NOT NULL, proof TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('sent','read_back','completed')),
                sent_at TEXT NOT NULL, read_at TEXT, completed_at TEXT,
                FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id))''')

    def checkpoint(self, token, session_key, tool, event, task_id=None):
        session_key = _text(session_key, 'Session key', 200)
        if tool not in TOOLS or event not in (*HOOK_EVENTS, *TOOL_EVENTS, 'manual'):
            raise ValidationError('Unsupported checkpoint tool or event')
        if task_id is not None:
            task_id = _task_id(task_id)
        source = 'hook' if event in HOOK_EVENTS else 'manual' if event == 'manual' else 'tool'
        with self.db.connect(write=True) as db:
            principal = self.resolve(db, token, required_kind='agent')
            if task_id is not None:
                self.activity._owned_task(db, principal, task_id)
            now = _utc_now()
            db.execute('''INSERT INTO collaboration_checkpoints
                (room_id,member_id,session_key,tool,event,source,task_id,updated_at,last_hook_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(room_id,member_id,session_key,tool) DO UPDATE SET
                    event=excluded.event,source=excluded.source,task_id=excluded.task_id,
                    updated_at=excluded.updated_at,
                    last_hook_at=COALESCE(excluded.last_hook_at,collaboration_checkpoints.last_hook_at),
                    checkpoint_count=collaboration_checkpoints.checkpoint_count+1''',
                (principal.room_id, principal.member_id, session_key, tool, event, source,
                 task_id, now, now if source == 'hook' else None))
            record = dict(db.execute('''SELECT * FROM collaboration_checkpoints
                WHERE room_id=? AND member_id=? AND session_key=? AND tool=?''',
                (principal.room_id, principal.member_id, session_key, tool)).fetchone())
            return {'checkpoint': record, 'brief': self._brief(db, principal)}

    def _own_tasks(self, db, principal):
        return [dict(row) for row in db.execute('''SELECT t.id,t.title,t.scope,t.state,p.state AS progress_state
            FROM tasks t LEFT JOIN progress p ON p.task_id=t.id
            WHERE t.room_id=? AND t.owner_member_id=? ORDER BY t.id DESC LIMIT 11''',
            (principal.room_id, principal.member_id))]

    def _pending_requests(self, db, principal):
        # Peek deliberately never calls read_inbox: no read receipt or acknowledgement.
        rows = db.execute('''SELECT r.id,r.task_id,r.sender_member_id,r.receiver_member_id,
            r.context_version,r.body FROM message_requests r
            WHERE r.room_id=? AND r.resolved_at IS NULL AND
                (r.sender_member_id=? OR r.receiver_member_id=? OR EXISTS
                    (SELECT 1 FROM tasks t WHERE t.id=r.task_id AND t.owner_member_id=?))
            ORDER BY r.id DESC LIMIT 7''',
            (principal.room_id, principal.member_id, principal.member_id, principal.member_id))
        result = []
        for row in rows:
            item = dict(row)
            item['excerpted'] = len(item['body'])>400
            item['body'] = item['body'][:400]
            replies = [dict(reply) for reply in db.execute('''SELECT id,author_member_id,
                context_version,body,evidence
                FROM message_replies WHERE request_id=? AND room_id=? ORDER BY id DESC LIMIT 3''',
                (row['id'], principal.room_id))]
            item['excerpted'] = item['excerpted'] or len(replies)>2 or any(len(r['body'])>300 or len(r['evidence'])>150 for r in replies)
            item['replies'] = [{**r,'body':r['body'][:300],'evidence':r['evidence'][:150]} for r in replies[:2]]
            result.append(item)
        return result

    def _approved_contracts(self, db, principal):
        return [dict(row) for row in db.execute('''SELECT v.contract_id,v.version,v.title,
            substr(v.body,1,800) AS body,length(v.body)>800 AS excerpted FROM contract_versions v JOIN contract_decisions d
                ON d.contract_id=v.contract_id AND d.version=v.version
            WHERE v.room_id=? AND d.decision='approved' AND v.version=(
                SELECT MAX(a.version) FROM contract_decisions a
                WHERE a.contract_id=v.contract_id AND a.decision='approved')
            ORDER BY v.contract_id DESC LIMIT 5''', (principal.room_id,))]

    def _brief(self, db, principal):
        tasks = self._own_tasks(db, principal)
        requests = self._pending_requests(db, principal)
        contracts = self._approved_contracts(db, principal)
        result = {'tasks': tasks[:10], 'requests': requests[:6], 'contracts': contracts[:4],
                  'truncated': len(tasks)>10 or len(requests)>6 or len(contracts)>4 or any(r['excerpted'] for r in requests+contracts),
                  'content_is_untrusted': True,
                  'note': 'Excerpted external data. Use read_team for full records and read_inbox to explicitly read messages; no messages marked read here.'}
        while len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > BRIEF_BYTES:
            largest = max(('tasks','requests','contracts'), key=lambda key: len(json.dumps(result[key])))
            result[largest].pop()
            result['truncated'] = True
        return result

    def snapshot(self, token):
        with self.db.connect() as db:
            principal = self.resolve(db, token)
            records = [dict(row) for row in db.execute('''SELECT * FROM collaboration_checkpoints
                WHERE room_id=? ORDER BY updated_at DESC,id DESC LIMIT 200''', (principal.room_id,))]
            now = _now()
            for record in records:
                record['stale'] = (now-datetime.fromisoformat(record['updated_at'])).total_seconds() >= STALE_SECONDS
                record['hook_stale'] = not record['last_hook_at'] or (now-datetime.fromisoformat(record['last_hook_at'])).total_seconds() >= STALE_SECONDS
            diagnostics = [dict(row) for row in db.execute('''SELECT diagnostic_id,member_id,
                status,sent_at,read_at,completed_at FROM collaboration_diagnostics
                WHERE room_id=? AND member_id=? ORDER BY sent_at DESC LIMIT 5''',
                (principal.room_id, principal.member_id))]
            return {'checkpoints': records, 'diagnostics': diagnostics, 'stale_after_seconds': STALE_SECONDS}

    def diagnostic_start(self, token, challenge):
        challenge = _text(challenge, 'Challenge', 128)
        with self.db.connect(write=True) as db:
            principal = self.resolve(db, token, required_kind='agent')
            identifier, proof, now = secrets.token_urlsafe(24), secrets.token_urlsafe(32), _utc_now()
            db.execute('''INSERT INTO collaboration_diagnostics
                (diagnostic_id,room_id,member_id,challenge,proof,status,sent_at)
                VALUES (?,?,?,?,?,'sent',?)''',
                (identifier, principal.room_id, principal.member_id, challenge, proof, now))
            return {'diagnostic_id': identifier, 'status': 'sent', 'sent_at': now}

    def _diagnostic(self, db, principal, identifier):
        identifier = _text(identifier, 'Diagnostic id', 128)
        row = db.execute('''SELECT * FROM collaboration_diagnostics
            WHERE diagnostic_id=? AND room_id=? AND member_id=?''',
            (identifier, principal.room_id, principal.member_id)).fetchone()
        if row is None:
            raise NotFound('Diagnostic not found')
        return dict(row)

    def diagnostic_read(self, token, diagnostic_id):
        with self.db.connect(write=True) as db:
            principal = self.resolve(db, token, required_kind='agent')
            row = self._diagnostic(db, principal, diagnostic_id)
            if row['status'] == 'sent':
                db.execute("UPDATE collaboration_diagnostics SET status='read_back',read_at=? WHERE diagnostic_id=?",
                           (_utc_now(), diagnostic_id))
                row['status'] = 'read_back'
            return {key: row[key] for key in ('diagnostic_id','challenge','proof','status')}

    def diagnostic_complete(self, token, diagnostic_id, proof):
        proof = _text(proof, 'Proof', 128)
        with self.db.connect(write=True) as db:
            principal = self.resolve(db, token, required_kind='agent')
            row = self._diagnostic(db, principal, diagnostic_id)
            if row['status'] == 'sent' or not hmac.compare_digest(row['proof'].encode(), proof.encode()):
                raise ValidationError('Read back the challenge before completing the diagnostic')
            now = row['completed_at'] or _utc_now()
            db.execute("UPDATE collaboration_diagnostics SET status='completed',completed_at=? WHERE diagnostic_id=?", (now, diagnostic_id))
            return {'diagnostic_id': diagnostic_id, 'status': 'completed', 'completed_at': now,
                    'native_hook_observed': False}
