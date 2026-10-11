"""Room-scoped tasks with transactional, exclusive agent ownership."""
from datetime import datetime, timezone
import json

from .errors import Conflict, NotFound, ValidationError
from .task_lifecycle import project_task, task_row, ownership_changed, archive_claim


def _text(value, field, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValidationError(f"{field} must contain 1 to {maximum} characters")
    return value.strip()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, identity_store):
        self.db = identity_store.db
        self.resolve = identity_store.resolve

    def create_task(self, web_token, intent_key, title, scope):
        intent_key = _text(intent_key, "Intent key", 200)
        title = _text(title, "Title", 200)
        scope = _text(scope, "Scope", 500)
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, web_token, required_kind="web")
            existing = connection.execute(
                "SELECT * FROM tasks WHERE room_id = ? AND intent_key = ?",
                (principal.room_id, intent_key),
            ).fetchone()
            if existing is not None:
                if existing["title"] != title or existing["scope"] != scope:
                    raise Conflict("Intent key already has a different task payload")
                return project_task(existing)
            cursor = connection.execute("""INSERT INTO tasks
                (room_id, intent_key, title, scope, state, created_at, creator_member_id)
                VALUES (?, ?, ?, ?, 'open', ?, ?)""",
                (principal.room_id, intent_key, title, scope, _utc_now(), principal.member_id),
            )
            return project_task(connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone())

    def list_tasks(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            return [project_task(row) for row in connection.execute(
                "SELECT * FROM tasks WHERE room_id = ? ORDER BY id ASC", (principal.room_id,),
            )]

    def claim_task(self, agent_token, task_id, session_key=None):
        if session_key is not None:
            session_key = _text(session_key, "Session key", 200)
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            row = task_row(connection, principal, task_id)
            if row['cancelled_at']:
                raise Conflict('Task is cancelled; reopen it first')
            if row['owner_member_id'] is not None and row['owner_member_id'] != principal.member_id:
                raise Conflict('Task already claimed', owner_member_id=row['owner_member_id'])
            if row['execution_session_key']:
                if session_key != row['execution_session_key']:
                    raise Conflict('Task already bound to another execution session')
                return project_task(row)
            if row['owner_member_id'] == principal.member_id and session_key is None:
                return project_task(row)
            if session_key and connection.execute('''SELECT 1 FROM task_session_bindings
                WHERE task_id=? AND member_id=? AND session_key=?''', (task_id,principal.member_id,session_key)).fetchone():
                raise Conflict('Retired session key cannot be reused; start a new session')
            fresh = row['owner_member_id'] is None
            epoch = row['ownership_epoch'] + int(fresh)
            now = _utc_now()
            event_id = archive_claim(connection, principal, row, now) if fresh else None
            connection.execute('''UPDATE tasks SET state='claimed',owner_member_id=?,claimed_at=COALESCE(claimed_at,?),
                revision=revision+1,ownership_epoch=?,execution_session_key=?,epoch_started_at=COALESCE(epoch_started_at,?)
                WHERE id=?''', (principal.member_id,now,epoch,session_key,now,task_id))
            if session_key:
                connection.execute('INSERT INTO task_session_bindings VALUES(?,?,?,?,?,?)',
                    (task_id,principal.room_id,principal.member_id,session_key,epoch,now))
            if fresh:
                ownership_changed(connection, task_id, None, principal.member_id, principal.member_id, principal.kind, "Task claimed")
            result = project_task(task_row(connection, principal, task_id))
            if event_id:
                connection.execute('UPDATE task_lifecycle_events SET result_json=? WHERE id=?', (json.dumps(result),event_id))
            return result
