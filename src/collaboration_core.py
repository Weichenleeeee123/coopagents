"""Default agent collaboration runtime. All shared state is scoped to a room."""
from pathlib import Path

from .awareness import AwarenessStore, OPERATIONS
from .errors import ValidationError
from .events import EventStore
from .identity import IdentityStore
from .messages import MessageStore
from .protocol import ServiceOperations, _utc_now, fields


class CollaborationService(ServiceOperations):
    lightweight = True

    def __init__(self, database_path):
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = IdentityStore(path, workflow=False)
        self.messages = MessageStore(self.identity, workflow=False)
        self.awareness = AwarenessStore(self.identity)
        with self.identity.db.connect(write=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS message_reply_reads (
                reply_id INTEGER PRIMARY KEY REFERENCES message_replies(id), read_at TEXT NOT NULL)""")
            # Older databases keep their tasks intact. Only plain correspondence
            # is visible here, including the sender's existing read receipts.
            if self.identity._has_table(db, 'workflow_reply_reads'):
                db.execute("""INSERT OR IGNORE INTO message_reply_reads
                    SELECT w.reply_id,w.read_at FROM workflow_reply_reads w JOIN message_replies y ON y.id=w.reply_id
                    JOIN message_requests r ON r.id=y.request_id WHERE r.task_id IS NULL AND r.sender_member_id=w.member_id""")
        self.change_events = EventStore(self.identity, workflow=False)
        self.operations = {
            'list_members': ('agent', self.list_members, {}),
            'send_request': ('agent', self.send_request, {
                **fields('request_key receiver_member_id body'), 'context_version': (int, False, 1)}),
            'read_inbox': ('agent', self.messages.read_inbox, fields('', {'after_id': 0, 'limit': 50})),
            'reply': ('agent', self.messages.reply, fields('request_id request_key context_version body', {'evidence': ''})),
            'read_replies': ('agent', self.read_replies, fields('', {'after_id': 0, 'limit': 20})),
            'wake_digest': ('agent', self.wake_digest, fields('', {'session_key': None})),
            'invite': ('web', self.identity.create_invite, fields('', {'hours': 1})),
            'revoke_invite': ('web', self.identity.revoke_invite, fields('invite_token')),
            'revoke_member': ('web', self.identity.revoke_member, fields('member_id')),
            'connect_agent': ('web', self.identity.connect_agent, {}),
            'rotate_agent': ('web', self.identity.rotate_agent, {}),
        }
        for name, schema in OPERATIONS.items():
            self.operations[name] = ('agent', getattr(self.awareness, name), schema)
        self.reads = {'members': self.identity.list_members}

    def me(self, token):
        return {**super().me(token), 'runtime': 'collaboration'}

    def list_members(self, token):
        return {'members': self.identity.list_members(token)}

    def snapshot(self, token, *, web=True):
        return {**self.me(token), **self.list_members(token)}

    def send_request(self, token, request_key, receiver_member_id, body, context_version=1):
        return self.messages.send_request(token, request_key, receiver_member_id, None, context_version, body)

    def read_replies(self, token, after_id=0, limit=20):
        if not 0 <= after_id < 2**63 or not 1 <= limit <= 50:
            raise ValidationError('Invalid reply cursor or limit')
        with self.identity.db.connect(write=True) as db:
            p = self.identity.resolve(db, token, 'agent')
            rows = db.execute("""SELECT y.*,r.sender_member_id,r.receiver_member_id,r.resolved_at
                FROM message_replies y JOIN message_requests r ON r.id=y.request_id
                WHERE r.room_id=? AND r.sender_member_id=? AND r.task_id IS NULL AND y.id>?
                ORDER BY y.id LIMIT ?""", (p.room_id, p.member_id, after_id, limit + 1)).fetchall()
            now = _utc_now()
            replies = []
            candidates = []
            for row in rows[:limit]:
                db.execute('INSERT OR IGNORE INTO message_reply_reads VALUES(?,?)', (row['id'], now))
                stamp = db.execute('SELECT read_at FROM message_reply_reads WHERE reply_id=?', (row['id'],)).fetchone()[0]
                replies.append({**dict(row), 'read_at': stamp, 'route_state': 'ordinary'})
                if row['evidence'] and row['author_member_id'] != p.member_id:
                    candidates.append({'request_id': row['request_id'], 'reply_id': row['id']})
            result = {'replies': replies, 'has_more': len(rows) > limit,
                    'next_cursor': replies[-1]['id'] if replies else after_id, 'model_consumption_proven': False}

            if candidates:
                result['choice_candidates'] = candidates
                result['choice_guidance'] = ('If an answer settles which implementation the team will extend, '
                    'record it now with remember_choice before finishing this turn. Use the original feature subject, '
                    'the exact reference from evidence and a short shareable summary. Use revision 0 for a new choice. '
                    'Keep unresolved questions private.')
            return result

    def wake_digest(self, token, session_key=None):
        with self.identity.db.connect() as db:
            db.execute('BEGIN')
            p = self.identity.resolve(db, token, 'agent')
            requests = db.execute("""SELECT r.id,r.id AS request_id,r.context_version AS route_version
                FROM message_requests r LEFT JOIN message_receipts m ON m.request_id=r.id
                WHERE r.room_id=? AND r.receiver_member_id=? AND r.task_id IS NULL
                AND r.resolved_at IS NULL AND m.read_at IS NULL ORDER BY r.id LIMIT 50""", (p.room_id, p.member_id))
            replies = db.execute("""SELECT y.id,r.id AS request_id,r.context_version AS route_version
                FROM message_replies y JOIN message_requests r ON r.id=y.request_id
                LEFT JOIN message_reply_reads w ON w.reply_id=y.id
                WHERE r.room_id=? AND r.sender_member_id=? AND r.task_id IS NULL AND r.resolved_at IS NULL
                AND w.reply_id IS NULL ORDER BY y.id LIMIT 50""", (p.room_id, p.member_id))
            incoming = [dict(row, kind='request', delivery_scope='member') for row in requests]
            answers = [dict(row, kind='reply', delivery_scope='member') for row in replies]
            return {'room_id': p.room_id, 'member_id': p.member_id, 'items': incoming + answers,
                    'counts': {'request': len(incoming), 'reply': len(answers), 'handoff': 0},
                    'content_included': False, 'receipts_written': False}
