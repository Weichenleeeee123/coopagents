"""Fictional local probe tests; evidence databases are intentionally retained."""

import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import probe_server


class StoreFixture:
    def setUp(self):
        self.probe = probe_server
        self.database = Path(__file__).parent / "evidence" / uuid4().hex / "test.sqlite3"
        self.store = self.probe.open_store(self.database)


class StoreTests(StoreFixture, unittest.TestCase):
    def test_retry_returns_exact_row_without_duplicate(self):
        first = self.store.post("request-1", "fictional-alice", "probe one")
        retry = self.store.post("request-1", "fictional-alice", "probe one")

        self.assertEqual(first, retry)
        self.assertEqual(self.store.read(0), [first])
        self.assertEqual(
            set(first), {"id", "request_key", "author", "body", "created_at"}
        )
        self.assertIsNotNone(datetime.fromisoformat(first["created_at"]).tzinfo)

    def test_conflicting_retry_payload_is_rejected(self):
        first = self.store.post("request-1", "fictional-alice", "probe one")
        for author, body in [("fictional-bob", "probe one"), ("fictional-alice", "changed")]:
            with self.subTest(author=author, body=body):
                with self.assertRaises(ValueError):
                    self.store.post("request-1", author, body)
        self.assertEqual(self.store.read(0), [first])

    def test_read_does_not_ack_and_repeated_ack_has_one_receipt(self):
        message = self.store.post("request-1", "fictional-alice", "probe one")
        self.assertEqual(self.store.read(0), [message])
        self.assertEqual(self.store.receipts(message["id"]), [])

        expected = {
            "message_id": message["id"],
            "receiver": "fictional-bob",
            "acknowledged": True,
        }
        self.assertEqual(self.store.ack(message["id"], "fictional-bob"), expected)
        self.assertEqual(self.store.ack(message["id"], "fictional-bob"), expected)
        self.assertEqual(self.store.receipts(message["id"]), ["fictional-bob"])
        self.assertEqual(self.store.read(0), [message])
        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        self.assertEqual(count, 1)

    def test_ack_rejects_nonexistent_message(self):
        with self.assertRaises(ValueError):
            self.store.ack(999, "fictional-bob")
        self.assertEqual(self.store.receipts(999), [])

    def test_reopening_preserves_messages_and_sorted_receipts(self):
        message = self.store.post("request-1", "fictional-alice", "probe one")
        self.store.ack(message["id"], "fictional-zoe")
        self.store.ack(message["id"], "fictional-bob")

        reopened = self.probe.open_store(self.database)
        self.assertEqual(reopened.read(0), [message])
        self.assertEqual(
            reopened.receipts(message["id"]), ["fictional-bob", "fictional-zoe"]
        )
        self.assertEqual(
            reopened.post("request-1", "fictional-alice", "probe one"), message
        )

    def test_four_concurrent_retries_insert_one_row(self):
        stores = [self.probe.open_store(self.database) for _ in range(4)]
        start = threading.Barrier(4)

        def post(store):
            start.wait(timeout=10)
            return store.post("concurrent-1", "fictional-alice", "shared probe")

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(post, stores))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.store.read(0), [results[0]])

    def test_read_uses_exclusive_cursor_and_at_most_fifty_rows(self):
        rows = [
            self.store.post(f"request-{index}", "fictional-alice", str(index))
            for index in range(53)
        ]
        self.assertEqual(self.store.read(0), rows[:50])
        self.assertEqual(self.store.read(rows[49]["id"]), rows[50:])
        self.assertEqual(self.store.read(rows[-1]["id"]), [])

    def test_post_rejects_empty_fields_and_oversized_body(self):
        invalid = [
            ("", "fictional-alice", "probe"),
            ("request", "", "probe"),
            ("request", "fictional-alice", ""),
            ("request", "fictional-alice", "x" * 4001),
        ]
        for payload in invalid:
            with self.subTest(payload=payload[:2]):
                with self.assertRaises(ValueError):
                    self.store.post(*payload)
        self.assertEqual(self.store.read(0), [])
        self.assertEqual(
            self.store.post("boundary", "fictional-alice", "x" * 4000)["body"],
            "x" * 4000,
        )

    def test_ack_rejects_empty_receiver(self):
        message = self.store.post("request-1", "fictional-alice", "probe one")
        with self.assertRaises(ValueError):
            self.store.ack(message["id"], "")
        self.assertEqual(self.store.receipts(message["id"]), [])


class MCPTests(StoreFixture, unittest.IsolatedAsyncioTestCase):
    async def test_tools_round_trip_and_cursor_preserves_empty_page_position(self):
        from mcp import Client
        from mcp.server import MCPServer

        server = self.probe.build_server(self.store)
        self.assertIsInstance(server, MCPServer)
        async with Client(server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            self.assertEqual(
                names, {"post_probe", "read_probes", "ack_probe", "probe_receipts"}
            )
            self.assertIn("fictional", client.instructions)
            self.assertIn("not authenticated", client.instructions)
            self.assertIn("not authoritative", client.instructions)
            self.assertIn("after processing", client.instructions)

            async def call(name, arguments):
                result = await client.call_tool(name, arguments)
                self.assertFalse(result.is_error, result.content)
                self.assertIsInstance(result.structured_content, dict)
                return result.structured_content

            payload = {
                "request_key": "mcp-request-1",
                "author": "fictional-alice",
                "body": "fictional probe",
            }
            message = await call("post_probe", payload)
            self.assertEqual(await call("post_probe", payload), message)
            self.assertEqual(
                await call("read_probes", {}),
                {"messages": [message], "next_cursor": message["id"]},
            )
            self.assertEqual(
                await call("probe_receipts", {"message_id": message["id"]}),
                {"message_id": message["id"], "receivers": []},
            )
            ack = {"message_id": message["id"], "receiver": "fictional-bob"}
            self.assertEqual(await call("ack_probe", ack), {**ack, "acknowledged": True})
            self.assertEqual(
                await call("probe_receipts", {"message_id": message["id"]}),
                {"message_id": message["id"], "receivers": ["fictional-bob"]},
            )
            self.assertEqual(
                await call("read_probes", {"after_id": 500}),
                {"messages": [], "next_cursor": 500},
            )


if __name__ == "__main__":
    unittest.main()
