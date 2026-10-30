"""Explicit agent session heartbeats and self-reported task progress."""
from itertools import combinations
import json

from .errors import AccessDenied, NotFound, ValidationError
from .tasks import _text, _utc_now


LEGACY_TOOLS = ("claude-code", "codex-cli", "codex-desktop")
TOOLS = (*LEGACY_TOOLS, "cursor", "opencode", "pi", "kimi-code", "zcode")
HARNESSES = ('claude-code', 'codex', 'cursor', 'opencode', 'pi', 'kimi-code', 'zcode')
CAPABILITY_STATUSES = ('supported', 'unsupported', 'unknown', 'unavailable', 'stale')
PROGRESS_STATES = ("working", "blocked", "local_done", "pushed", "pr_open", "merged")


def _task_id(value):
    if type(value) is not int or value <= 0:
        raise ValidationError("Task id must be a positive integer")
    return value


class ActivityStore:
    def __init__(self, identity_store):
        self.db = identity_store.db
        self.resolve = identity_store.resolve
        with self.db.connect(write=True) as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS harness_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,room_id TEXT NOT NULL,member_id TEXT NOT NULL,
                session_key TEXT NOT NULL,tool TEXT NOT NULL,repository TEXT NOT NULL,branch TEXT NOT NULL,
                task_id INTEGER,updated_at TEXT NOT NULL,UNIQUE(room_id,member_id,session_key),
                FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
                FOREIGN KEY(task_id,room_id,member_id) REFERENCES tasks(id,room_id,owner_member_id))''')
            connection.execute('''CREATE TABLE IF NOT EXISTS session_capabilities (
                room_id TEXT NOT NULL, member_id TEXT NOT NULL, session_key TEXT NOT NULL,
                harness TEXT NOT NULL, version TEXT NOT NULL, platform TEXT NOT NULL,
                capabilities_json TEXT NOT NULL, evidence_source TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(room_id, member_id, session_key),
                FOREIGN KEY(member_id, room_id) REFERENCES members(id, room_id))''')

            if 'credential_hash' not in {r['name'] for r in connection.execute('PRAGMA table_info(session_capabilities)')}:
                connection.execute('ALTER TABLE session_capabilities ADD COLUMN credential_hash TEXT')

    def _owned_task(self, connection, principal, task_id, session_key=None, ownership_epoch=None):
        from .task_lifecycle import execution_task
        return execution_task(connection, principal, task_id, session_key, ownership_epoch)

    def register_session(self, agent_token, session_key, tool, repository, branch, task_id=None, ownership_epoch=None,
                         harness=None, harness_version='unknown', platform='unknown', capabilities=None):
        session_key = _text(session_key, "Session key", 200)
        repository = _text(repository, "Repository", 500)
        branch = _text(branch, "Branch", 200)
        if tool not in TOOLS:
            raise ValidationError("Unsupported coding agent tool")
        harness = harness or ('codex' if tool.startswith('codex') else tool)
        if harness not in HARNESSES or harness != ('codex' if tool.startswith('codex') else tool):
            raise ValidationError('Unsupported Harness')
        harness_version = _text(harness_version, 'Harness version', 100)
        platform = _text(platform, 'Platform', 60)
        capabilities = {} if capabilities is None else capabilities
        if not isinstance(capabilities, dict) or len(capabilities) > 32:
            raise ValidationError('Capabilities must be an object with at most 32 entries')
        if any(not isinstance(key, str) or not 1 <= len(key) <= 100 or not isinstance(value, str)
               or value not in CAPABILITY_STATUSES for key, value in capabilities.items()):
            raise ValidationError('Capability entries must use bounded status values')
        if task_id is not None:
            task_id = _task_id(task_id)
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            if task_id is not None:
                self._owned_task(connection, principal, task_id, session_key, ownership_epoch)
            table = 'sessions' if tool in LEGACY_TOOLS else 'harness_sessions'
            other = 'harness_sessions' if table == 'sessions' else 'sessions'
            if connection.execute(f'SELECT 1 FROM {other} WHERE room_id=? AND member_id=? AND session_key=?',
                                  (principal.room_id,principal.member_id,session_key)).fetchone():
                raise ValidationError('Use a distinct session key when changing Harness family')
            connection.execute(f"""INSERT INTO {table}
                (room_id, member_id, session_key, tool, repository, branch, task_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (room_id, member_id, session_key) DO UPDATE SET
                    tool = excluded.tool, repository = excluded.repository,
                    branch = excluded.branch, task_id = excluded.task_id,
                    updated_at = excluded.updated_at""",
                (principal.room_id, principal.member_id, session_key, tool,
                 repository, branch, task_id, _utc_now()))
            from .identity import _token_hash
            timestamp = _utc_now()
            connection.execute('''INSERT INTO session_capabilities
                (room_id,member_id,session_key,harness,version,platform,capabilities_json,evidence_source,updated_at)
                VALUES (?,?,?,?,?,?,?,'agent_report',?)
                ON CONFLICT(room_id,member_id,session_key) DO UPDATE SET
                    harness=excluded.harness,version=excluded.version,platform=excluded.platform,
                    capabilities_json=excluded.capabilities_json,evidence_source=excluded.evidence_source,updated_at=excluded.updated_at''',
                (principal.room_id, principal.member_id, session_key, harness, harness_version, platform,
                 json.dumps(capabilities, ensure_ascii=True, separators=(',', ':')), timestamp))
            connection.execute('UPDATE session_capabilities SET credential_hash=? WHERE room_id=? AND member_id=? AND session_key=?',
                (_token_hash(agent_token),principal.room_id,principal.member_id,session_key))
            return dict(connection.execute(f"""SELECT * FROM {table}
                WHERE room_id = ? AND member_id = ? AND session_key = ?""",
                (principal.room_id, principal.member_id, session_key)).fetchone())

    def list_capabilities(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            rows = []
            for row in connection.execute('SELECT * FROM session_capabilities WHERE room_id=? ORDER BY updated_at,session_key',
                                          (principal.room_id,)):
                item = dict(row)
                item['capabilities'] = json.loads(item.pop('capabilities_json'))
                key = item.pop('credential_hash',None)
                try:
                    if key:
                        credential = connection.execute('SELECT revoked_at,expires_at FROM credentials WHERE token_hash=?',(key,)).fetchone()
                        from .identity import _expired, _utcnow
                        item['credential_status'] = ('valid' if credential and not credential['revoked_at']
                            and not _expired(credential['expires_at'],_utcnow()) else 'unavailable')
                    else:
                        item['credential_status'] = 'unknown'
                    if self._inactive_member(connection,item['member_id']):
                        item['credential_status'] = 'unavailable'
                except (KeyError,TypeError):
                    item['credential_status'] = 'unknown'
                rows.append(item)
            return rows

    @staticmethod
    def _inactive_member(db, member_id):
        from .identity import IdentityStore
        if not IdentityStore._has_table(db, 'project_members'):
            return False
        row = db.execute("""SELECT p.active,t.active AS team_active FROM project_members p
            JOIN team_projects r ON r.room_id=p.room_id
            JOIN team_members t ON t.team_id=r.team_id AND t.account_id=p.account_id
            WHERE p.member_id=?""",(member_id,)).fetchone()
        return row is not None and (not row['active'] or not row['team_active'])

    def list_sessions(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            legacy = [dict(row) for row in connection.execute(
                "SELECT * FROM sessions WHERE room_id = ? ORDER BY id", (principal.room_id,))]
            extra = [dict(row, id='harness:'+str(row['id'])) for row in connection.execute(
                'SELECT * FROM harness_sessions WHERE room_id=? ORDER BY id', (principal.room_id,))]
            return legacy + extra

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
