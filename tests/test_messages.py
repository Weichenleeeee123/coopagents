"""Messaging lifecycle tests retain every local SQLite evidence file."""
from pathlib import Path
import sqlite3
import unittest
from uuid import uuid4

from crewmesh.identity import IdentityStore
from crewmesh.tasks import TaskStore
from crewmesh.errors import AccessDenied, Conflict, NotFound, ValidationError
try:
    from crewmesh.messages import MessageStore
except ModuleNotFoundError:
    MessageStore = None


class MessageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MessageStore, "Message store is not implemented")
        root = Path(__file__).resolve().parents[1] / ".local" / "test-evidence"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"messages-{uuid4()}.sqlite3"
        self.identity = IdentityStore(self.path)
        self.owner = self.identity.create_room("Room", "Owner")
        self.member = self.identity.add_member(self.owner["web_token"], "Recipient")
        self.peer = self.identity.add_member(self.owner["web_token"], "Peer")
        self.other = self.identity.create_room("Other", "Other")
        self.messages = MessageStore(self.identity)

    def send(self, sender=None, **changes):
        payload = dict(request_key="key", receiver_member_id=self.member["member_id"], task_id=None, context_version=1, body="Question")
        payload.update(changes)
        return self.messages.send_request((sender or self.owner)["agent_token"], **payload)

    def reply(self, request, author=None, **changes):
        payload = dict(request_key="reply", context_version=1, body="Answer", evidence="Proof")
        payload.update(changes)
        return self.messages.reply((author or self.member)["agent_token"], request["id"], **payload)

    def test_shapes_and_send_retry(self):
        row = self.send(body=" Question ", request_key=" key ")
        self.assertEqual(set(row), {"id", "delivery_id", "room_id", "sender_member_id", "receiver_member_id", "assigned_by_member_id", "assigned_at", "task_id", "context_version", "body", "request_key", "created_at", "resolved_at", "read_at", "processed_at", "replies"})
        self.assertEqual(row["body"], "Question")
        self.assertEqual(row["sender_member_id"], self.owner["member_id"])
        self.assertEqual(self.send(), row)
        for change in ({"body": "Changed"}, {"context_version": 2}, {"receiver_member_id": None}):
            with self.assertRaises(Conflict):
                self.send(**change)
        self.assertNotEqual(self.send(self.peer)["id"], row["id"])

    def test_read_ack_reply_resolve_are_separate(self):
        row = self.send()
        self.assertIsNone(self.messages.list_requests(self.member["web_token"])[0]["read_at"])
        with self.assertRaises(Conflict):
            self.messages.acknowledge(self.member["agent_token"], row["id"])
        read = self.messages.read_inbox(self.member["agent_token"])["requests"][0]
        self.assertTrue(read["read_at"])
        self.assertIsNone(read["processed_at"])
        self.assertIsNone(read["resolved_at"])
        self.assertEqual(self.messages.read_inbox(self.member["agent_token"])["requests"][0], read)
        ack = self.messages.acknowledge(self.member["agent_token"], row["id"])
        self.assertTrue(ack["processed_at"])
        self.assertIsNone(ack["resolved_at"])
        self.assertEqual(self.messages.acknowledge(self.member["agent_token"], row["id"]), ack)
        with self.assertRaises(Conflict):
            self.messages.resolve_request(self.owner["web_token"], row["id"], 1)
        replied = self.reply(row)
        self.assertEqual(replied["processed_at"], ack["processed_at"])
        self.assertIsNone(replied["resolved_at"])
        self.assertEqual(replied["replies"][0]["author_member_id"], self.member["member_id"])
        self.assertEqual(replied["replies"][0]["evidence"], "Proof")
        resolved = self.messages.resolve_request(self.owner["agent_token"], row["id"], 1)
        self.assertTrue(resolved["resolved_at"])
        self.assertEqual(self.messages.resolve_request(self.owner["web_token"], row["id"], 1), resolved)

    def test_reply_without_read_does_not_ack(self):
        row = self.reply(self.send())
        self.assertIsNone(row["read_at"])
        self.assertIsNone(row["processed_at"])
        self.assertEqual(self.reply(row), row)
        for change in ({"body": "Changed"}, {"evidence": "Changed"}):
            with self.assertRaises(Conflict):
                self.reply(row, **change)
        second = self.send(self.peer, request_key="second", receiver_member_id=self.owner["member_id"])
        self.reply(second, self.owner)  # Separate author namespace permits the same key.
        with self.assertRaises(Conflict):
            self.reply(second, self.owner, body="Changed")
        with self.assertRaises(Conflict):
            self.reply(self.send(request_key="third"))

    def test_assignment_only_web_and_only_unassigned(self):
        row = self.send(receiver_member_id=None)
        self.assertIsNone(row["assigned_by_member_id"])
        self.assertIsNone(row["assigned_at"])
        self.assertEqual(self.messages.read_inbox(self.member["agent_token"])["requests"], [])
        with self.assertRaises(AccessDenied):
            self.messages.assign_receiver(self.owner["agent_token"], row["id"], self.member["member_id"])
        assigned = self.messages.assign_receiver(self.peer["web_token"], row["id"], self.member["member_id"])
        self.assertEqual(assigned["receiver_member_id"], self.member["member_id"])
        self.assertEqual(assigned["assigned_by_member_id"], self.peer["member_id"])
        self.assertTrue(assigned["assigned_at"].endswith("+00:00"))
        self.assertEqual(self.messages.assign_receiver(self.owner["web_token"], row["id"], self.member["member_id"]), assigned)
        with self.assertRaises(Conflict):
            self.messages.assign_receiver(self.owner["web_token"], row["id"], self.peer["member_id"])
        self.assertEqual(self.send(receiver_member_id=None)["id"], row["id"])

    def test_permissions_and_hidden_rooms(self):
        row = self.send()
        for token in (self.member["web_token"], "unknown", None):
            with self.assertRaises(AccessDenied):
                self.messages.send_request(token, "x", None, None, 1, "Body")
            with self.assertRaises(AccessDenied):
                self.messages.read_inbox(token)
            with self.assertRaises(AccessDenied):
                self.messages.reply(token, row["id"], "x", 1, "Body")
            with self.assertRaises(AccessDenied):
                self.messages.acknowledge(token, row["id"])
        for member in (self.owner, self.peer):
            with self.assertRaises(AccessDenied):
                self.reply(row, member)
            with self.assertRaises(AccessDenied):
                self.messages.acknowledge(member["agent_token"], row["id"])
        with self.assertRaises(AccessDenied):
            self.messages.resolve_request(self.member["web_token"], row["id"], 1)
        for request_id in (row["id"], 999999):
            with self.assertRaises(NotFound):
                self.messages.resolve_request(self.other["web_token"], request_id, 1)
            with self.assertRaises(NotFound):
                self.messages.assign_receiver(self.other["web_token"], request_id, self.other["member_id"])
            with self.assertRaises(NotFound):
                self.messages.reply(self.other["agent_token"], request_id, "r", 1, "Answer")
        self.assertEqual(self.messages.list_requests(self.other["web_token"]), [])
        self.assertEqual(self.messages.read_inbox(self.peer["agent_token"])["requests"], [])

    def test_task_and_target_room_validation(self):
        tasks = TaskStore(self.identity)
        own = tasks.create_task(self.owner["web_token"], "own", "Task", "src")
        foreign = tasks.create_task(self.other["web_token"], "other", "Task", "src")
        self.send(task_id=own["id"])
        for value in (foreign["id"], 999999):
            with self.assertRaises(NotFound):
                self.send(request_key=str(value), task_id=value)
        for value in (self.other["member_id"], "missing"):
            with self.assertRaises(NotFound):
                self.send(request_key=value, receiver_member_id=value)
            with self.assertRaises(NotFound):
                self.messages.assign_receiver(self.owner["web_token"], self.send(request_key="pending", receiver_member_id=None)["id"], value)

    def test_version_and_input_validation(self):
        row = self.send()
        for version in (2, 3):
            with self.assertRaises(Conflict):
                self.reply(row, context_version=version)
            with self.assertRaises(Conflict):
                self.messages.resolve_request(self.owner["web_token"], row["id"], version)
        for field, values in (("context_version", (True, False, 0, -1, "1", 1.0, None)), ("task_id", (True, 0, -1, "1", 1.0)), ("body", (None, 1, "", " ", "x" * 4001)), ("request_key", (None, 1, "", " ", "x" * 201))):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    self.send(**{field: value})
        for evidence in (None, 1, "e" * 1001):
            with self.assertRaises(ValidationError):
                self.reply(row, evidence=evidence)
        self.send(request_key="k" * 200, body="b" * 4000)
        self.reply(row, request_key="r" * 200, body="b" * 4000, evidence="e" * 1000)
        for method in (self.messages.acknowledge,):
            for value in (True, 0, -1, "1", 1.0):
                with self.assertRaises(ValidationError):
                    method(self.member["agent_token"], value)

    def test_pagination_exclusive_cursor(self):
        rows = [self.send(request_key=str(i)) for i in range(4)]
        first = self.messages.read_inbox(self.member["agent_token"], limit=2)
        self.assertEqual(first["next_cursor"], rows[1]["delivery_id"])
        self.assertEqual([r["id"] for r in first["requests"]], [r["id"] for r in rows[:2]])
        second = self.messages.read_inbox(self.member["agent_token"], after_id=first["next_cursor"], limit=2)
        self.assertEqual([r["id"] for r in second["requests"]], [r["id"] for r in rows[2:]])
        empty = self.messages.read_inbox(self.member["agent_token"], after_id=second["next_cursor"])
        self.assertEqual(empty, {"requests": [], "next_cursor": second["next_cursor"]})
        for changes in ({"after_id": True}, {"after_id": -1}, {"after_id": "1"}, {"limit": True}, {"limit": 0}, {"limit": 51}, {"limit": 1.0}):
            with self.assertRaises(ValidationError):
                self.messages.read_inbox(self.member["agent_token"], **changes)

    def test_late_assignment_uses_delivery_cursor_and_survives_reopen(self):
        pending = self.send(request_key="pending", receiver_member_id=None)
        self.assertIsNone(pending["delivery_id"])
        newer = self.send(request_key="newer")
        page = self.messages.read_inbox(self.member["agent_token"])
        self.assertEqual(page["next_cursor"], newer["delivery_id"])
        assigned = self.messages.assign_receiver(self.owner["web_token"], pending["id"], self.member["member_id"])
        self.assertGreater(assigned["delivery_id"], page["next_cursor"])
        self.assertEqual(self.messages.assign_receiver(self.peer["web_token"], pending["id"], self.member["member_id"]), assigned)
        self.assertEqual(self.send(request_key="pending", receiver_member_id=None), assigned)
        reopened = MessageStore(IdentityStore(self.path))
        late = reopened.read_inbox(self.member["agent_token"], after_id=page["next_cursor"])
        self.assertEqual([row["id"] for row in late["requests"]], [pending["id"]])
        self.assertEqual(late["next_cursor"], assigned["delivery_id"])
        self.assertEqual(reopened.read_inbox(self.member["agent_token"], after_id=late["next_cursor"]),
                         {"requests": [], "next_cursor": late["next_cursor"]})

    def test_reopen_revocation_and_rollback(self):
        row = self.send()
        self.reply(row)
        reopened = MessageStore(IdentityStore(self.path))
        self.assertEqual(reopened.list_requests(self.member["web_token"]), self.messages.list_requests(self.owner["agent_token"]))
        second = self.send(request_key="second")
        with self.identity.db.connect(write=True) as connection:
            connection.execute(f"CREATE TRIGGER fail_receipt BEFORE INSERT ON message_receipts WHEN NEW.request_id = {second['id']} BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.messages.read_inbox(self.member["agent_token"])
        self.assertTrue(all(request["read_at"] is None for request in self.messages.list_requests(self.owner["web_token"])))
        self.identity.revoke_agent(self.owner["web_token"], self.member["member_id"])
        for call in (lambda: self.messages.read_inbox(self.member["agent_token"]), lambda: self.reply(row), lambda: self.messages.list_requests(self.member["agent_token"])):
            with self.assertRaises(AccessDenied):
                call()

    def test_database_foreign_keys(self):
        row = self.send()
        self.messages.read_inbox(self.member["agent_token"])
        self.reply(row)
        foreign = TaskStore(self.identity).create_task(self.other["web_token"], "foreign", "Task", "src")
        for statement, value in (("UPDATE message_requests SET room_id = ?", self.other["room_id"]), ("UPDATE message_requests SET sender_member_id = ?", self.other["member_id"]), ("UPDATE message_requests SET receiver_member_id = ?", self.other["member_id"])):
            with self.assertRaises(sqlite3.IntegrityError), self.identity.db.connect(write=True) as connection:
                connection.execute(statement, (value,))
        for statement, value in (("UPDATE message_requests SET task_id = ?", foreign["id"]), ("UPDATE message_receipts SET member_id = ?", self.peer["member_id"]), ("UPDATE message_replies SET author_member_id = ?", self.peer["member_id"]), ("UPDATE message_requests SET receiver_member_id = ?", self.peer["member_id"])):
            with self.assertRaises(sqlite3.IntegrityError), self.identity.db.connect(write=True) as connection:
                connection.execute(statement, (value,))


if __name__ == "__main__":
    unittest.main()
