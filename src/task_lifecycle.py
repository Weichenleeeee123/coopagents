"""Transactional task ownership, explicit human handoffs and retained epoch history."""
from functools import partial
import hashlib
import json
from uuid import uuid4

from .errors import AccessDenied, Conflict, NotFound, ValidationError

ACTIONS = ('release_task', 'propose_handoff', 'accept_handoff', 'reject_handoff',
           'force_handoff', 'cancel_task', 'reopen_task')


def initialize(db):
    columns = {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}
    for name, definition in {
        'revision':'INTEGER NOT NULL DEFAULT 0', 'ownership_epoch':'INTEGER NOT NULL DEFAULT 0',
        'execution_session_key':'TEXT', 'cancelled_at':'TEXT', 'creator_member_id':'TEXT',
        'last_owner_member_id':'TEXT', 'epoch_started_at':'TEXT',
    }.items():
        if name not in columns:
            db.execute(f'ALTER TABLE tasks ADD COLUMN {name} {definition}')
    db.execute('''CREATE TABLE IF NOT EXISTS task_lifecycle_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, task_id INTEGER NOT NULL,
        actor_member_id TEXT NOT NULL, actor_kind TEXT NOT NULL, action TEXT NOT NULL,
        request_key TEXT NOT NULL, payload_hash TEXT NOT NULL, summary TEXT NOT NULL,
        from_owner_member_id TEXT, to_owner_member_id TEXT, ownership_epoch INTEGER NOT NULL,
        revision INTEGER NOT NULL, created_at TEXT NOT NULL, context_json TEXT NOT NULL,
        result_json TEXT NOT NULL,
        UNIQUE(room_id,actor_member_id,request_key),
        FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS task_handoffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, task_id INTEGER NOT NULL,
        from_member_id TEXT NOT NULL, target_member_id TEXT NOT NULL, proposed_by TEXT NOT NULL,
        summary TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT,
        FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id),
        FOREIGN KEY(target_member_id,room_id) REFERENCES members(id,room_id))''')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS task_pending_handoff ON task_handoffs(task_id) WHERE status='pending'")
    db.execute('''CREATE TABLE IF NOT EXISTS task_session_bindings (
        task_id INTEGER NOT NULL, room_id TEXT NOT NULL, member_id TEXT NOT NULL,
        session_key TEXT NOT NULL, ownership_epoch INTEGER NOT NULL, bound_at TEXT NOT NULL,
        PRIMARY KEY(task_id,member_id,session_key),
        FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')


def project_task(row):
    item = dict(row)
    if item['cancelled_at']:
        item['state'] = 'cancelled'
    return item


def task_row(db, principal, task_id):
    if type(task_id) is not int or not 0 < task_id < 2**63:
        raise ValidationError('Task id must be a positive integer')
    task = db.execute('SELECT * FROM tasks WHERE room_id=? AND id=?', (principal.room_id, task_id)).fetchone()
    if task is None:
        raise NotFound('Task not found')
    return task


def execution_task(db, principal, task_id, session_key=None, ownership_epoch=None):
    task = task_row(db, principal, task_id)
    if task['cancelled_at']:
        raise Conflict('Task is cancelled; reopen it before working')
    if task['state'] != 'claimed' or task['owner_member_id'] != principal.member_id:
        raise AccessDenied('Claimed task owner required')
    if ownership_epoch is not None and (type(ownership_epoch) is not int or ownership_epoch != task['ownership_epoch']):
        raise Conflict('Ownership epoch changed; refresh the task before reporting')
    if task['execution_session_key']:
        if session_key != task['execution_session_key'] or ownership_epoch != task['ownership_epoch']:
            raise Conflict('Current execution session and ownership_epoch required')
    elif task['ownership_epoch'] > 1 or task['last_owner_member_id'] is not None:
        raise Conflict('Bind a new execution session with claim_task before reporting after a lifecycle change')
    return task


def manager(identity, db, principal):
    from .repositories import require_manager
    try:
        require_manager(identity, db, principal)
        return True
    except AccessDenied:
        return False


def has_table(db, table):
    return db.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone() is not None


def context_for(db, task):
    """Full audit context is stored before removing any active projection."""
    task_id = task['id']
    progress = db.execute('SELECT * FROM progress WHERE task_id=?', (task_id,)).fetchone()
    result = {'task': project_task(task), 'progress': dict(progress) if progress else None,
              'sessions': [dict(r) for r in db.execute('SELECT * FROM sessions WHERE task_id=?', (task_id,))]}
    if has_table(db, 'harness_sessions'):
        result['sessions'].extend(dict(r) for r in db.execute('SELECT * FROM harness_sessions WHERE task_id=?',(task_id,)))
    for table in ('collaboration_checkpoints', 'github_refs', 'github_commit_refs', 'github_release_refs'):
        result[table] = [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE task_id=?', (task_id,))] if has_table(db, table) else []
    # Immutable observations remain queryable in their original table; retain only branch context here.
    result['git_observations'] = [dict(r) for r in db.execute('''SELECT id,branch,head,received_at,ownership_epoch
        FROM git_observations WHERE task_id=? AND ownership_epoch=? ORDER BY id DESC LIMIT 20''',
        (task_id,task['ownership_epoch']))] if has_table(db,'git_observations') else []
    if has_table(db, 'github_evidence'):
        evidence = db.execute('SELECT deliveries_json FROM github_evidence WHERE room_id=?', (task['room_id'],)).fetchone()
        result['deliveries'] = [r for r in json.loads(evidence[0]) if r['task_id']==task_id and r.get('ownership_epoch',0)==task['ownership_epoch']] if evidence else []
    return result


def retire_execution(db, task):
    # The caller has durably inserted context_json in this same transaction.
    # FK-bearing active records must be detached before tasks.owner_member_id changes.
    # Legacy tasks can have several registered sessions without an exclusive binding.
    # Retire every known task session before detaching it, preserving current legacy
    # behavior until an actual lifecycle boundary occurs.
    for table in ('sessions', 'harness_sessions', 'collaboration_checkpoints'):
        if has_table(db, table):
            db.execute(f'''INSERT OR IGNORE INTO task_session_bindings
                (task_id,room_id,member_id,session_key,ownership_epoch,bound_at)
                SELECT task_id,room_id,member_id,session_key,?,updated_at FROM {table} WHERE task_id=?''',
                (task['ownership_epoch'],task['id']))
    db.execute('DELETE FROM progress WHERE task_id=?', (task['id'],))
    db.execute('UPDATE sessions SET task_id=NULL WHERE task_id=?', (task['id'],))
    if has_table(db, 'harness_sessions'):
        db.execute('UPDATE harness_sessions SET task_id=NULL WHERE task_id=?',(task['id'],))
    if has_table(db, 'collaboration_checkpoints'):
        db.execute('UPDATE collaboration_checkpoints SET task_id=NULL WHERE task_id=?', (task['id'],))
    for table in ('github_refs', 'github_commit_refs', 'github_release_refs'):
        if has_table(db, table):
            db.execute(f'DELETE FROM {table} WHERE task_id=?', (task['id'],))
    if has_table(db, 'github_connections'):
        # In-flight GitHub fetches cannot commit their old reference snapshot.
        db.execute('UPDATE github_connections SET revision=revision+1 WHERE room_id=?', (task['room_id'],))


def archive_claim(db, principal, task, now):
    """Claim keeps its legacy atomic API while auditing any pre-claim evidence."""
    context = context_for(db, task)
    cursor = db.execute('''INSERT INTO task_lifecycle_events
        (room_id,task_id,actor_member_id,actor_kind,action,request_key,payload_hash,summary,
         from_owner_member_id,to_owner_member_id,ownership_epoch,revision,created_at,context_json,result_json)
         VALUES(?,?,?,'agent','claim_task',?,'','Agent claimed the task',?,?,?,?,?,?,?)''',
        (principal.room_id,task['id'],principal.member_id,'claim:'+str(uuid4()),task['owner_member_id'],
         principal.member_id,task['ownership_epoch'],task['revision']+1,now,json.dumps(context),'{}'))
    retire_execution(db, task)
    return cursor.lastrowid


def ownership_changed(db, task_id, old_owner, new_owner, actor=None, kind="system", reason="Task responsibility changed"):
    from .dependencies import ownership_changed as route_dependencies
    route_dependencies(db, task_id, old_owner, new_owner, actor, kind, reason)


class TaskLifecycleStore:
    def __init__(self, identity):
        self.identity, self.db = identity, identity.db
        for action in ACTIONS:
            setattr(self, action, partial(self.transition, action=action))

    def transition(self, token, task_id, expected_revision, request_key, summary, *, action,
                   target_member_id=None, session_key=None, ownership_epoch=None):
        from .tasks import _text, _utc_now
        request_key = _text(request_key, 'Request key', 200)
        summary = _text(summary, 'Handoff summary', 4000)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValidationError('Expected revision must be a nonnegative integer')
        if action not in ACTIONS:
            raise ValidationError('Unknown lifecycle action')
        payload = [action, task_id, expected_revision, summary, target_member_id, session_key, ownership_epoch]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.db.connect(write=True) as db:
            principal = self.identity.resolve(db, token)
            if action not in ('release_task', 'propose_handoff') and principal.kind != 'web':
                raise AccessDenied('Explicit human web decision required')
            task = task_row(db, principal, task_id)
            prior = db.execute('''SELECT * FROM task_lifecycle_events
                WHERE room_id=? AND actor_member_id=? AND request_key=?''',
                (principal.room_id, principal.member_id, request_key)).fetchone()
            if prior:
                if prior['payload_hash'] != digest or prior['actor_kind'] != principal.kind:
                    raise Conflict('Request key already has another payload')
                return json.loads(prior['result_json'])
            if task['revision'] != expected_revision:
                raise Conflict('Task revision changed; refresh and review the current handoff context')
            is_manager = manager(self.identity, db, principal)
            own = task['owner_member_id'] == principal.member_id
            pending = db.execute("SELECT * FROM task_handoffs WHERE task_id=? AND status='pending'", (task_id,)).fetchone()
            if action in ('accept_handoff', 'reject_handoff'):
                if not pending or pending['target_member_id'] != principal.member_id:
                    raise AccessDenied('Only the proposed recipient may accept or reject')
            elif action == 'force_handoff':
                if not is_manager:
                    raise AccessDenied('Project manager required for forced handoff')
            elif principal.kind == 'agent':
                execution_task(db, principal, task_id, session_key, ownership_epoch)
            elif not (is_manager or own or (not task['owner_member_id'] and principal.member_id in
                     (task['creator_member_id'], task['last_owner_member_id']))):
                raise AccessDenied('Task owner, creator of an open task, or project manager required')
            if action == 'reopen_task':
                if not task['cancelled_at']:
                    raise Conflict('Only cancelled tasks can be reopened')
            elif task['cancelled_at']:
                raise Conflict('Task is cancelled; reopen it first')
            if action in ('release_task', 'propose_handoff', 'accept_handoff', 'reject_handoff', 'force_handoff') and task['state'] != 'claimed':
                raise Conflict('Only a claimed task can be released or handed off')
            if action in ('propose_handoff', 'force_handoff'):
                if not isinstance(target_member_id, str) or not db.execute(
                    'SELECT 1 FROM members WHERE room_id=? AND id=?', (principal.room_id, target_member_id)).fetchone():
                    raise NotFound('Target member not found in project')
                if has_table(db, 'team_projects') and db.execute('SELECT 1 FROM team_projects WHERE room_id=?', (principal.room_id,)).fetchone():
                    mapping = db.execute('''SELECT p.active,t.active AS team_active FROM project_members p
                        JOIN team_projects r ON r.room_id=p.room_id
                        LEFT JOIN team_members t ON t.team_id=r.team_id AND t.account_id=p.account_id
                        WHERE p.room_id=? AND p.member_id=?''', (principal.room_id,target_member_id)).fetchone()
                    # Team adoption deliberately preserves unmapped legacy collaborators.
                    # Mapped accounts require both membership grants to remain active.
                    if mapping is not None and (not mapping['active'] or not mapping['team_active']):
                        raise AccessDenied('Active target project membership required')
                if target_member_id == task['owner_member_id']:
                    raise Conflict('Target already owns the task')
            if action == 'propose_handoff' and pending:
                raise Conflict('A handoff is already pending; recipient must accept or reject it')
            context = context_for(db, task)
            now = _utc_now()
            next_owner = pending['target_member_id'] if action == 'accept_handoff' else target_member_id if action == 'force_handoff' else None
            changed = action not in ('propose_handoff', 'reject_handoff')
            cursor = db.execute('''INSERT INTO task_lifecycle_events
                (room_id,task_id,actor_member_id,actor_kind,action,request_key,payload_hash,summary,
                 from_owner_member_id,to_owner_member_id,ownership_epoch,revision,created_at,context_json,result_json)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (principal.room_id,task_id,principal.member_id,principal.kind,action,request_key,digest,summary,
                 task['owner_member_id'],next_owner if changed else task['owner_member_id'],task['ownership_epoch'],
                 task['revision']+1,now,json.dumps(context),'{}'))
            if changed:
                retire_execution(db, task)
                db.execute('''UPDATE tasks SET state=?,owner_member_id=?,claimed_at=?,execution_session_key=NULL,
                    ownership_epoch=ownership_epoch+1,epoch_started_at=?,revision=revision+1,
                    cancelled_at=?,last_owner_member_id=COALESCE(owner_member_id,last_owner_member_id) WHERE id=?''',
                    ('claimed' if next_owner else 'open',next_owner,now if next_owner else None,now,
                     now if action=='cancel_task' else None,task_id))
                if pending:
                    db.execute('UPDATE task_handoffs SET status=?,decided_at=? WHERE id=?',
                        ('accepted' if action=='accept_handoff' else 'superseded',now,pending['id']))
                ownership_changed(db, task_id, task['owner_member_id'], next_owner, principal.member_id, principal.kind, action+': '+summary)
            else:
                db.execute('UPDATE tasks SET revision=revision+1 WHERE id=?', (task_id,))
                if action == 'propose_handoff':
                    db.execute('''INSERT INTO task_handoffs(room_id,task_id,from_member_id,target_member_id,
                        proposed_by,summary,status,created_at) VALUES(?,?,?,?,?,?,'pending',?)''',
                        (principal.room_id,task_id,task['owner_member_id'],target_member_id,principal.member_id,summary,now))
                else:
                    db.execute("UPDATE task_handoffs SET status='rejected',decided_at=? WHERE id=?", (now,pending['id']))
            result = project_task(task_row(db, principal, task_id))
            db.execute('UPDATE task_lifecycle_events SET result_json=? WHERE id=?', (json.dumps(result),cursor.lastrowid))
            return result

    @staticmethod
    def _event(row, full=False):
        item = dict(row)
        context = json.loads(item.pop('context_json'))
        item.pop('result_json'); item.pop('payload_hash'); item.pop('request_key')
        if full:
            item['context'] = context
        else:
            item['context'] = {'progress': context['progress'],
                **{key: context.get(key, [])[:5] for key in ('sessions','git_observations','github_refs','github_commit_refs','github_release_refs')},
                'deliveries':[{key:r.get(key) for key in ('branch','pr_number','commit_sha','state','sync_at','ownership_epoch')}
                    for r in context.get('deliveries',[])[:5]]}
            item['context_excerpted'] = True
        return item

    def snapshot(self, token):
        with self.db.connect() as db:
            principal = self.identity.resolve(db, token)
            history = [self._event(r) for r in db.execute('''SELECT * FROM task_lifecycle_events WHERE room_id=?
                ORDER BY id DESC LIMIT 51''', (principal.room_id,))]
            handoffs = [dict(r) for r in db.execute('''SELECT * FROM task_handoffs WHERE room_id=? AND status='pending'
                ORDER BY target_member_id=? DESC,id DESC LIMIT 201''', (principal.room_id,principal.member_id))]
            return {'can_manage': manager(self.identity,db,principal), 'history':history[:50],
                    'history_truncated':len(history)>50,'handoffs':handoffs[:200],'handoffs_truncated':len(handoffs)>200}

    def read_task_history(self, token, task_id, before_id=None, limit=20):
        if type(limit) is not int or not 1<=limit<=50:
            raise ValidationError('History limit must be between 1 and 50')
        if before_id is not None and (type(before_id) is not int or not 0<before_id<2**63):
            raise ValidationError('History cursor must be a positive integer')
        with self.db.connect() as db:
            principal = self.identity.resolve(db, token)
            task = task_row(db,principal,task_id)
            handoff = db.execute("SELECT * FROM task_handoffs WHERE task_id=? AND status='pending'", (task_id,)).fetchone()
            rows = db.execute('''SELECT * FROM task_lifecycle_events WHERE room_id=? AND task_id=?
                AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?''', (principal.room_id,task_id,before_id,before_id,limit+1)).fetchall()
            return {'task':project_task(task),'handoff':dict(handoff) if handoff else None,
                    'events':[self._event(row) for row in rows[:limit]],
                    'next_before_id':rows[limit-1]['id'] if len(rows)>limit else None}

    def history_event(self, token, task_id, event_id):
        with self.db.connect() as db:
            principal = self.identity.resolve(db, token)
            task_row(db, principal, task_id)
            row = db.execute('SELECT * FROM task_lifecycle_events WHERE room_id=? AND task_id=? AND id=?',
                             (principal.room_id,task_id,event_id)).fetchone()
            if row is None:
                raise NotFound('Lifecycle event not found')
            return self._event(row, full=True)
