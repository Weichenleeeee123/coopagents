"""Identity integration tests; SQLite evidence is deliberately retained."""
import hashlib
from pathlib import Path
import sqlite3
import unittest
from uuid import UUID, uuid4

try:
    from crewmesh.identity import IdentityStore, Principal
    from crewmesh.errors import AccessDenied, NotFound, ValidationError
except ModuleNotFoundError:
    IdentityStore = None


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(IdentityStore, "Identity foundation is not implemented")
        root = Path(__file__).resolve().parents[1] / ".local" / "test-evidence"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"identity-{uuid4()}.sqlite3"
        self.store = IdentityStore(self.path)
        self.owner = self.store.create_room(" Room ", " Owner ")

    def counts(self):
        with self.store.db.connect() as connection:
            return tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                         for table in ("rooms", "members", "credentials"))

    def test_creation_identity_and_only_hashes_persist(self):
        tokens = [self.owner["web_token"], self.owner["agent_token"]]
        self.assertEqual(len(set(tokens)), 2)
        for kind, token in zip(("web", "agent"), tokens):
            principal = self.store.authenticate(token, required_kind=kind)
            self.assertEqual(principal, Principal(self.owner["room_id"], self.owner["member_id"], "Owner", "owner", kind))
        UUID(self.owner["room_id"])
        UUID(self.owner["member_id"])
        with self.store.db.connect() as connection:
            hashes = {row[0] for row in connection.execute("SELECT token_hash FROM credentials")}
            self.assertEqual(hashes, {hashlib.sha256(token.encode()).hexdigest() for token in tokens})
            self.assertEqual(connection.execute("SELECT name FROM rooms").fetchone()[0], "Room")
        data = self.path.read_bytes()
        for token in tokens:
            self.assertNotIn(token.encode(), data)

    def test_bad_credentials_never_echo_input(self):
        for token in (None, 42, "", "secret-unknown", "\ud800"):
            with self.subTest(token=token), self.assertRaises(AccessDenied) as caught:
                self.store.authenticate(token)
            if isinstance(token, str) and token:
                self.assertNotIn(token, str(caught.exception))

    def test_kind_validation_and_scope(self):
        with self.assertRaises(ValidationError):
            self.store.authenticate(self.owner["web_token"], required_kind="invalid")
        with self.assertRaises(AccessDenied):
            self.store.authenticate(self.owner["agent_token"], required_kind="web")
        with self.store.db.connect() as connection:
            self.assertEqual(self.store.resolve(connection, self.owner["web_token"]).kind, "web")

    def test_owner_adds_member_and_member_cannot_add(self):
        member = self.store.add_member(self.owner["web_token"], " Alice ")
        self.assertEqual(member["room_id"], self.owner["room_id"])
        self.assertEqual(self.store.authenticate(member["web_token"]).role, "member")
        before = self.counts()
        for token in (member["web_token"], member["agent_token"], self.owner["agent_token"], "unknown"):
            with self.assertRaises(AccessDenied):
                self.store.add_member(token, "Intruder")
            self.assertEqual(self.counts(), before)

    def test_lists_are_isolated_deterministic_and_have_no_credentials(self):
        alice = self.store.add_member(self.owner["web_token"], "Alice")
        other = self.store.create_room("Other", "Other owner")
        members = self.store.list_members(alice["agent_token"])
        self.assertEqual(members, self.store.list_members(self.owner["web_token"]))
        self.assertEqual({row["member_id"] for row in members}, {self.owner["member_id"], alice["member_id"]})
        self.assertEqual(len(self.store.list_members(other["web_token"])), 1)
        for row in members:
            self.assertEqual(set(row), {"room_id", "member_id", "display_name", "role"})

    def test_member_revokes_own_agent_idempotently(self):
        member = self.store.add_member(self.owner["web_token"], "Alice")
        for _ in range(2):
            self.store.revoke_agent(member["web_token"], member["member_id"])
        with self.assertRaises(AccessDenied):
            self.store.authenticate(member["agent_token"])
        self.assertEqual(self.store.authenticate(member["web_token"]).kind, "web")
        self.store.authenticate(self.owner["agent_token"])

    def test_owner_revokes_same_room_member(self):
        member = self.store.add_member(self.owner["web_token"], "Alice")
        self.store.revoke_agent(self.owner["web_token"], member["member_id"])
        with self.assertRaises(AccessDenied):
            self.store.authenticate(member["agent_token"])

    def test_revocation_requires_web_and_member_cannot_revoke_peer(self):
        member = self.store.add_member(self.owner["web_token"], "Alice")
        for token in (self.owner["agent_token"], member["agent_token"], member["web_token"]):
            with self.assertRaises(AccessDenied):
                self.store.revoke_agent(token, self.owner["member_id"])
        self.store.authenticate(self.owner["agent_token"])

    def test_cross_room_and_nonexistent_targets_are_uniformly_hidden(self):
        other = self.store.create_room("Other", "Other owner")
        messages = []
        for target in (other["member_id"], str(uuid4())):
            with self.assertRaises(NotFound) as caught:
                self.store.revoke_agent(self.owner["web_token"], target)
            messages.append(str(caught.exception))
        self.assertEqual(messages[0], messages[1])
        self.store.authenticate(other["agent_token"])

    def test_names_validate_before_partial_creation(self):
        before = self.counts()
        for value in (None, 7, " ", "x" * 121):
            with self.assertRaises(ValidationError):
                self.store.create_room(value, "Owner")
            with self.assertRaises(ValidationError):
                self.store.create_room("Room", value)
            with self.assertRaises(ValidationError):
                self.store.add_member(self.owner["web_token"], value)
            self.assertEqual(self.counts(), before)
        self.store.create_room("x" * 120, "y" * 120)

    def test_persistence_and_foreign_keys_on_every_connection(self):
        reopened = IdentityStore(self.path)
        self.assertEqual(reopened.authenticate(self.owner["web_token"]), self.store.authenticate(self.owner["web_token"]))
        for write in (False, True):
            with reopened.db.connect(write=write) as connection:
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 10000)
        with self.assertRaises(sqlite3.IntegrityError), reopened.db.connect(write=True) as connection:
            connection.execute("INSERT INTO members (id, room_id, display_name, role) VALUES (?, ?, ?, ?)", (str(uuid4()), str(uuid4()), "Orphan", "member"))

    def test_creation_is_atomic_if_credentials_insert_fails(self):
        with self.store.db.connect(write=True) as connection:
            connection.execute("CREATE TRIGGER reject_agent BEFORE INSERT ON credentials WHEN NEW.kind = 'agent' BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        before = self.counts()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_room("Failed", "Owner")
        self.assertEqual(self.counts(), before)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_member(self.owner["web_token"], "Failed")
        self.assertEqual(self.counts(), before)

    def test_write_connection_rolls_back_and_closes_on_exception(self):
        with self.assertRaises(RuntimeError):
            with self.store.db.connect(write=True) as connection:
                connection.execute("INSERT INTO rooms (id, name) VALUES (?, ?)", (str(uuid4()), "Rolled back"))
                raise RuntimeError("injected failure")
        self.assertEqual(self.counts(), (1, 1, 2))
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
