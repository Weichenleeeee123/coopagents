"""Access integration evidence is retained under .local/test-evidence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sqlite3
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from crewmesh.identity import IdentityStore
from crewmesh.errors import AccessDenied, ValidationError


class AccessTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.local' / 'test-evidence'
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f'access-{uuid4()}.sqlite3'
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.clock = patch('crewmesh.identity._utcnow', return_value=self.now, create=True)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.store = IdentityStore(self.path)
        self.owner = self.store.create_room('Room', 'Owner')

    def test_repository_validated_and_persistent(self):
        owner = self.store.create_room('Repo', 'Owner', repository=' git@example:team/repo ')
        info = IdentityStore(self.path).room_info(owner['agent_token'])
        self.assertEqual(info, {'id': owner['room_id'], 'name': 'Repo', 'repository': 'git@example:team/repo'})
        self.assertEqual(self.store.room_info(self.owner['web_token'])['repository'], '')
        for repository in (None, 5, 'x' * 501):
            with self.assertRaises(ValidationError):
                self.store.create_room('Invalid', 'Owner', repository)

    def test_invite_hash_only_single_use_and_expiry(self):
        invite = self.store.create_invite(self.owner['web_token'])
        self.assertEqual(invite['expires_at'], (self.now + timedelta(hours=1)).isoformat())
        with self.store.db.connect() as connection:
            row = connection.execute('SELECT token_hash, used_at FROM invitations').fetchone()
            self.assertEqual(row['token_hash'], hashlib.sha256(invite['invite_token'].encode()).hexdigest())
            self.assertIsNone(row['used_at'])
        member = self.store.join_invite(invite['invite_token'], ' Alice ')
        self.assertEqual(self.store.authenticate(member['web_token']).display_name, 'Alice')
        self.assertEqual(self.store.authenticate(member['agent_token']).role, 'member')
        self.assertEqual(member['room_id'], self.owner['room_id'])
        for token in (invite['invite_token'], 'unknown', '', None):
            with self.assertRaises(AccessDenied) as caught:
                self.store.join_invite(token, 'Bob')
            self.assertEqual(str(caught.exception), 'Invitation not accepted')
        fresh = self.store.create_invite(self.owner['web_token'])
        with patch('crewmesh.identity._utcnow', return_value=self.now + timedelta(hours=1)):
            with self.assertRaises(AccessDenied) as caught:
                self.store.join_invite(fresh['invite_token'], 'Bob')
            self.assertEqual(str(caught.exception), 'Invitation not accepted')
        for token in [invite['invite_token'], fresh['invite_token'], *[v for k, v in member.items() if k.endswith('_token')]]:
            self.assertNotIn(token.encode(), self.path.read_bytes())

    def test_only_owner_web_issues_invites(self):
        peer = self.store.add_member(self.owner['web_token'], 'Peer')
        for token in (self.owner['agent_token'], peer['web_token'], peer['agent_token'], 'unknown'):
            with self.assertRaises(AccessDenied):
                self.store.create_invite(token)
        with self.store.db.connect() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM invitations').fetchone()[0], 0)

    def test_concurrent_join_has_one_winner(self):
        invite = self.store.create_invite(self.owner['web_token'])
        barrier = threading.Barrier(2)
        def join(name):
            barrier.wait(timeout=5)
            try:
                return self.store.join_invite(invite['invite_token'], name)
            except AccessDenied:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(join, ['Alice', 'Bob']))
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(len(self.store.list_members(self.owner['web_token'])), 2)

    def test_new_credential_lifetimes_and_exact_boundary(self):
        with self.store.db.connect() as connection:
            rows = list(connection.execute('SELECT kind, expires_at FROM credentials'))
        for row in rows:
            days = 30 if row['kind'] == 'web' else 90
            expiry = self.now + timedelta(days=days)
            self.assertEqual(row['expires_at'], expiry.isoformat())
            with patch('crewmesh.identity._utcnow', return_value=expiry - timedelta(microseconds=1)):
                self.store.authenticate(self.owner[f"{row['kind']}_token"])
            with patch('crewmesh.identity._utcnow', return_value=expiry):
                with self.assertRaises(AccessDenied):
                    self.store.authenticate(self.owner[f"{row['kind']}_token"])

    def test_legacy_schema_upgrade_preserves_nonexpiring_credentials(self):
        legacy = self.path.with_name(f'legacy-access-{uuid4()}.sqlite3')
        with closing(sqlite3.connect(legacy)) as connection, connection:
            connection.executescript('''CREATE TABLE rooms(id TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE members(id TEXT PRIMARY KEY, room_id TEXT NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(id,room_id));
                CREATE TABLE credentials(token_hash TEXT PRIMARY KEY, member_id TEXT NOT NULL, kind TEXT NOT NULL, revoked_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);''')
            connection.execute("INSERT INTO rooms VALUES ('room', 'Legacy')")
            connection.execute("INSERT INTO members VALUES ('member', 'room', 'Owner', 'owner')")
            connection.execute("INSERT INTO credentials(token_hash, member_id, kind) VALUES (?, 'member', 'web')", (hashlib.sha256(b'legacy-token').hexdigest(),))
        upgraded = IdentityStore(legacy)
        with patch('crewmesh.identity._utcnow', return_value=self.now + timedelta(days=10000)):
            self.assertEqual(upgraded.authenticate('legacy-token').member_id, 'member')
        self.assertEqual(upgraded.room_info('legacy-token')['repository'], '')
        with upgraded.db.connect() as connection:
            self.assertIsNone(connection.execute('SELECT expires_at FROM credentials').fetchone()[0])

    def test_rotation_revokes_all_old_agents_isolates_peers_and_reopens(self):
        peer = self.store.add_member(self.owner['web_token'], 'Peer')
        first = self.store.rotate_agent(self.owner['web_token'])
        second = self.store.rotate_agent(self.owner['web_token'])
        self.assertEqual(set(second), {'agent_token', 'expires_at', 'room_id', 'member_id'})
        self.assertEqual(second['expires_at'], (self.now + timedelta(days=90)).isoformat())
        for token in (self.owner['agent_token'], first['agent_token']):
            with self.assertRaises(AccessDenied):
                self.store.authenticate(token)
        reopened = IdentityStore(self.path)
        self.assertEqual(reopened.authenticate(second['agent_token']).member_id, self.owner['member_id'])
        reopened.authenticate(peer['agent_token'])
        reopened.authenticate(self.owner['web_token'])
        with self.assertRaises(AccessDenied):
            reopened.rotate_agent(second['agent_token'])
        rotated_peer = reopened.rotate_agent(peer['web_token'])
        reopened.authenticate(second['agent_token'])
        self.assertEqual(reopened.authenticate(rotated_peer['agent_token']).member_id, peer['member_id'])
        self.assertNotIn(second['agent_token'].encode(), self.path.read_bytes())

    def test_failed_join_and_rotation_roll_back(self):
        invite = self.store.create_invite(self.owner['web_token'])
        with self.store.db.connect(write=True) as connection:
            connection.execute("CREATE TRIGGER reject_agent BEFORE INSERT ON credentials WHEN NEW.kind = 'agent' BEGIN SELECT RAISE(ABORT, 'injected'); END")
        for operation in (lambda: self.store.join_invite(invite['invite_token'], 'Alice'), lambda: self.store.rotate_agent(self.owner['web_token'])):
            with self.assertRaises(sqlite3.IntegrityError):
                operation()
        self.store.authenticate(self.owner['agent_token'])
        with self.store.db.connect() as connection:
            self.assertIsNone(connection.execute('SELECT used_at FROM invitations').fetchone()[0])
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM members').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM credentials').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
