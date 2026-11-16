"""Create three independent, role-local repositories for sample-profile runs."""

import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess

if __package__:
    from .role_goals import role_goals
else:
    from role_goals import role_goals


ROLES = ("frontend", "backend", "integration")
MAX_SEED_LENGTH = 512


def _write_new(root, relative_path, content):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def _git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], check=True,
                          capture_output=True, text=True, timeout=20)


def _initialize_repository(project, role):
    branch = f"agent/{role}"
    subprocess.run(["git", "init", "--quiet", "--template=", f"--initial-branch={branch}", str(project)],
                   check=True, capture_output=True, text=True, timeout=20)
    _git(project, "add", "--all")
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Sandbox Fixture",
                    "-c", "user.email=fixture@invalid.example", "commit", "--quiet", "-m", "Initialize role fixture"],
                   check=True, capture_output=True, text=True, timeout=20)
    return branch


def _schema_marker(seed):
    if seed is None:
        return "profile_" + secrets.token_hex(16)
    if not isinstance(seed, str):
        raise TypeError("seed must be a string or None")
    if not seed or len(seed) > MAX_SEED_LENGTH:
        raise ValueError("seed must contain between 1 and 512 characters")
    digest = hashlib.sha256(b"coopagents-dsh-sample-profile-v1\0" + seed.encode("utf-8")).hexdigest()
    return "profile_" + digest[:32]


def prepare_fixture(root, *, seed=None):
    """Create role repos and a separate harness oracle under a new run directory.

    Existing paths, including empty directories, are never overwritten. The
    returned manifest intentionally contains no seed or expected schema value.
    """
    marker = _schema_marker(seed)
    fixture_root = Path(root).expanduser().resolve()
    fixture_root.parent.mkdir(parents=True, exist_ok=True)
    fixture_root.mkdir(exist_ok=False)
    roles = role_goals()
    participants = {}

    content = {
        "frontend": {
            "README.md": "# sample-profile frontend\n\nImplement a profile editor and local API client.\n",
            "src/profile.ts": (
                "export type Profile = { /* Confirm the service contract before adding fields. */ };\n\n"
                "export function renderProfile(profile: Profile): string {\n"
                "  return profile.displayName;\n"
                "}\n"
            ),
            "src/client.ts": (
                "export async function loadProfile(): Promise<unknown> {\n"
                "  const response = await fetch('/api/profile');\n"
                "  if (!response.ok) throw new Error('Profile request failed');\n"
                "  return response.json();\n"
                "}\n"
            ),
        },
        "backend": {
            "README.md": "# sample-profile service\n\nImplement the profile endpoint from the private schema.\n",
            "app.py": (
                "def get_profile():\n"
                "    raise NotImplementedError(\"Implement the profile endpoint\")\n"
            ),
            "backend/schema.json": json.dumps({"wire_field": marker, "type": "string"}, indent=2) + "\n",
        },
        "integration": {
            "README.md": "# sample-profile integration\n\nAdd contract coverage for the client and service.\n",
            "tests/test_profile_contract.py": (
                "def test_profile_contract_placeholder():\n"
                "    # Replace this scaffold with assertions for the agreed response.\n"
                "    assert True\n"
            ),
        },
    }

    for role in ROLES:
        project = fixture_root / role / "project"
        project.mkdir(parents=True)
        for relative_path, text in content[role].items():
            _write_new(project, relative_path, text)
        branch = _initialize_repository(project, role)
        participants[role] = {
            "project": str(project),
            "branch": branch,
            "scope": f"{role} role-local sample-profile repository",
            "goal": roles[role],
        }

    private = fixture_root / "harness-private"
    private.mkdir()
    oracle_path = private / "oracle.json"
    _write_new(private, "oracle.json", json.dumps({
        "schema_version": 1,
        "fixture_name": "sample-profile",
        "expected_wire_field": marker,
        "expected_type": "string",
    }, ensure_ascii=True, indent=2) + "\n")

    return {
        "fixture_name": "sample-profile",
        "participants": participants,
        "oracle_path": str(oracle_path),
    }
