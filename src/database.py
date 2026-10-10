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
