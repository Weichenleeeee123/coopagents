"""Durable room invalidations, committed atomically with the domain transaction.

This module deliberately uses only the standard library and domain interfaces.
"""
from .errors import ValidationError


class EventStore:
    MAX_PAGE = 200

    def __init__(self, identity):
        self.identity, self.db = identity, identity.db
        with self.db.connect(write=True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS room_event_streams (
                room_id TEXT PRIMARY KEY, high_water INTEGER NOT NULL DEFAULT 0,
                floor INTEGER NOT NULL DEFAULT 0)''')
            c.execute('''CREATE TABLE IF NOT EXISTS room_change_events (
                id INTEGER NOT NULL, room_id TEXT NOT NULL, topic TEXT NOT NULL,
                entity_id TEXT NOT NULL, action TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY(room_id,id))''')
        self.install_triggers()

    def install_triggers(self):
        """Install after stores initialize; never backfill historical business rows."""
        direct = {
            'tasks': ('tasks', 'id'), 'progress': ('progress', 'task_id'),
            'sessions': ('sessions', 'id'), 'harness_sessions': ('sessions', 'id'),
            'session_capabilities': ('sessions', 'session_key'), 'capability_verifications': ('capabilities', 'id'), 'members': ('identity', 'id'),
            'rooms': ('room', 'id'), 'message_requests': ('messages', 'id'),
            'message_receipts': ('messages', 'request_id'),
            'message_deliveries': ('messages', 'request_id'),
            'message_replies': ('messages', 'request_id'),
            'contracts': ('contracts', 'id'), 'contract_versions': ('contracts', 'contract_id'),
            'contract_decisions': ('contracts', 'contract_id'), 'contract_events': ('contracts', 'contract_id'),
            'task_lifecycle_events': ('lifecycle', 'task_id'), 'task_handoffs': ('lifecycle', 'task_id'),
            'task_session_bindings': ('lifecycle', 'task_id'),
            'task_dependencies': ('dependencies', 'id'), 'dependency_events': ('dependencies', 'dependency_id'),
            'collaboration_checkpoints': ('collaboration', 'id'),
            'collaboration_diagnostics': ('collaboration', 'diagnostic_id'),
            'repo_bindings': ('git', 'room_id'), 'git_observations': ('git', 'id'),
            'github_connections': ('git', 'room_id'), 'github_refs': ('git', 'id'),
            'github_commit_refs': ('git', 'id'), 'github_release_refs': ('git', 'id'),
            'github_evidence': ('git', 'room_id'), 'delivery_suggestions': ('git','id'),
            'project_members': ('identity', 'member_id'),
        }
        with self.db.connect(write=True) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, (topic, entity) in direct.items():
                if table not in tables:
                    continue
                columns = {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
                if entity not in columns or ('room_id' if table != 'rooms' else 'id') not in columns:
                    raise RuntimeError(f'Event trigger schema mismatch: {table}')
                self._triggers(c, table, topic, f'SELECT {{row}}.{"id" if table == "rooms" else "room_id"} AS room_id', entity)
            self._triggers(c, 'credentials', 'identity', 'SELECT room_id FROM members WHERE id={row}.member_id', 'member_id')
            for table in ('dependency_routes', 'dependency_reads'):
                self._triggers(c, table, 'dependencies', 'SELECT room_id FROM task_dependencies WHERE id={row}.dependency_id', 'dependency_id')
            self._triggers(c, 'dependency_reply_actors', 'dependencies', 'SELECT room_id FROM message_replies WHERE id={row}.reply_id', 'reply_id')
            if 'account_sessions' in tables and 'session_project_credentials' in tables:
                self._triggers(c, 'account_sessions', 'identity', '''SELECT DISTINCT m.room_id FROM members m
                    JOIN credentials cr ON cr.member_id=m.id JOIN session_project_credentials sp ON sp.credential_hash=cr.token_hash
                    WHERE sp.session_hash={row}.token_hash''', None)
                self._triggers(c, 'team_members', 'identity', '''SELECT DISTINCT p.room_id FROM project_members p
                    JOIN team_projects t ON t.room_id=p.room_id WHERE t.team_id={row}.team_id
                    AND p.account_id={row}.account_id''', None)

    @staticmethod
    def _triggers(c, table, topic, room_select, entity):
        # Table/column expressions are a closed, internal allowlist. Never token-derived SQL.
        for action, row in (('insert', 'NEW'), ('update', 'NEW'), ('delete', 'OLD')):
            rooms = room_select.format(row=row)
            entity_sql = f'CAST({row}.{entity} AS TEXT)' if entity else 'stream.room_id'
            c.execute(f'''CREATE TRIGGER IF NOT EXISTS change_{table}_{action} AFTER {action.upper()} ON {table}
                BEGIN
                  INSERT INTO room_event_streams(room_id,high_water)
                    SELECT room_id,1 FROM ({rooms}) WHERE room_id IS NOT NULL
                    ON CONFLICT(room_id) DO UPDATE SET high_water=high_water+1;
                  INSERT INTO room_change_events(id,room_id,topic,entity_id,action)
                    SELECT stream.high_water,stream.room_id,'{topic}',{entity_sql},'{action}'
                    FROM room_event_streams stream WHERE stream.room_id IN ({rooms});
                END''')

    def read(self, token, after_id=0, limit=100):
        if type(after_id) is not int or not 0 <= after_id < 2**63:
            raise ValidationError('Event cursor must be a nonnegative integer')
        if type(limit) is not int or not 1 <= limit <= self.MAX_PAGE:
            raise ValidationError('Event limit must be between 1 and 200')
        with self.db.connect() as c:
            # One read transaction holds authentication and page/high-water in one snapshot.
            c.execute('BEGIN')
            principal = self.identity.resolve(c, token)
            stream = c.execute('SELECT high_water,floor FROM room_event_streams WHERE room_id=?', (principal.room_id,)).fetchone()
            high, floor = (stream['high_water'], stream['floor']) if stream else (0, 0)
            reset = 'future_cursor' if after_id > high else 'expired_cursor' if after_id < floor else None
            events = [] if reset else [dict(r) for r in c.execute('''SELECT id,room_id,topic,entity_id,action,created_at
                FROM room_change_events WHERE room_id=? AND id>? ORDER BY id LIMIT ?''', (principal.room_id, after_id, limit))]
            cursor = high if reset else events[-1]['id'] if events else after_id
            return {'events': events, 'cursor': cursor, 'high_water': high, 'has_more': cursor < high, 'reset': reset}
