"""Room-scoped tasks with transactional, exclusive agent ownership."""
from datetime import datetime, timezone

from .errors import Conflict, NotFound, ValidationError


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
                return dict(existing)
            cursor = connection.execute("""INSERT INTO tasks
                (room_id, intent_key, title, scope, state, created_at)
                VALUES (?, ?, ?, ?, 'open', ?)""",
                (principal.room_id, intent_key, title, scope, _utc_now()),
            )
            return dict(connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone())

    def list_tasks(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            return [dict(row) for row in connection.execute(
                "SELECT * FROM tasks WHERE room_id = ? ORDER BY id ASC", (principal.room_id,),
            )]

    def claim_task(self, agent_token, task_id):
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ? AND room_id = ?", (task_id, principal.room_id),
            ).fetchone()
            if row is None:
                raise NotFound("Task not found")
            if row["owner_member_id"] == principal.member_id:
                return dict(row)
            if row["owner_member_id"] is not None:
                raise Conflict("Task already claimed", owner_member_id=row["owner_member_id"])
            connection.execute("""UPDATE tasks SET state = 'claimed', owner_member_id = ?, claimed_at = ?
                WHERE id = ? AND room_id = ? AND owner_member_id IS NULL""",
                (principal.member_id, _utc_now(), task_id, principal.room_id),
            )
            return dict(connection.execute(
                "SELECT * FROM tasks WHERE id = ? AND room_id = ?", (task_id, principal.room_id),
            ).fetchone())
