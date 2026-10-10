"""Agent activity is room scoped and explicitly reported; evidence is retained."""
from datetime import datetime
from pathlib import Path
import sqlite3
import unittest
from uuid import uuid4

from crewmesh.identity import IdentityStore
from crewmesh.tasks import TaskStore
from crewmesh.errors import AccessDenied, NotFound, ValidationError
try:
    from crewmesh.activity import ActivityStore
except ModuleNotFoundError:
    ActivityStore = None


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ActivityStore, "Activity store is not implemented")
        root = Path(__file__).resolve().parents[1] / ".local" / "test-evidence"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"activity-{uuid4()}.sqlite3"
        self.identity = IdentityStore(self.path)
        self.owner = self.identity.create_room("Room", "Owner")
        self.member = self.identity.add_member(self.owner["web_token"], "Member")
        self.other = self.identity.create_room("Other", "Other owner")
        self.tasks = TaskStore(self.identity)
        self.activity = ActivityStore(self.identity)

    def task(self, scope="src/auth", member=None, claimed=True):
        member = member or self.member
        token = self.other["web_token"] if member is self.other else self.owner["web_token"]
        task = self.tasks.create_task(token, str(uuid4()), "Task", scope)
        return self.tasks.claim_task(member["agent_token"], task["id"]) if claimed else task

    def session(self, member=None, **changes):
        payload = dict(session_key="key", tool="codex-cli", repository="repo", branch="main")
        payload.update(changes)
        return self.activity.register_session((member or self.member)["agent_token"], **payload)

    def test_session_shape_strip_upsert_and_multiple_sessions(self):
        first = self.session(session_key=" key ", repository=" repo ", branch=" main ")
        self.assertEqual(set(first), {"id", "room_id", "member_id", "session_key", "tool", "repository", "branch", "task_id", "updated_at"})
        self.assertEqual((first["session_key"], first["repository"], first["branch"]), ("key", "repo", "main"))
        self.assertEqual(first["member_id"], self.member["member_id"])
        self.assertEqual(first["room_id"], self.owner["room_id"])
        self.assertIsNone(first["task_id"])
        self.assertEqual(datetime.fromisoformat(first["updated_at"]).utcoffset().total_seconds(), 0)
        updated = self.session(branch="feature", tool="claude-code")
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(updated["branch"], "feature")
        second = self.session(session_key="second", tool="codex-desktop")
        independent = self.session(self.owner)
        self.assertEqual(len({updated["id"], second["id"], independent["id"]}), 3)
        for token in (self.owner["web_token"], self.member["agent_token"]):
            self.assertEqual(self.activity.list_sessions(token), [updated, second, independent])

    def test_task_association_requires_room_and_owner(self):
        own = self.task()
        foreign_owner = self.task(member=self.owner)
        unclaimed = self.task(claimed=False)
        other_room = self.task(member=self.other)
        self.assertEqual(self.session(task_id=own["id"])["task_id"], own["id"])
        for task in (foreign_owner, unclaimed):
            with self.assertRaises(AccessDenied):
                self.session(task_id=task["id"])
        messages = []
        for task_id in (other_room["id"], 999999):
            with self.assertRaises(NotFound) as error:
                self.session(task_id=task_id)
            messages.append(str(error.exception))
        self.assertEqual(messages[0], messages[1])
        self.assertEqual(self.activity.list_sessions(self.owner["web_token"])[0]["task_id"], own["id"])

    def test_credential_permissions_and_revocation(self):
        task = self.task()
        for token in (self.member["web_token"], "unknown", None):
            with self.assertRaises(AccessDenied):
                self.activity.register_session(token, "key", "codex-cli", "repo", "main")
            with self.assertRaises(AccessDenied):
                self.activity.report_progress(token, task["id"], "working", "Started")
        self.identity.revoke_agent(self.owner["web_token"], self.member["member_id"])
        with self.assertRaises(AccessDenied):
            self.session()
        with self.assertRaises(AccessDenied):
            self.activity.report_progress(self.member["agent_token"], task["id"], "working", "Started")
        for method in (self.activity.list_sessions, self.activity.list_progress, self.activity.overlaps):
            with self.assertRaises(AccessDenied):
                method("unknown")

    def test_progress_explicit_latest_report_preserves_claim(self):
        task = self.task()
        self.session(task_id=task["id"])
        self.assertEqual(self.activity.list_progress(self.owner["web_token"]), [])
        for state in ("working", "blocked", "local_done", "pushed", "pr_open", "merged"):
            row = self.activity.report_progress(self.member["agent_token"], task["id"], state, " Summary ", " Evidence ")
            self.assertEqual(set(row), {"task_id", "room_id", "member_id", "state", "summary", "evidence", "source", "updated_at"})
            self.assertEqual((row["state"], row["summary"], row["evidence"], row["source"]), (state, "Summary", "Evidence", "agent_report"))
            self.assertEqual(row["member_id"], self.member["member_id"])
            self.assertEqual(datetime.fromisoformat(row["updated_at"]).utcoffset().total_seconds(), 0)
            self.assertEqual(self.activity.list_progress(self.owner["web_token"]), [row])
        self.session(task_id=task["id"], branch="heartbeat")
        self.assertEqual(self.activity.list_progress(self.member["agent_token"]), [row])
        self.assertEqual(self.tasks.list_tasks(self.owner["web_token"]), [task])

    def test_progress_rejects_unclaimed_other_owner_and_cross_room(self):
        for task in (self.task(claimed=False), self.task(member=self.owner)):
            with self.assertRaises(AccessDenied):
                self.activity.report_progress(self.member["agent_token"], task["id"], "working", "Summary")
        hidden = self.task(member=self.other)
        messages = []
        for task_id in (hidden["id"], 99999):
            with self.assertRaises(NotFound) as error:
                self.activity.report_progress(self.member["agent_token"], task_id, "working", "Summary")
            messages.append(str(error.exception))
        self.assertEqual(messages[0], messages[1])
        self.assertEqual(self.activity.list_progress(self.owner["web_token"]), [])

    def test_room_isolation_and_persistence(self):
        own = self.task()
        foreign = self.task(member=self.other)
        session = self.session(task_id=own["id"])
        other_session = self.session(self.other, task_id=foreign["id"])
        report = self.activity.report_progress(self.member["agent_token"], own["id"], "working", "Summary")
        other_report = self.activity.report_progress(self.other["agent_token"], foreign["id"], "blocked", "Other")
        reopened = ActivityStore(IdentityStore(self.path))
        self.assertEqual(reopened.list_sessions(self.owner["web_token"]), [session])
        self.assertEqual(reopened.list_sessions(self.other["agent_token"]), [other_session])
        self.assertEqual(reopened.list_progress(self.owner["agent_token"]), [report])
        self.assertEqual(reopened.list_progress(self.other["web_token"]), [other_report])

    def test_session_validation_bounds_no_partial_rows(self):
        for field, maximum in (("session_key", 200), ("repository", 500), ("branch", 200)):
            for value in (None, 7, "", " \t ", "x" * (maximum + 1)):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    self.session(**{field: value})
        for value in (None, "other", 5, [], " codex-cli "):
            with self.assertRaises(ValidationError):
                self.session(tool=value)
        for value in (True, False, 0, -1, "1", 1.0):
            with self.assertRaises(ValidationError):
                self.session(task_id=value)
        self.assertEqual(self.activity.list_sessions(self.owner["web_token"]), [])
        self.session(session_key="k" * 200, repository="r" * 500, branch="b" * 200)

    def test_progress_validation_bounds_no_partial_rows(self):
        task = self.task()
        for field, values in (("state", ("done", None, 1, [], " working ")), ("summary", (None, 1, "", " \t ", "s" * 4001)), ("evidence", (None, 1, "e" * 1001)), ("task_id", (True, False, 0, -1, "1", 1.0, None))):
            for value in values:
                payload = dict(task_id=task["id"], state="working", summary="Summary", evidence="")
                payload[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    self.activity.report_progress(self.member["agent_token"], **payload)
        self.assertEqual(self.activity.list_progress(self.owner["web_token"]), [])
        self.activity.report_progress(self.member["agent_token"], task["id"], "working", "s" * 4000, "e" * 1000)

    def test_scope_equal_and_segment_prefix_only(self):
        scopes = ("src/auth", "src/auth", "src/auth/login", "src/authentication", "docs", "src/auth/")
        tasks = [self.task(scope=scope, claimed=False) for scope in scopes]
        self.task(scope="src/auth", member=self.other)
        matches = self.activity.overlaps(self.owner["web_token"])
        pairs = {tuple(row["task_ids"]) for row in matches}
        self.assertEqual(pairs, {(tasks[a]["id"], tasks[b]["id"]) for a, b in ((0, 1), (0, 2), (0, 5), (1, 2), (1, 5), (2, 5))})
        for row in matches:
            self.assertEqual(row["scopes"], [next(task["scope"] for task in tasks if task["id"] == task_id) for task_id in row["task_ids"]])
            self.assertTrue(row["reason"])
        self.assertEqual(self.activity.overlaps(self.member["agent_token"]), matches)
        self.assertEqual(self.activity.overlaps(self.other["web_token"]), [])

    def test_database_rejects_cross_room_and_fake_owner_activity(self):
        own = self.task()
        foreign = self.task(member=self.other)
        self.session(task_id=own["id"])
        self.activity.report_progress(self.member["agent_token"], own["id"], "working", "Summary")
        for statement, value in (("UPDATE sessions SET room_id = ?", self.other["room_id"]), ("UPDATE sessions SET task_id = ?", foreign["id"]), ("UPDATE sessions SET member_id = ?", self.owner["member_id"]), ("UPDATE progress SET room_id = ?", self.other["room_id"]), ("UPDATE progress SET member_id = ?", self.owner["member_id"])):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError), self.identity.db.connect(write=True) as connection:
                connection.execute(statement, (value,))


if __name__ == "__main__":
    unittest.main()
