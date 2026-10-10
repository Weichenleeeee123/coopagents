"""Tests for native probe safety and evidence classification."""
import unittest
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
from uuid import uuid4
import native_check

from native_check import claude_args, classify_codex_preflight, native_pair_passed, EXPECTED_BODY, advance_cursor, summarize_events


class NativeCheckTests(unittest.TestCase):
    def test_claude_only_has_probe_permissions(self):
        args = claude_args("claude.exe", "prompt", "id")
        self.assertEqual(args[args.index("--tools") + 1], "")
        allowed = args[args.index("--allowedTools") + 1].split(",")
        self.assertEqual(set(allowed), {"mcp__crewmesh_probe__post_probe"})
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertNotIn("--settings", args)

    def test_config_failure_blocks_codex_before_auth(self):
        self.assertEqual(classify_codex_preflight(1, "invalid type: map, expected a boolean"),
                         "configuration_invalid_type")
        self.assertEqual(classify_codex_preflight(0, ""), "ready")

    def test_receipt_alone_is_not_native_proof(self):
        report = {"audit": [{"author": "claude-native", "receivers": ["codex-native"]}]}
        self.assertFalse(native_pair_passed(report))
        report["claude"] = {"exit_code": 0, "timed_out": False,
                            "tool_calls": [{"name": "mcp__crewmesh_probe__post_probe"}]}
        report["codex"] = {"exit_code": 0, "timed_out": False,
                           "tool_calls": [{"name": "read_probes"}, {"name": "ack_probe"},
                                          {"name": "probe_receipts"}]}
        self.assertFalse(native_pair_passed(report))
        report["claude"]["model_error"] = "subscription access disabled"
        self.assertFalse(native_pair_passed(report))

    def test_correlated_native_pair_and_failure_cases(self):
        import copy
        row = {"id": 42, "request_key": "run", "author": "claude-native", "body": EXPECTED_BODY}
        def call(name, arguments, result):
            return {"name": name, "arguments": arguments, "result": result, "success": True}
        report = {"run_id": "run", "claude": {"exit_code": 0, "timed_out": False,
                  "tool_calls": [call("mcp__crewmesh_probe__post_probe",
                    {key: row[key] for key in ("request_key", "author", "body")}, row)]},
                  "codex": {"exit_code": 0, "timed_out": False,
                            "answer": {"message_id": 42, "lantern_count": 3}, "tool_calls": [
                    call("read_probes", {"after_id": 0}, {"messages": [row]}),
                    call("ack_probe", {"message_id": 42, "receiver": "codex-native"},
                         {"message_id": 42, "receiver": "codex-native", "acknowledged": True}),
                    call("probe_receipts", {"message_id": 42},
                         {"message_id": 42, "receivers": ["codex-native"]})]},
                  "audit": [{"message_id": 42, "author": "claude-native", "body": EXPECTED_BODY,
                              "receivers": ["codex-native"]}]}
        self.assertTrue(native_pair_passed(report))
        for mutation in ("timeout", "exit", "wrong_id", "missing_read", "wrong_run", "failed_ack",
                         "wrong_count", "wrong_answer_id", "missing_answer"):
            changed = copy.deepcopy(report)
            if mutation == "timeout": changed["codex"]["timed_out"] = True
            if mutation == "exit": changed["codex"]["exit_code"] = 1
            if mutation == "wrong_id": changed["codex"]["tool_calls"][1]["arguments"]["message_id"] = 43
            if mutation == "missing_read": changed["codex"]["tool_calls"] = changed["codex"]["tool_calls"][1:]
            if mutation == "wrong_run": changed["run_id"] = "other"
            if mutation == "failed_ack": changed["codex"]["tool_calls"][1]["success"] = False
            if mutation == "wrong_count": changed["codex"]["answer"]["lantern_count"] = 2
            if mutation == "wrong_answer_id": changed["codex"]["answer"]["message_id"] = 43
            if mutation == "missing_answer": changed["codex"]["answer"] = None
            self.assertFalse(native_pair_passed(changed), mutation)

    def test_audit_cursor_must_advance(self):
        self.assertEqual(advance_cursor(40, {"next_cursor": 90}), 90)
        for value in (40, 39, "90", None):
            with self.assertRaises(RuntimeError):
                advance_cursor(40, {"next_cursor": value})

    def test_parser_rejects_completed_mcp_tool_errors(self):
        class Fixture:
            def __init__(self, events): self.events = events
            def read_text(self, encoding): return "\n".join(json.dumps(event) for event in self.events)
        for error_key in ("isError", "is_error"):
            event = {"type": "item.completed", "item": {"type": "mcp_tool_call", "id": "call",
                     "tool": "ack_probe", "status": "completed", "arguments": {"message_id": 42},
                     "result": {error_key: True, "structuredContent": {"message_id": 42}}}}
            self.assertFalse(summarize_events(Fixture([event]))["tool_calls"][0]["success"])
            event["item"]["result"][error_key] = False
            parsed = summarize_events(Fixture([event, {"type": "item.completed", "item": {
                        "type": "agent_message", "text": '{"message_id":42,"lantern_count":3}'}}]))
            self.assertTrue(parsed["tool_calls"][0]["success"])
            self.assertEqual(parsed["answer"], {"message_id": 42, "lantern_count": 3})

    def test_fresh_root_startup_timeout_retains_failure_report(self):
        root = native_check.EVIDENCE_ROOT / "tests" / str(uuid4())
        root.mkdir(parents=True)
        exe = root / "fixture.exe"
        exe.touch()
        self.assertFalse((root / "evidence").exists())
        with patch.object(native_check, "ROOT", root), \
             patch.object(native_check, "EVIDENCE_ROOT", root / "evidence"), \
             patch.object(native_check.sys, "argv", ["native_check.py", "--codex-exe", str(exe),
                          "--claude-exe", str(exe)]), \
             patch.object(native_check.subprocess, "run", side_effect=subprocess.TimeoutExpired("fixture", 15)), \
             patch.object(native_check.subprocess, "Popen") as spawn:
            self.assertEqual(native_check.main(), 1)
            spawn.assert_not_called()
        reports = list((root / "evidence").glob("native-*/report.json"))
        self.assertEqual(len(reports), 1)
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        self.assertFalse(report["native_pair_passed"])
        self.assertIsNone(report["owned_server_pid"])
        self.assertIn("timed out", report["checker_error"])


if __name__ == "__main__":
    unittest.main()
