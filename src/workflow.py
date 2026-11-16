"""Small authenticated compositions of existing collaboration domain operations."""
import hashlib
import json

from .dependencies import _row as dependency_row, project as project_dependency
from .errors import Conflict, ValidationError
from .messages import _positive
from .task_lifecycle import task_row
from .tasks import _text, _utc_now


def schemas():
    optional_int = lambda: (int, False, None)
    return {
        'ask_owner': {
            'request_key': (str, True, None), 'body': (str, True, None),
            'target_task_id': optional_int(), 'scope': (str, False, None),
            'source_task_id': optional_int(), 'expected_revision': optional_int(),
            'context': (str, False, ''), 'session_key': (str, False, None),
            'ownership_epoch': optional_int(),
        },
        'read_replies': {'after_id': (int, False, 0), 'limit': (int, False, 20),
                         'task_id': optional_int()},
    }


class WorkflowStore:
    def __init__(self, service):
        self.service = service
        self.identity = service.identity
        self.db = self.identity.db
        with self.db.connect(write=True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS workflow_questions (
                room_id TEXT NOT NULL, member_id TEXT NOT NULL, request_key TEXT NOT NULL,
                payload_hash TEXT NOT NULL, target_task_id INTEGER NOT NULL,
                initial_owner TEXT, initial_revision INTEGER NOT NULL,
                dependency_id INTEGER, request_id INTEGER, created_at TEXT NOT NULL,
                PRIMARY KEY(room_id,member_id,request_key),
                FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
                FOREIGN KEY(target_task_id,room_id) REFERENCES tasks(id,room_id),
                FOREIGN KEY(dependency_id) REFERENCES task_dependencies(id),
                FOREIGN KEY(request_id) REFERENCES message_requests(id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS workflow_reply_reads (
                room_id TEXT NOT NULL, member_id TEXT NOT NULL, reply_id INTEGER NOT NULL,
                read_at TEXT NOT NULL, PRIMARY KEY(room_id,member_id,reply_id),
                FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
                FOREIGN KEY(reply_id) REFERENCES message_replies(id))''')

    def ask_owner(self, token, request_key, body, target_task_id=None, scope=None,
                  source_task_id=None, expected_revision=None, context='',
                  session_key=None, ownership_epoch=None):
        request_key = _text(request_key, 'Request key', 200)
        body = _text(body, 'Question', 500)
        if not isinstance(context, str) or len(context.strip()) > 3000:
            raise ValidationError('Context must contain at most 3000 characters')
        context = context.strip()
        if (target_task_id is None) == (scope is None):
            raise ValidationError('Provide exactly one of target_task_id or scope')
        if scope is not None:
            scope = _text(scope, 'Scope', 500).replace('\\', '/').strip('/')
            if not scope or any(part in ('', '.', '..') for part in scope.split('/')):
                raise ValidationError('Scope must contain explicit path segments')
        if source_task_id is None:
            if any(value is not None for value in (expected_revision, session_key, ownership_epoch)):
                raise ValidationError('Execution fields require source_task_id')
        elif type(expected_revision) is not int or expected_revision < 0:
            raise ValidationError('Source task expected_revision is required')
        values = [target_task_id, scope, source_task_id, expected_revision, body, context,
                  session_key, ownership_epoch]
        digest = hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()
        with self.db.connect(write=True) as db:
            p = self.identity.resolve(db, token, required_kind='agent')
            if source_task_id is not None:
                source = task_row(db, p, source_task_id)
                self.service.dependencies._authority(db, p, source, session_key, ownership_epoch)
            existing = db.execute('''SELECT * FROM workflow_questions
                WHERE room_id=? AND member_id=? AND request_key=?''',
                (p.room_id, p.member_id, request_key)).fetchone()
            if existing:
                if existing['payload_hash'] != digest:
                    raise Conflict('Request key already has a different payload')
                return self._question_result(db, p, existing)
            selected = self.service.dependencies.lookup_in_connection(db, p, target_task_id, scope)
            if selected['status'] in ('not_found', 'ambiguous'):
                return {**selected, 'request': None, 'dependency': None}
            target = selected['candidates'][0]
            if not target['owner_member_id'] and source_task_id is None:
                return {**selected, 'target': target, 'request': None, 'dependency': None}
            domain_key = 'owner-question:' + hashlib.sha256(
                (p.member_id + ':' + request_key).encode()).hexdigest()
            dependency_id = request_id = None
            if source_task_id is not None:
                dep = self.service.dependencies.create_in_connection(db, p, source_task_id,
                    target['id'], body, expected_revision, domain_key, context, session_key, ownership_epoch)
                dependency_id = dep['id']
            else:
                request = self.service.messages.send_in_connection(db, p, domain_key,
                    target['owner_member_id'], target['id'], 1,
                    body + ('\n' + context if context else ''))
                request_id = request['id']
            db.execute('''INSERT INTO workflow_questions VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (p.room_id, p.member_id, request_key, digest, target['id'],
                 target['owner_member_id'], target['revision'], dependency_id, request_id, _utc_now()))
            saved = db.execute('''SELECT * FROM workflow_questions
                WHERE room_id=? AND member_id=? AND request_key=?''',
                (p.room_id, p.member_id, request_key)).fetchone()
            return self._question_result(db, p, saved)

    def _question_result(self, db, p, saved):
        target = task_row(db, p, saved['target_task_id'])
        dep = project_dependency(db, dependency_row(db, p, saved['dependency_id'])) if saved['dependency_id'] else None
        request_id = dep['current_request_id'] if dep else saved['request_id']
        request = (self.service.messages._enrich(db, self.service.messages._request(db, p, request_id))
                   if request_id else None)
        return {
            'status': 'delivered' if request else dep['routing_state'] if dep else 'unassigned',
            'target': {key: target[key] for key in ('id', 'title', 'scope', 'owner_member_id',
                                                   'revision', 'execution_session_key', 'ownership_epoch')},
            'target_changed': (target['owner_member_id'], target['revision']) !=
                              (saved['initial_owner'], saved['initial_revision']),
            'routing': 'task_dependency' if dep else 'fixed_recipient',
            'request': request, 'dependency': dep,
        }

    def read_replies(self, token, after_id=0, limit=20, task_id=None):
        if type(after_id) is not int or not 0 <= after_id < 2**63:
            raise ValidationError('Reply cursor must be a nonnegative integer')
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValidationError('Limit must be an integer from 1 to 50')
        if task_id is not None:
            task_id = _positive(task_id, 'Task id')
        with self.db.connect(write=True) as db:
            p = self.identity.resolve(db, token, required_kind='agent')
            if task_id is not None:
                task_row(db, p, task_id)
            rows = db.execute('''SELECT y.*,r.task_id,r.sender_member_id,r.receiver_member_id,
                    r.resolved_at,x.dependency_id,d.current_request_id,d.status AS dependency_status
                FROM message_replies y JOIN message_requests r ON r.id=y.request_id
                LEFT JOIN dependency_routes x ON x.request_id=r.id
                LEFT JOIN task_dependencies d ON d.id=x.dependency_id
                WHERE r.room_id=? AND r.sender_member_id=?
                    AND y.id>? AND (? IS NULL OR r.task_id=?) ORDER BY y.id LIMIT ?''',
                (p.room_id, p.member_id, after_id, task_id, task_id, limit+1)).fetchall()
            now = _utc_now()
            result = []
            for row in rows[:limit]:
                db.execute('''INSERT INTO workflow_reply_reads VALUES(?,?,?,?)
                    ON CONFLICT(room_id,member_id,reply_id) DO NOTHING''',
                    (p.room_id, p.member_id, row['id'], now))
                item = {key: row[key] for key in ('id', 'request_id', 'task_id', 'author_member_id',
                    'context_version', 'body', 'evidence', 'created_at', 'sender_member_id',
                    'receiver_member_id', 'resolved_at', 'dependency_id')}
                item['route_state'] = ('historical' if row['request_id'] != row['current_request_id']
                    else 'current' if row['dependency_status'] == 'active' else 'closed') if row['dependency_id'] else 'ordinary'
                item['read_at'] = db.execute('''SELECT read_at FROM workflow_reply_reads
                    WHERE room_id=? AND member_id=? AND reply_id=?''',
                    (p.room_id, p.member_id, row['id'])).fetchone()[0]
                result.append(item)
            return {'replies': result, 'next_cursor': result[-1]['id'] if result else after_id,
                    'has_more': len(rows) > limit, 'model_consumption_proven': False}
