"""One-shot project configuration. Refuses any existing destination."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
DESTINATIONS = (".codex/config.toml", ".codex/hooks.json", ".claude/settings.json", ".mcp.json")


def main():
    python = Path(sys.executable).resolve()
    hook = ROOT / "hook_probe.py"
    # Complete preflight before creating any directory or destination file.
    missing = [str(path) for path in (python, hook, ROOT / "probe_server.py") if not path.is_file()]
    existing = [name for name in DESTINATIONS if (ROOT / name).exists()]
    if missing or existing:
        print(json.dumps({"refused": True, "missing_dependencies": missing,
                          "existing_destinations": existing}), file=sys.stderr)
        return 1
    check = subprocess.run([str(python), "-c", "import mcp"], capture_output=True, timeout=5)
    if check.returncode:
        print("refused: virtual environment cannot import mcp", file=sys.stderr)
        return 1

    def hooks(agent):
        command = f'"{python}" "{hook}" --agent {agent}'
        result = {}
        for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
            group = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
            if event == "PostToolUse":
                group["matcher"] = "Bash|Edit|Write|apply_patch"
            result[event] = [group]
        return {"hooks": result}

    files = {
        ".codex/config.toml": '[mcp_servers.coopagents_probe]\nurl = "http://127.0.0.1:8768/mcp"\n',
        ".codex/hooks.json": json.dumps(hooks("codex"), indent=2) + "\n",
        ".claude/settings.json": json.dumps(hooks("claude"), indent=2) + "\n",
        ".mcp.json": json.dumps({"mcpServers": {"coopagents_probe": {
            "type": "http", "url": "http://127.0.0.1:8768/mcp"}}}, indent=2) + "\n",
    }
    for name, content in files.items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    print(json.dumps({"created": list(files)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
