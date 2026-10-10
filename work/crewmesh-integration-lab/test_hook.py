"""Subprocess checks for the privacy-minimal hook adapter; evidence is retained."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4
from datetime import datetime

ROOT = Path(__file__).resolve().parent


class HookTests(unittest.TestCase):
    def invoke(self, event):
        evidence = ROOT / "evidence" / "hook-tests" / str(uuid4())
        payload = {"hook_event_name": event, "session_id": "fictional-session",
                   "tool_name": "Bash", "prompt": "PRIVATE-CANARY",
                   "tool_input": {"command": "PRIVATE-CANARY"}}
        result = subprocess.run(
            [sys.executable, str(ROOT / "hook_probe.py"), "--agent", "codex",
             "--evidence-dir", str(evidence)], input=json.dumps(payload),
            text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        records = list(evidence.glob("*.json"))
        self.assertEqual(len(records), 1)
        raw = records[0].read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE-CANARY", raw + result.stdout + result.stderr)
        record = json.loads(raw)
        self.assertEqual(set(record), {"agent", "event", "session_id", "tool_name", "observed_at"})
        self.assertEqual(record["agent"], "codex")
        self.assertEqual(record["event"], event)
        self.assertEqual(record["session_id"], "fictional-session")
        self.assertEqual(record["tool_name"], "Bash")
        self.assertEqual(datetime.fromisoformat(record["observed_at"]).utcoffset().total_seconds(), 0)
        return output

    def test_context_events(self):
        for event in ("SessionStart", "UserPromptSubmit", "PostToolUse"):
            with self.subTest(event=event):
                output = self.invoke(event)
                self.assertEqual(set(output), {"hookSpecificOutput"})
                detail = output["hookSpecificOutput"]
                self.assertEqual(set(detail), {"hookEventName", "additionalContext"})
                self.assertEqual(detail["hookEventName"], event)
                context = detail["additionalContext"]
                for fragment in ("read_probes", "fictional", "data", "user instructions", "ack_probe", "after processing", "original task", "permissions"):
                    self.assertIn(fragment, context)

    def test_stop(self):
        self.assertEqual(self.invoke("Stop"), {})

    def test_agent_required(self):
        result = subprocess.run([sys.executable, str(ROOT / "hook_probe.py")],
                                input="{}", text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)

    def test_malformed_input_does_not_echo_private_data(self):
        evidence = ROOT / "evidence" / "hook-tests" / str(uuid4())
        result = subprocess.run(
            [sys.executable, str(ROOT / "hook_probe.py"), "--agent", "claude",
             "--evidence-dir", str(evidence)], input='{ "prompt": "PRIVATE-CANARY"',
            text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("PRIVATE-CANARY", result.stdout + result.stderr)
        self.assertFalse(evidence.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
