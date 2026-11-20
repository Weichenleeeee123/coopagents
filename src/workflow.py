"""Small authenticated compositions of existing collaboration domain operations."""
import hashlib
import json
import re

from .dependencies import _row as dependency_row, project as project_dependency
from .errors import Conflict, ValidationError
from .messages import _positive
from .task_lifecycle import task_row
from .tasks import _text, _utc_now


def initialize(db):
    """Base-store schema and additive upgrades; no credential fabrication."""
    db.execute('''CREATE TABLE IF NOT EXISTS workflow_questions (
        room_id TEXT NOT NULL, member_id TEXT NOT NULL, request_key TEXT NOT NULL,
        payload_hash TEXT NOT NULL, target_task_id INTEGER NOT NULL,
        initial_owner TEXT, initial_revision INTEGER NOT NULL, dependency_id INTEGER,
        request_id INTEGER, created_at TEXT NOT NULL,
        PRIMARY KEY(room_id,member_id,request_key),
        FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
        FOREIGN KEY(target_task_id,room_id) REFERENCES tasks(id,room_id),
        FOREIGN KEY(dependency_id) REFERENCES task_dependencies(id),
        FOREIGN KEY(request_id) REFERENCES message_requests(id))''')
    columns = {r['name'] for r in db.execute('PRAGMA table_info(workflow_questions)')}
    for name, definition in {'question_body': "TEXT NOT NULL DEFAULT ''",
            'routing_state': "TEXT NOT NULL DEFAULT 'unassigned'",
            'route_version': 'INTEGER NOT NULL DEFAULT 0',
            'target_ownership_epoch': 'INTEGER NOT NULL DEFAULT 0'}.items():
        if name not in columns:
            db.execute('ALTER TABLE workflow_questions ADD COLUMN ' + name + ' ' + definition)
    db.execute('''CREATE TABLE IF NOT EXISTS workflow_owner_routes (
        request_id INTEGER PRIMARY KEY,room_id TEXT NOT NULL,member_id TEXT NOT NULL,
        request_key TEXT NOT NULL,route_version INTEGER NOT NULL,
        target_ownership_epoch INTEGER NOT NULL,created_at TEXT NOT NULL,
        UNIQUE(room_id,member_id,request_key,route_version),
        FOREIGN KEY(request_id) REFERENCES message_requests(id),
        FOREIGN KEY(room_id,member_id,request_key)
            REFERENCES workflow_questions(room_id,member_id,request_key))''')
    db.execute('CREATE INDEX IF NOT EXISTS workflow_owner_target ON workflow_questions(target_task_id,dependency_id,routing_state)')
    db.execute('''CREATE TABLE IF NOT EXISTS workflow_reply_reads (
        room_id TEXT NOT NULL,member_id TEXT NOT NULL,reply_id INTEGER NOT NULL,read_at TEXT NOT NULL,
        PRIMARY KEY(room_id,member_id,reply_id),
        FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
        FOREIGN KEY(reply_id) REFERENCES message_replies(id))''')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_reply_reads'").fetchone():
        db.execute("""INSERT OR IGNORE INTO workflow_reply_reads
            SELECT r.room_id,r.sender_member_id,w.reply_id,w.read_at FROM message_reply_reads w
            JOIN message_replies y ON y.id=w.reply_id JOIN message_requests r ON r.id=y.request_id
            WHERE r.task_id IS NULL""")
    for question in db.execute('SELECT * FROM workflow_questions WHERE dependency_id IS NULL').fetchall():
        if question['request_id'] and not db.execute('SELECT 1 FROM workflow_owner_routes WHERE request_id=?',
                                                   (question['request_id'],)).fetchone():
            old = db.execute('SELECT * FROM message_requests WHERE id=?', (question['request_id'],)).fetchone()
            target = db.execute('SELECT * FROM tasks WHERE id=?', (question['target_task_id'],)).fetchone()
            epoch = (target['ownership_epoch'] if old['receiver_member_id'] == target['owner_member_id']
                     and old['created_at'] >= (target['epoch_started_at'] or '') else 0)
            version = max(question['route_version'], 1)
            db.execute('INSERT INTO workflow_owner_routes VALUES(?,?,?,?,?,?,?)',
                (old['id'], question['room_id'], question['member_id'], question['request_key'],
                 version, epoch, old['created_at']))
            db.execute('''UPDATE workflow_questions SET question_body=?,routing_state=?,route_version=?,
                target_ownership_epoch=? WHERE room_id=? AND member_id=? AND request_key=?''',
                (question['question_body'] or old['body'], 'closed' if old['resolved_at'] else 'routed',
                 version, epoch, question['room_id'], question['member_id'], question['request_key']))
        _route_owner_question(db, _question_row(db, question))


def _question_row(db, question):
    return db.execute('SELECT * FROM workflow_questions WHERE room_id=? AND member_id=? AND request_key=?',
                      (question['room_id'], question['member_id'], question['request_key'])).fetchone()


def _route_owner_question(db, question):
    """Continue the original authorized question inside its ownership transaction."""
    if question['routing_state'] == 'closed':
        return
    target = db.execute('SELECT * FROM tasks WHERE id=? AND room_id=?',
                         (question['target_task_id'], question['room_id'])).fetchone()
    request = db.execute('SELECT * FROM message_requests WHERE id=?', (question['request_id'],)).fetchone()
    state = ('closed' if request and request['resolved_at'] else 'target_cancelled' if target['cancelled_at']
             else 'unassigned' if not target['owner_member_id'] else 'routed')
    if state == 'closed':
        db.execute("UPDATE workflow_questions SET routing_state='closed' WHERE room_id=? AND member_id=? AND request_key=?",
                   (question['room_id'], question['member_id'], question['request_key']))
        return
    if (question['routing_state'] == state and question['target_ownership_epoch'] == target['ownership_epoch']
            and (state != 'routed' and request is None
                 or state == 'routed' and request and request['receiver_member_id'] == target['owner_member_id'])):
        return
    version, request_id, now = question['route_version'] + 1, None, _utc_now()
    if state == 'routed':
        if not question['question_body']:
            raise Conflict('Stored owner question content is unavailable')
        key = 'owner-route:' + hashlib.sha256(json.dumps([question['room_id'], question['member_id'],
                                                         question['request_key'], version]).encode()).hexdigest()
        request_id = db.execute('''INSERT INTO message_requests(room_id,sender_member_id,receiver_member_id,
            initial_receiver_member_id,task_id,context_version,body,request_key,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)''', (question['room_id'], question['member_id'], target['owner_member_id'],
            target['owner_member_id'], target['id'], version, question['question_body'], key, now)).lastrowid
        db.execute('INSERT INTO message_deliveries(request_id,room_id,receiver_member_id) VALUES(?,?,?)',
                   (request_id, question['room_id'], target['owner_member_id']))
        db.execute('INSERT INTO workflow_owner_routes VALUES(?,?,?,?,?,?,?)',
                   (request_id, question['room_id'], question['member_id'], question['request_key'],
                    version, target['ownership_epoch'], now))
    db.execute('''UPDATE workflow_questions SET request_id=?,routing_state=?,route_version=?,target_ownership_epoch=?
        WHERE room_id=? AND member_id=? AND request_key=?''', (request_id, state, version, target['ownership_epoch'],
        question['room_id'], question['member_id'], question['request_key']))


def ownership_changed(db, task_id, *args):
    for question in db.execute('''SELECT * FROM workflow_questions
            WHERE target_task_id=? AND dependency_id IS NULL AND routing_state!='closed' ''', (task_id,)).fetchall():
        _route_owner_question(db, question)


def live_owner_route_sql(alias='r'):
    """Ordinary explicit-member/dependency messages pass; retired owner routes do not."""
    if not isinstance(alias, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', alias):
        raise ValidationError('Expected a SQL table alias')
    return f'''(NOT EXISTS(SELECT 1 FROM workflow_owner_routes ow WHERE ow.request_id={alias}.id)
        OR EXISTS(SELECT 1 FROM workflow_owner_routes ow JOIN workflow_questions oq
            ON oq.room_id=ow.room_id AND oq.member_id=ow.member_id AND oq.request_key=ow.request_key
            JOIN tasks ot ON ot.id=oq.target_task_id AND ot.room_id=oq.room_id
            WHERE ow.request_id={alias}.id AND oq.request_id={alias}.id AND oq.routing_state='routed'
                AND ot.cancelled_at IS NULL AND ot.owner_member_id={alias}.receiver_member_id
                AND ot.ownership_epoch=ow.target_ownership_epoch))'''


def request_route_info(db, request_id):
    if type(request_id) is not int:
        return None
    row = db.execute('''SELECT ow.route_version,oq.route_version AS current_route_version,
        oq.request_id AS current_request_id,oq.target_task_id,oq.routing_state,''' + live_owner_route_sql('r') + ''' AS live
        FROM workflow_owner_routes ow JOIN workflow_questions oq
            ON oq.room_id=ow.room_id AND oq.member_id=ow.member_id AND oq.request_key=ow.request_key
        JOIN message_requests r ON r.id=ow.request_id WHERE ow.request_id=?''', (request_id,)).fetchone()
    if row is None:
        return None
    return {'current': bool(row['live']), 'state': 'current' if row['live'] else
            'closed' if row['current_request_id'] == request_id and row['routing_state'] == 'closed' else 'historical',
            **{k: row[k] for k in ('current_request_id', 'target_task_id', 'route_version', 'current_route_version')}}


def queued_owner_questions(db, p):
    rows = db.execute('''SELECT q.*,t.title AS target_title,t.scope FROM workflow_questions q
        JOIN tasks t ON t.id=q.target_task_id AND t.room_id=q.room_id
        WHERE q.room_id=? AND q.member_id=? AND q.dependency_id IS NULL
            AND q.routing_state IN('unassigned','target_cancelled') ORDER BY q.created_at,q.request_key''',
        (p.room_id, p.member_id)).fetchall()
    return [{'question_key': r['request_key'], 'requester_member_id': r['member_id'],
             'body': r['question_body'], 'status': r['routing_state'], 'current_request_id': r['request_id'],
             'wait_reason': 'awaiting_owner' if r['routing_state'] == 'unassigned' else 'target_cancelled',
             **{k: r[k] for k in ('target_task_id', 'target_title', 'scope', 'routing_state', 'route_version', 'created_at')}}
            for r in rows]


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
            domain_key = 'owner-question:' + hashlib.sha256(
                (p.member_id + ':' + request_key).encode()).hexdigest()
            dependency_id = request_id = None
            if source_task_id is not None:
                dep = self.service.dependencies.create_in_connection(db, p, source_task_id,
                    target['id'], body, expected_revision, domain_key, context, session_key, ownership_epoch)
                dependency_id = dep['id']
            db.execute('''INSERT INTO workflow_questions(room_id,member_id,request_key,payload_hash,
                target_task_id,initial_owner,initial_revision,dependency_id,request_id,created_at,question_body)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (p.room_id, p.member_id, request_key, digest, target['id'],
                 target['owner_member_id'], target['revision'], dependency_id, request_id, _utc_now(),
                 body + ('\n' + context if context else '')))
            saved = db.execute('''SELECT * FROM workflow_questions
                WHERE room_id=? AND member_id=? AND request_key=?''',
                (p.room_id, p.member_id, request_key)).fetchone()
            return self._question_result(db, p, saved)

    def _question_result(self, db, p, saved):
        target = task_row(db, p, saved['target_task_id'])
        dep = project_dependency(db, dependency_row(db, p, saved['dependency_id'])) if saved['dependency_id'] else None
        if dep is None:
            _route_owner_question(db, saved)
            saved = _question_row(db, saved)
        request_id = dep['current_request_id'] if dep else saved['request_id']
        request = (self.service.messages._enrich(db, self.service.messages._request(db, p, request_id))
                   if request_id else None)
        return {
            'status': 'closed' if not dep and saved['routing_state'] == 'closed' else
                      'delivered' if request else dep['routing_state'] if dep else saved['routing_state'],
            'target': {key: target[key] for key in ('id', 'title', 'scope', 'owner_member_id',
                                                   'revision', 'execution_session_key', 'ownership_epoch')},
            'target_changed': (target['owner_member_id'], target['revision']) !=
                              (saved['initial_owner'], saved['initial_revision']),
            'routing': 'task_dependency' if dep else 'task_owner',
            'routing_state': dep['routing_state'] if dep else saved['routing_state'],
            'route_version': dep['route_version'] if dep else saved['route_version'],
            'current_request_id': request_id,
            'route': request_route_info(db, request_id) if request_id else None,
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
                owner_route = request_route_info(db, row['request_id'])
                if owner_route:
                    item.update(route_state=owner_route['state'], owner_route_state=owner_route['state'],
                                owner_target_task_id=owner_route['target_task_id'])
                item['read_at'] = db.execute('''SELECT read_at FROM workflow_reply_reads
                    WHERE room_id=? AND member_id=? AND reply_id=?''',
                    (p.room_id, p.member_id, row['id'])).fetchone()[0]
                result.append(item)
            return {'replies': result, 'next_cursor': result[-1]['id'] if result else after_id,
                    'has_more': len(rows) > limit, 'model_consumption_proven': False}
