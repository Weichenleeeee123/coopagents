"""Durable per-profile bridge events and the wake watcher's read-only cursor."""
from contextlib import closing, contextmanager
import json
import sqlite3

from .spaces import checked_path, private_directory, protect


EVENT_CACHE_FILENAME = 'bridge-events.sqlite3'


def bridge_cursor(profile_path):
    """High-water cursor of the bridge's event cache, or None when unavailable."""
    path = checked_path(profile_path).with_name(EVENT_CACHE_FILENAME)
    if not path.exists():
        return None
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)) as connection:
            row = connection.execute('SELECT cursor FROM state').fetchone()
            return row[0] if row else None
    except sqlite3.Error:
        return None


class EventCache:
    """A bounded private SQLite cache; receiving never acknowledges a message."""
    def __init__(self, profile_path, room_id, member_id, capacity=400):
        self.path = checked_path(profile_path).with_name(EVENT_CACHE_FILENAME)
        private_directory(self.path.parent)
        self.room_id, self.member_id, self.capacity = room_id, member_id, capacity
        if not self.path.exists():
            try:
                with self.path.open('xb'):
                    protect(self.path)
            except FileExistsError:
                pass
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('CREATE TABLE IF NOT EXISTS state(room TEXT, member TEXT, cursor INTEGER, floor INTEGER, reset TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
            # A constant-key unique index enforces one identity without
            # rewriting an existing private cache schema or removing files.
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS state_singleton ON state((1))')
            row = c.execute('SELECT room,member FROM state').fetchone()
            if row and tuple(row) != (room_id, member_id):
                raise ValueError('Event cache identity does not match profile')
            if not row:
                c.execute('INSERT INTO state VALUES(?,?,0,0,NULL)', (room_id, member_id))
        protect(self.path)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @property
    def cursor(self):
        with self.connect() as c:
            return c.execute('SELECT cursor FROM state').fetchone()[0]

    def receive(self, frame, *, expected_after_id=None):
        cursor = frame.get('cursor')
        if type(cursor) is not int or not 0 <= cursor < 2**63:
            raise ValueError('Invalid event cursor')
        with self.connect() as c:
            # Multiple native processes may share this personal profile. Lock
            # before reading the durable cursor so overlapping pages cannot
            # overwrite a cursor advanced by another consumer.
            c.execute('BEGIN IMMEDIATE')
            previous = c.execute('SELECT cursor FROM state').fetchone()[0]
            if frame['type'] == 'reset':
                reason = frame.get('reason')
                if reason not in ('future_cursor', 'expired_cursor'):
                    raise ValueError('Invalid event reset')
                # A reset belongs to the cursor requested by this particular
                # stream. A second process may have advanced the shared cache
                # since that request. Reconnect with its new cursor instead of
                # clearing that progress. A fresh server rollback still applies.
                if expected_after_id is not None and expected_after_id != previous:
                    return False
                c.execute('DELETE FROM events')
                c.execute('UPDATE state SET cursor=?,floor=?,reset=?', (cursor, cursor, reason))
                return True
            events = frame.get('events')
            if not isinstance(events, list) or len(events) > 200:
                raise ValueError('Invalid event page')
            last = 0
            for event in events:
                keys = {'id', 'room_id', 'topic', 'entity_id', 'action', 'created_at'}
                if (not isinstance(event, dict) or set(event) != keys or event['room_id'] != self.room_id
                        or type(event['id']) is not int or not last < event['id'] <= cursor
                        or any(not isinstance(event[k], str) or len(event[k]) > 512 for k in keys - {'id'})):
                    raise ValueError('Invalid room invalidation')
                last = event['id']
                # Validate even duplicate invalidations, but don't restore
                # already expired rows or reject ordinary shared-cache replay.
                if last > previous:
                    c.execute('INSERT OR IGNORE INTO events VALUES(?,?)', (last, json.dumps(event)))
            if events and last != cursor or not events and cursor > previous:
                raise ValueError('Cursor does not match event page')
            removed = c.execute('SELECT id FROM events ORDER BY id DESC LIMIT -1 OFFSET ?', (self.capacity,)).fetchall()
            if removed:
                floor = max(r[0] for r in removed)
                c.execute('DELETE FROM events WHERE id<=?', (floor,))
                c.execute("UPDATE state SET floor=?,reset='local_cache_expired'", (floor,))
            c.execute('UPDATE state SET cursor=?', (max(cursor, previous),))
            return True

    def read(self, after_id=0, limit=100):
        if type(after_id) is not int or not 0 <= after_id < 2**63 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('Expected nonnegative after_id and limit between 1 and 200')
        with self.connect() as c:
            c.execute('BEGIN')
            high, floor, reason = c.execute('SELECT cursor,floor,reset FROM state').fetchone()
            reset = 'future_cursor' if after_id > high else reason if after_id < floor else None
            events = [] if reset else [json.loads(r[0]) for r in c.execute('SELECT body FROM events WHERE id>? ORDER BY id LIMIT ?', (after_id,limit))]
            cursor = high if reset else events[-1]['id'] if events else after_id
            return dict(events=events, cursor=cursor, high_water=high, has_more=cursor < high, reset=reset,
                        room_id=self.room_id, model_read_acknowledged=False)
