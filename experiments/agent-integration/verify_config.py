"""Parse project configs and prove repeated generation refuses without mutation."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from uuid import uuid4
from configure_lab import DESTINATIONS
from lab_paths import EVIDENCE_ROOT

ROOT = Path(__file__).resolve().parent


def main():
    paths = [ROOT / name for name in DESTINATIONS]
    before = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    config = tomllib.loads(paths[0].read_text(encoding="utf-8"))
    assert config["mcp_servers"]["coopagents_probe"]["url"] == "http://127.0.0.1:8768/mcp"
    for path, agent in ((paths[1], "codex"), (paths[2], "claude")):
        hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
        assert set(hooks) == {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}
        assert hooks["PostToolUse"][0]["matcher"] == "Bash|Edit|Write|apply_patch"
        for event in hooks.values():
            command = event[0]["hooks"][0]
            assert command["timeout"] == 5
            assert command["command"] == f'"{Path(sys.executable).resolve()}" "{ROOT / "hook_probe.py"}" --agent {agent}'
    assert json.loads(paths[3].read_text(encoding="utf-8")) == {"mcpServers": {"coopagents_probe": {"type": "http", "url": "http://127.0.0.1:8768/mcp"}}}
    retry = subprocess.run([sys.executable, str(ROOT / "configure_lab.py")], capture_output=True, text=True, timeout=5)
    after = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert retry.returncode != 0
    assert before == after
    refusal = json.loads(retry.stderr)
    assert set(refusal["existing_destinations"]) == set(DESTINATIONS)
    record = {"parsed_json_and_toml": True, "repeat_returncode": retry.returncode,
              "repeat_refusal": refusal, "unchanged_sha256": after}
    destination = EVIDENCE_ROOT / f"config-verification-{uuid4()}.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"verified": True, "evidence": str(destination)}))


if __name__ == "__main__":
    main()
