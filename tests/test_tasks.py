"""Atomic task claims; all SQLite evidence is deliberately retained."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import sqlite3
from threading import Barrier
import unittest
from uuid import uuid4

from crewmesh.identity import IdentityStore
from crewmesh.errors import AccessDenied, Conflict, NotFound, ValidationError
try:
    from crewmesh.tasks import TaskStore
except ModuleNotFoundError:
    TaskStore = None


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(TaskStore, "Task store is not implemented")
        root = Path(__file__).resolve().parents[1] / ".local" / "test-evidence"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"tasks-{uuid4()}.sqlite3"
        self.identity = IdentityStore(self.path)
        self.owner = self.identity.create_room("Room", "Owner")
        self.member = self.identity.add_member(self.owner["web_token"], "Member")
        self.tasks = TaskStore(self.identity)

    def create(self, key="intent", title="Title", scope="Scope", token=None):
        return self.tasks.create_task(token or self.owner["web_token"], key, title, scope)

    def test_creation_shape_strip_and_listing_order(self):
        first = self.create(" key ", " Title ", " Scope ", self.member["web_token"])
        second = self.create("second")
        self.assertEqual(set(first), {"id", "room_id", "intent_key", "title", "scope", "state", "owner_member_id", "created_at", "claimed_at", "revision", "ownership_epoch", "execution_session_key", "creator_member_id", "last_owner_member_id", "cancelled_at", "epoch_started_at"})
        self.assertEqual((first["intent_key"], first["title"], first["scope"]), ("key", "Title", "Scope"))
        self.assertEqual(first["room_id"], self.owner["room_id"])
        self.assertEqual(first["state"], "open")
        self.assertIsNone(first["owner_member_id"])
        self.assertIsNone(first["claimed_at"])
        self.assertEqual(datetime.fromisoformat(first["created_at"]).utcoffset().total_seconds(), 0)
        for token in (self.owner["web_token"], self.member["agent_token"]):
            self.assertEqual(self.tasks.list_tasks(token), [first, second])

    def test_room_isolation_and_room_local_keys(self):
        first = self.create()
        other = self.identity.create_room("Other", "Other owner")
        second = self.create(token=other["web_token"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.tasks.list_tasks(self.owner["agent_token"]), [first])
        self.assertEqual(self.tasks.list_tasks(other["web_token"]), [second])

    def test_permissions_and_invalid_tokens_leave_task_open(self):
        task = self.create()
        for token in (self.owner["agent_token"], self.member["agent_token"], "unknown", None):
            with self.assertRaises(AccessDenied):
                self.tasks.create_task(token, "new", "Title", "Scope")
        for token in (self.owner["web_token"], self.member["web_token"], "unknown", None):
            with self.assertRaises(AccessDenied):
                self.tasks.claim_task(token, task["id"])
        for token in ("unknown", None):
            with self.assertRaises(AccessDenied):
                self.tasks.list_tasks(token)
        self.assertEqual(self.tasks.list_tasks(self.owner["web_token"]), [task])

    def test_validation_bounds_and_no_partial_creation(self):
        for index, maximum in enumerate((200, 200, 500)):
            for value in (None, 7, "", " \t ", "x" * (maximum + 1)):
                payload = ["intent", "Title", "Scope"]
                payload[index] = value
                with self.subTest(index=index, length=maximum), self.assertRaises(ValidationError):
                    self.tasks.create_task(self.owner["web_token"], *payload)
        self.assertEqual(self.tasks.list_tasks(self.owner["web_token"]), [])
        self.create(" " + "k" * 200 + " ", "t" * 200, "s" * 500)

    def test_idempotent_creation_and_payload_collision_even_after_claim(self):
        task = self.create()
        self.assertEqual(self.create(" intent "), task)
        for title, scope in (("Changed", "Scope"), ("Title", "Changed")):
            with self.assertRaises(Conflict):
                self.create(title=title, scope=scope)
        claimed = self.tasks.claim_task(self.member["agent_token"], task["id"])
        self.assertEqual(self.create(), claimed)
        with self.assertRaises(Conflict):
            self.create(title="Changed")
        self.assertEqual(self.tasks.list_tasks(self.owner["web_token"]), [claimed])

    def test_same_owner_claim_is_exactly_idempotent(self):
        task = self.create()
        claimed = self.tasks.claim_task(self.member["agent_token"], task["id"])
        self.assertEqual(claimed["state"], "claimed")
        self.assertEqual(claimed["owner_member_id"], self.member["member_id"])
        self.assertEqual(claimed["created_at"], task["created_at"])
        self.assertEqual(datetime.fromisoformat(claimed["claimed_at"]).utcoffset().total_seconds(), 0)
        self.assertEqual(self.tasks.claim_task(self.member["agent_token"], task["id"]), claimed)

    def test_conflict_identifies_verified_room_owner_without_cross_room_leak(self):
        task = self.create()
        claimed = self.tasks.claim_task(self.member["agent_token"], task["id"])
        with self.assertRaises(Conflict) as conflict:
            self.tasks.claim_task(self.owner["agent_token"], task["id"])
        self.assertEqual(conflict.exception.owner_member_id, self.member["member_id"])
        other = self.identity.create_room("Other", "Other owner")
        messages = []
        for task_id in (task["id"], task["id"] + 9999):
            with self.assertRaises(NotFound) as hidden:
                self.tasks.claim_task(other["agent_token"], task_id)
            messages.append(str(hidden.exception))
            self.assertNotIn(self.member["member_id"], str(hidden.exception))
            self.assertFalse(hasattr(hidden.exception, "owner_member_id"))
        self.assertEqual(messages[0], messages[1])
        self.assertEqual(self.tasks.list_tasks(self.owner["web_token"]), [claimed])

    def test_revoked_agent_cannot_claim_or_repeat_its_claim(self):
        task = self.create()
        claimed = self.tasks.claim_task(self.member["agent_token"], task["id"])
        open_task = self.create("open")
        self.identity.revoke_agent(self.owner["web_token"], self.member["member_id"])
        for task_id in (task["id"], open_task["id"]):
            with self.assertRaises(AccessDenied):
                self.tasks.claim_task(self.member["agent_token"], task_id)
        self.assertEqual(self.tasks.list_tasks(self.owner["web_token"]), [claimed, open_task])

    def test_four_distinct_members_race_for_one_atomic_claim(self):
        task = self.create()
        members = [self.owner, self.member] + [self.identity.add_member(self.owner["web_token"], f"Racer {i}") for i in range(2)]
        barrier = Barrier(4)
        def race(member):
            independent = TaskStore(IdentityStore(self.path))
            barrier.wait(timeout=10)
            try:
                return "success", independent.claim_task(member["agent_token"], task["id"])
            except Conflict as error:
                return "conflict", error.owner_member_id
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(race, members))
        successes = [value for status, value in results if status == "success"]
        conflicts = [value for status, value in results if status == "conflict"]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(conflicts), 3)
        winner = successes[0]
        self.assertIn(winner["owner_member_id"], {member["member_id"] for member in members})
        self.assertEqual(conflicts, [winner["owner_member_id"]] * 3)
        self.assertEqual(self.tasks.list_tasks(self.owner["web_token"]), [winner])

    def test_claim_persists_after_reopen(self):
        claimed = self.tasks.claim_task(self.member["agent_token"], self.create()["id"])
        reopened = TaskStore(IdentityStore(self.path))
        self.assertEqual(reopened.list_tasks(self.owner["web_token"]), [claimed])
        self.assertEqual(reopened.claim_task(self.member["agent_token"], claimed["id"]), claimed)

    def test_foreign_key_rejects_owner_from_other_room(self):
        task = self.create()
        other = self.identity.create_room("Other", "Other owner")
        with self.assertRaises(sqlite3.IntegrityError), self.identity.db.connect(write=True) as connection:
            connection.execute("UPDATE tasks SET owner_member_id = ?, state = 'claimed', claimed_at = ? WHERE id = ?", (other["member_id"], "2026-01-01T00:00:00+00:00", task["id"]))
        self.assertEqual(self.tasks.list_tasks(self.owner["web_token"]), [task])

    def test_failed_claim_transaction_rolls_back(self):
        task = self.create()
        with self.identity.db.connect(write=True) as connection:
            connection.execute("CREATE TRIGGER reject_claim AFTER UPDATE ON tasks BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.tasks.claim_task(self.member["agent_token"], task["id"])
        self.assertEqual(self.tasks.list_tasks(self.owner["web_token"]), [task])


if __name__ == "__main__":
    unittest.main()
