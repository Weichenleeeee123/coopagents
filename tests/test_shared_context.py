import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import ValidationError
from transport_support import LiveService


class SharedContextTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path('.local/test-evidence/shared-context') / uuid4().hex
        self.folder.mkdir(parents=True)
        self.service = CoordinationService(self.folder / "context.sqlite3")
        self.owner = self.service.identity.create_room("Context", "Owner")
        self.member = self.service.identity.add_member(self.owner["web_token"], "Member")

    def test_context_is_bounded_source_labelled_and_excludes_private_payloads(self):
        task = self.service.tasks.create_task(self.owner["web_token"], "context-task", "Share context", "src")
        claimed = self.service.tasks.claim_task(self.owner["agent_token"], task["id"], session_key="session")
        self.service.activity.register_session(self.owner["agent_token"], "session", "codex-cli", "github.com/o/r", "main", task_id=task["id"], ownership_epoch=claimed["ownership_epoch"])
        self.service.activity.report_progress(self.owner["agent_token"], task["id"], "working", "Public progress", "commit abc", session_key="session", ownership_epoch=claimed["ownership_epoch"])
        self.service.messages.send_request(self.owner["agent_token"], "request", self.member["member_id"], task["id"], 1, "Need the API shape")
        result = self.service.read_context(self.owner["web_token"], limit=3)
        self.assertEqual(result["limit"], 3)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["privacy"], "shared_structured_only")
        self.assertTrue(all(item["privacy"] == "shared_structured" for item in result["items"]))
        self.assertTrue(all(set(item) == {"id", "kind", "source", "scope", "observed_at", "freshness", "privacy", "data"}
                            for item in result["items"]))
        encoded = json.dumps(result)
        self.assertNotIn("transcript", encoded)
        self.assertNotIn("tool_input", encoded)

    def test_filters_and_freshness_are_explicit(self):
        task = self.service.tasks.create_task(self.owner["web_token"], "fresh-task", "Freshness", "src")
        claimed = self.service.tasks.claim_task(self.owner["agent_token"], task["id"], session_key="fresh-session")
        self.service.activity.register_session(self.owner["agent_token"], "fresh-session", "codex-cli", "github.com/o/r", "main", task_id=task["id"], ownership_epoch=claimed["ownership_epoch"])
        result = self.service.read_context(self.owner["web_token"], task_id=task["id"], member_id=self.owner["member_id"])
        self.assertTrue(result["items"])
        self.assertTrue(all(item["data"].get("task_id") == task["id"] or item["kind"] == "task" for item in result["items"]))
        session = next(item for item in result["items"] if item["kind"] == "session")
        self.assertEqual(session["freshness"], "fresh")
        self.assertEqual(result["filters"]["member_id"], self.owner["member_id"])

    def test_invalid_limits_are_rejected(self):
        for limit in (0, 101, True, "10"):
            with self.subTest(limit=limit), self.assertRaises(ValidationError):
                self.service.read_context(self.owner["web_token"], limit=limit)

    def test_http_context_query_uses_the_same_structured_projection(self):
        live = LiveService()
        self.addCleanup(live.close)
        owner, _ = live.bootstrap()
        task = live.request("POST", "/api/tasks", owner["web_token"],
                            {"intent_key": "http-context", "title": "HTTP context", "scope": "src"})[1]
        status, result, _ = live.request("GET", "/api/context?task_id=%d&limit=1" % task["id"], owner["web_token"])
        self.assertEqual(status, 200, result)
        self.assertEqual(result["filters"], {"task_id": task["id"], "member_id": None})
        self.assertEqual(result["items"][0]["data"]["task_id"], task["id"])


if __name__ == "__main__":
    unittest.main()
