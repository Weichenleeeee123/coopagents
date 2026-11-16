"""Local fixture isolation tests; generated Git repositories are retained."""

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from uuid import uuid4

MODULE_DIR = Path(__file__).resolve().parents[1] / "experiments" / "agent-integration" / "dsh_sandbox"
sys.path.insert(0, str(MODULE_DIR))
import fixture_repo
import role_goals


class FixtureRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / ".local" / "dsh-sandbox-fixture-tests" / uuid4().hex

    def files(self, root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*") if path.is_file() and ".git" not in path.parts}

    def git(self, project, *args):
        return subprocess.run(["git", "-C", str(project), *args], capture_output=True,
                              text=True, check=True, timeout=10).stdout.strip()

    def test_builds_three_independent_role_repositories_with_private_oracle(self):
        manifest = fixture_repo.prepare_fixture(self.root, seed="paired-seed")
        roles = {"frontend", "backend", "integration"}
        self.assertEqual(set(manifest["participants"]), roles)
        self.assertEqual(Path(manifest["oracle_path"]), self.root.resolve() / "harness-private" / "oracle.json")
        oracle = json.loads(Path(manifest["oracle_path"]).read_text(encoding="utf-8"))
        marker = oracle["expected_wire_field"]
        self.assertRegex(marker, r"^profile_[0-9a-f]{32}$")
        self.assertEqual(oracle["expected_type"], "string")
        self.assertEqual(oracle["fixture_name"], "sample-profile")

        expected_files = {
            "frontend": {"README.md", "src/profile.ts", "src/client.ts"},
            "backend": {"README.md", "app.py", "backend/schema.json"},
            "integration": {"README.md", "tests/test_profile_contract.py"},
        }
        repositories = []
        for role, participant in manifest["participants"].items():
            project = Path(participant["project"])
            self.assertEqual(project, self.root.resolve() / role / "project")
            self.assertEqual(set(self.files(project)), expected_files[role])
            self.assertEqual(self.git(project, "branch", "--show-current"), f"agent/{role}")
            if role != "backend":
                self.assertNotIn(marker.encode(), b"\n".join(self.files(project).values()))
            repositories.append(self.git(project, "rev-parse", "--absolute-git-dir"))
        self.assertEqual(len(set(repositories)), 3)
        backend_schema = json.loads((self.root / "backend/project/backend/schema.json").read_text(encoding="utf-8"))
        self.assertEqual(backend_schema, {"wire_field": marker, "type": "string"})
        self.assertFalse((self.root / "frontend/project/.git").resolve() == (self.root / "backend/project/.git").resolve())
        self.assertNotIn("seed", json.dumps(manifest).lower())

    def test_same_seed_reproduces_fixture_and_new_seed_changes_private_marker(self):
        first = fixture_repo.prepare_fixture(self.root / "arm-a", seed="scenario-seed")
        paired = fixture_repo.prepare_fixture(self.root / "arm-b", seed="scenario-seed")
        changed = fixture_repo.prepare_fixture(self.root / "arm-c", seed="other-seed")
        read_marker = lambda item: json.loads(Path(item["oracle_path"]).read_text(encoding="utf-8"))["expected_wire_field"]
        self.assertEqual(read_marker(first), read_marker(paired))
        self.assertNotEqual(read_marker(first), read_marker(changed))
        self.assertEqual(self.files(Path(first["participants"]["frontend"]["project"])),
                         self.files(Path(paired["participants"]["frontend"]["project"])))

    def test_role_goals_are_outcome_focused_and_do_not_name_protocol_tools(self):
        goals = role_goals.role_goals()
        self.assertEqual(set(goals), {"frontend", "backend", "integration"})
        forbidden = re.compile(r"\b(?:MCP|CLI|ask_owner|read_replies|work_brief|checkpoint|send_request|reply|read_team)\b", re.I)
        for goal in goals.values():
            self.assertIsInstance(goal, str)
            self.assertGreater(len(goal), 80)
            self.assertIsNone(forbidden.search(goal))
        self.assertIn("profile", goals["frontend"].lower())
        self.assertIn("backend", goals["frontend"].lower())
        self.assertIn("integration", goals["integration"].lower())

    def test_invalid_input_and_existing_root_never_overwrite_files(self):
        with self.assertRaises((ValueError, TypeError)):
            fixture_repo.prepare_fixture(self.root, seed=object())
        self.assertFalse(self.root.exists())
        self.root.mkdir(parents=True)
        sentinel = self.root / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            fixture_repo.prepare_fixture(self.root, seed="ok")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
