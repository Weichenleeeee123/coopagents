"""Real local Git authorization tests; generated repositories are retained."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import unittest
from uuid import uuid4

MODULE_DIR = Path(__file__).resolve().parents[1] / "experiments" / "agent-integration" / "dsh_sandbox"
sys.path.insert(0, str(MODULE_DIR))
import fixture_repo
import private_git


class PrivateGitTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / ".local" / ("git-" + uuid4().hex[:8])
        fixture = fixture_repo.prepare_fixture(self.root / "fixture", seed="private-git-test")
        projects = {role: Path(item["project"]) for role, item in fixture["participants"].items()}
        self.service = self.root / "service"
        self.repos = private_git.prepare_private_git(self.service, projects)

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                              text=True, timeout=20).stdout.strip()

    def clone_role(self, role, name):
        clone = self.root / name
        subprocess.run(["git", "clone", "--quiet", str(self.repos[role]), str(clone)], check=True,
                       capture_output=True, text=True, timeout=20)
        return clone

    def test_bare_repositories_preserve_role_object_isolation_and_have_no_host_remote(self):
        refs = {}
        for role, repo in self.repos.items():
            self.assertTrue((repo / "hooks" / "pre-receive").is_file())
            self.assertEqual(self.git(repo, "symbolic-ref", "HEAD"), f"refs/heads/agent/{role}")
            refs[role] = self.git(repo, "rev-parse", "refs/heads/agent/" + role)
        self.assertEqual(len(set(refs.values())), 3)
        self.assertEqual(self.git(self.repos["frontend"], "remote"), "")
        self.assertNotIn("backend/schema.json", self.git(self.repos["frontend"], "ls-tree", "-r", "--name-only", "HEAD"))

    def test_own_branch_push_succeeds_but_other_refs_and_other_role_branch_fail(self):
        clone = self.clone_role("frontend", "frontend-client")
        self.git(clone, "config", "user.name", "Synthetic Member")
        self.git(clone, "config", "user.email", "member@invalid.example")
        (clone / "src" / "note.txt").write_text("allowed\n", encoding="utf-8")
        self.git(clone, "add", "src/note.txt")
        self.git(clone, "commit", "--quiet", "-m", "allowed change")
        self.git(clone, "push", "origin", "HEAD:refs/heads/agent/frontend")
        self.assertEqual(self.git(self.repos["frontend"], "rev-parse", "agent/frontend"),
                         self.git(clone, "rev-parse", "HEAD"))
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(clone, "push", "origin", "HEAD:refs/heads/agent/backend")
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(clone, "push", "origin", "HEAD:refs/tags/escape")

    def test_branch_deletion_and_non_fast_forward_updates_are_denied(self):
        clone = self.clone_role("integration", "integration-client")
        stale = self.clone_role("integration", "integration-stale-client")
        self.git(clone, "config", "user.name", "Synthetic Member")
        self.git(clone, "config", "user.email", "member@invalid.example")
        self.git(stale, "config", "user.name", "Stale Synthetic Member")
        self.git(stale, "config", "user.email", "stale@invalid.example")
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(clone, "push", "origin", ":refs/heads/agent/integration")
        (clone / "first.txt").write_text("first\n", encoding="utf-8")
        self.git(clone, "add", "first.txt")
        self.git(clone, "commit", "--quiet", "-m", "first")
        self.git(clone, "push", "origin", "HEAD:refs/heads/agent/integration")
        (stale / "stale.txt").write_text("stale\n", encoding="utf-8")
        self.git(stale, "add", "stale.txt")
        self.git(stale, "commit", "--quiet", "-m", "divergent update")
        old = self.git(self.repos["integration"], "rev-parse", "refs/heads/agent/integration")
        new = self.git(stale, "rev-parse", "HEAD")
        hook = self.repos["integration"] / "hooks" / "pre-receive"
        environment = os.environ.copy()
        environment["GIT_DIR"] = str(self.repos["integration"])
        shell = shutil.which("sh")
        if not shell:
            self.skipTest("a POSIX shell is required to execute Git's pre-receive hook locally")
        with self.assertRaises(subprocess.CalledProcessError):
            subprocess.run([shell, str(hook)], input=f"{old} {new} refs/heads/agent/integration\n",
                           text=True, capture_output=True, check=True, timeout=10, env=environment)
        self.assertEqual(self.git(self.repos["integration"], "rev-parse", "refs/heads/agent/integration"), old)

    def test_forced_command_is_fixed_role_scoped_and_rejects_untrusted_commands(self):
        command = private_git.command_for("frontend", self.service, "git-upload-pack 'frontend.git'")
        self.assertEqual(command[2], str(self.repos["frontend"]))
        for bad in ("sh", "git-upload-pack '../../backend.git'", "git-upload-pack 'frontend.git';id",
                    "git-receive-pack 'backend.git'", "git-upload-pack 'frontend.git' --foo"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                private_git.command_for("frontend", self.service, bad)
        with self.assertRaises(ValueError):
            private_git.command_for("../../backend", self.service, "git-upload-pack 'backend.git'")

    def test_sshd_fragment_binds_separate_accounts_to_forced_role_commands(self):
        fragment = private_git.sshd_config_fragment(self.service, "10.20.0.8")
        self.assertIn("ListenAddress 10.20.0.8", fragment)
        self.assertIn("PasswordAuthentication no", fragment)
        self.assertIn("one Unix account per role", fragment)
        for role in private_git.ROLES:
            self.assertIn(f"Match User git-{role}", fragment)
            self.assertIn(f"--role {role}", fragment)
        self.assertIn("DisableForwarding yes", fragment)
        self.assertIn("PermitTTY no", fragment)
        with self.assertRaises(ValueError):
            private_git.sshd_config_fragment(self.service, "0.0.0.0")


if __name__ == "__main__":
    unittest.main()
