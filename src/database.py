"""Short-lived SQLite connections shared by CrewMesh stores."""
from contextlib import contextmanager
import sqlite3


class Database:
    def __init__(self, path):
        self.path = path
        with self.connect(write=True) as connection:
            # Individual statements preserve the surrounding transaction.
            connection.execute("""CREATE TABLE IF NOT EXISTS rooms (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS members (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL REFERENCES rooms(id),
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
                UNIQUE (id, room_id)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS credentials (
                token_hash TEXT PRIMARY KEY,
                member_id TEXT NOT NULL REFERENCES members(id),
                kind TEXT NOT NULL CHECK (kind IN ('web', 'agent')),
                revoked_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL REFERENCES rooms(id),
                intent_key TEXT NOT NULL,
                title TEXT NOT NULL,
                scope TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('open', 'claimed')),
                owner_member_id TEXT,
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                UNIQUE (room_id, intent_key),
                FOREIGN KEY (owner_member_id, room_id) REFERENCES members(id, room_id),
                CHECK ((state = 'open' AND owner_member_id IS NULL AND claimed_at IS NULL)
                    OR (state = 'claimed' AND owner_member_id IS NOT NULL AND claimed_at IS NOT NULL))
            )""")
            # Composite keys let SQLite enforce both room and claimed-owner coherence.
            connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS task_activity_owner
                ON tasks (id, room_id, owner_member_id)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL REFERENCES rooms(id),
                member_id TEXT NOT NULL,
                session_key TEXT NOT NULL,
                tool TEXT NOT NULL CHECK (tool IN ('claude-code', 'codex-cli', 'codex-desktop')),
                repository TEXT NOT NULL,
                branch TEXT NOT NULL,
                task_id INTEGER,
                updated_at TEXT NOT NULL,
                UNIQUE (room_id, member_id, session_key),
                FOREIGN KEY (member_id, room_id) REFERENCES members(id, room_id),
                FOREIGN KEY (task_id, room_id, member_id)
                    REFERENCES tasks(id, room_id, owner_member_id)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS progress (
                task_id INTEGER PRIMARY KEY,
                room_id TEXT NOT NULL REFERENCES rooms(id),
                member_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN
                    ('working', 'blocked', 'local_done', 'pushed', 'pr_open', 'merged')),
                summary TEXT NOT NULL,
                evidence TEXT NOT NULL,
                source TEXT NOT NULL CHECK (source = 'agent_report'),
                updated_at TEXT NOT NULL,
                FOREIGN KEY (member_id, room_id) REFERENCES members(id, room_id),
                FOREIGN KEY (task_id, room_id, member_id)
                    REFERENCES tasks(id, room_id, owner_member_id)
            )""")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS task_room ON tasks(id, room_id)")
            connection.execute("""CREATE TABLE IF NOT EXISTS message_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL REFERENCES rooms(id),
                sender_member_id TEXT NOT NULL,
                receiver_member_id TEXT,
                initial_receiver_member_id TEXT,
                assigned_by_member_id TEXT,
                assigned_at TEXT,
                task_id INTEGER,
                context_version INTEGER NOT NULL CHECK(context_version > 0),
                body TEXT NOT NULL,
                request_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                UNIQUE(room_id, sender_member_id, request_key),
                UNIQUE(id, room_id, receiver_member_id),
                FOREIGN KEY(sender_member_id, room_id) REFERENCES members(id, room_id),
                FOREIGN KEY(receiver_member_id, room_id) REFERENCES members(id, room_id),
                FOREIGN KEY(initial_receiver_member_id, room_id) REFERENCES members(id, room_id),
                FOREIGN KEY(assigned_by_member_id, room_id) REFERENCES members(id, room_id),
                CHECK ((assigned_by_member_id IS NULL AND assigned_at IS NULL)
                    OR (assigned_by_member_id IS NOT NULL AND assigned_at IS NOT NULL
                        AND receiver_member_id IS NOT NULL)),
                FOREIGN KEY(task_id, room_id) REFERENCES tasks(id, room_id)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS message_receipts (
                request_id INTEGER PRIMARY KEY,
                room_id TEXT NOT NULL,
                member_id TEXT NOT NULL,
                read_at TEXT NOT NULL,
                processed_at TEXT,
                FOREIGN KEY(request_id, room_id, member_id)
                    REFERENCES message_requests(id, room_id, receiver_member_id)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS message_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL UNIQUE,
                room_id TEXT NOT NULL,
                receiver_member_id TEXT NOT NULL,
                FOREIGN KEY(request_id, room_id, receiver_member_id)
                    REFERENCES message_requests(id, room_id, receiver_member_id)
            )""")
            # Preserve addressed requests when opening a database predating delivery cursors.
            connection.execute("""INSERT INTO message_deliveries
                (request_id, room_id, receiver_member_id)
                SELECT r.id, r.room_id, r.receiver_member_id FROM message_requests r
                WHERE r.receiver_member_id IS NOT NULL
                    AND NOT EXISTS (SELECT 1 FROM message_deliveries d WHERE d.request_id = r.id)
                ORDER BY r.id
                ON CONFLICT(request_id) DO NOTHING""")
            connection.execute("""CREATE TABLE IF NOT EXISTS message_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                room_id TEXT NOT NULL,
                author_member_id TEXT NOT NULL,
                request_key TEXT NOT NULL,
                context_version INTEGER NOT NULL CHECK(context_version > 0),
                body TEXT NOT NULL,
                evidence TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(room_id, author_member_id, request_key),
                FOREIGN KEY(request_id, room_id, author_member_id)
                    REFERENCES message_requests(id, room_id, receiver_member_id)
            )""")

    @contextmanager
    def connect(self, write=False):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                if write:
                    connection.commit()
            except BaseException:
                if write:
                    connection.rollback()
                raise
        finally:
            connection.close()
