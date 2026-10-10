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
