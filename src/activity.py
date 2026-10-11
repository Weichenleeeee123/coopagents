"""Explicit agent session heartbeats and self-reported task progress."""
from itertools import combinations

from .errors import AccessDenied, NotFound, ValidationError
from .tasks import _text, _utc_now


TOOLS = ("claude-code", "codex-cli", "codex-desktop")
PROGRESS_STATES = ("working", "blocked", "local_done", "pushed", "pr_open", "merged")


def _task_id(value):
    if type(value) is not int or value <= 0:
        raise ValidationError("Task id must be a positive integer")
    return value


class ActivityStore:
    def __init__(self, identity_store):
        self.db = identity_store.db
        self.resolve = identity_store.resolve

    def _owned_task(self, connection, principal, task_id, session_key=None, ownership_epoch=None):
        from .task_lifecycle import execution_task
        return execution_task(connection, principal, task_id, session_key, ownership_epoch)

    def register_session(self, agent_token, session_key, tool, repository, branch, task_id=None, ownership_epoch=None):
        session_key = _text(session_key, "Session key", 200)
        repository = _text(repository, "Repository", 500)
        branch = _text(branch, "Branch", 200)
        if tool not in TOOLS:
            raise ValidationError("Tool must be claude-code, codex-cli or codex-desktop")
        if task_id is not None:
            task_id = _task_id(task_id)
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            if task_id is not None:
                self._owned_task(connection, principal, task_id, session_key, ownership_epoch)
            connection.execute("""INSERT INTO sessions
                (room_id, member_id, session_key, tool, repository, branch, task_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (room_id, member_id, session_key) DO UPDATE SET
                    tool = excluded.tool, repository = excluded.repository,
                    branch = excluded.branch, task_id = excluded.task_id,
                    updated_at = excluded.updated_at""",
                (principal.room_id, principal.member_id, session_key, tool,
                 repository, branch, task_id, _utc_now()))
            return dict(connection.execute("""SELECT * FROM sessions
                WHERE room_id = ? AND member_id = ? AND session_key = ?""",
                (principal.room_id, principal.member_id, session_key)).fetchone())

    def list_sessions(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            return [dict(row) for row in connection.execute(
                "SELECT * FROM sessions WHERE room_id = ? ORDER BY id", (principal.room_id,))]

    def report_progress(self, agent_token, task_id, state, summary, evidence="", session_key=None, ownership_epoch=None):
        task_id = _task_id(task_id)
        if state not in PROGRESS_STATES:
            raise ValidationError("Unsupported progress state")
        summary = _text(summary, "Summary", 4000)
        if not isinstance(evidence, str) or len(evidence.strip()) > 1000:
            raise ValidationError("Evidence must contain at most 1000 characters")
        evidence = evidence.strip()
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            self._owned_task(connection, principal, task_id, session_key, ownership_epoch)
            connection.execute("""INSERT INTO progress
                (task_id, room_id, member_id, state, summary, evidence, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'agent_report', ?)
                ON CONFLICT (task_id) DO UPDATE SET member_id = excluded.member_id, state = excluded.state,
                    summary = excluded.summary, evidence = excluded.evidence,
                    updated_at = excluded.updated_at""",
                (task_id, principal.room_id, principal.member_id, state, summary, evidence, _utc_now()))
            return dict(connection.execute("SELECT * FROM progress WHERE task_id = ?",
                                           (task_id,)).fetchone())

    def list_progress(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            return [dict(row) for row in connection.execute(
                "SELECT * FROM progress WHERE room_id = ? ORDER BY task_id", (principal.room_id,))]

    def overlaps(self, token):
        """Compare declared scope strings; this performs no filesystem operations."""
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            tasks = connection.execute("SELECT id, scope FROM tasks WHERE room_id = ? AND cancelled_at IS NULL ORDER BY id",
                                       (principal.room_id,)).fetchall()
            result = []
            for first, second in combinations(tasks, 2):
                left, right = first["scope"].rstrip("/"), second["scope"].rstrip("/")
                reason = None
                if left == right:
                    reason = "Declared scopes are equal"
                elif left and right and (left.startswith(right + "/") or right.startswith(left + "/")):
                    reason = "One declared scope is a slash-segment prefix of the other"
                if reason:
                    result.append({"task_ids": [first["id"], second["id"]],
                                   "scopes": [first["scope"], second["scope"]], "reason": reason})
            return result
