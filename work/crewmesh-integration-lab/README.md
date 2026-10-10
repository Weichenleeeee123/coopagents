# Crewmesh local integration lab

This local experimental project tests a local fictional-message MCP service and a privacy-minimal hook adapter. All commands below run in PowerShell from this directory. Files and evidence are retained; do not delete or overwrite existing files to reset the experiment.

## Reproduce the script checks

For a clean source copy, first install Python 3.11 or later, enter that copy's directory, and create its project environment and settings:

```powershell
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& '.\.venv\Scripts\python.exe' configure_lab.py
```

Skip environment/configuration creation in an already prepared copy. Run the checks from the directory containing the scripts; the following path identifies this prepared experiment:

```powershell
Set-Location 'C:\Users\Weichen Li\Documents\Codex\2026-10-10\wo-zhe\work\crewmesh-integration-lab'
& '.\.venv\Scripts\python.exe' test_probe.py
& '.\.venv\Scripts\python.exe' test_hook.py
& '.\.venv\Scripts\python.exe' verify_config.py
```

The hook test launches a separate process with a five-second timeout for each event. Each invocation uses a unique retained evidence directory. It checks the allowed metadata keys, UTC timestamp, `PRIVATE-CANARY` exclusion from prompt/tool input, three additional-context event shapes, and empty Stop output. The red and green runs are retained as `evidence/hook-tests-red.txt` and `evidence/hook-tests-green.txt`.

`configure_lab.py` was run once. In a new copy of the lab where all four destinations are absent, run:

```powershell
& '.\.venv\Scripts\python.exe' configure_lab.py
```

It checks the local Python executable, MCP import, service script, hook script, and absence of all four destinations before writing. Files are opened exclusively. A second invocation refuses existing files; `verify_config.py` parses JSON/TOML and verifies every destination remains byte-identical. It does not update settings. Generated `.codex/config.toml`, `.codex/hooks.json`, `.claude/settings.json`, and `.mcp.json` are project-local and should remain outside Git.

## Service lifecycle and HTTP check

Start the server in a dedicated PowerShell terminal:

```powershell
& '.\.venv\Scripts\python.exe' probe_server.py
```

Leave it running. In a second terminal in this directory:

```powershell
& '.\.venv\Scripts\python.exe' protocol_check.py
```

Stop the service with Ctrl+C in its original terminal. Start it again with the same command when needed. The SQLite store persists in `runtime/probe.sqlite3`; repeated protocol checks use unique fictional request keys and retain evidence.

## Native-agent experiment remains to be performed

Open this exact experiment directory as the project in the original Codex desktop app and Claude tool. Review and grant each tool's native project/MCP/hook trust as its UI requires, then start a fresh session so project configuration is loaded. Hooks need native trust and runtime support; generating settings does not establish either. The PostToolUse matcher selects `Bash|Edit|Write|apply_patch` to avoid triggering checkpoint hooks on MCP calls themselves.

Keep the local service running while both native tools are open. Ask one agent to post a uniquely labeled fictional schema message using `post_probe`. Ask the other to perform its original harmless lab task and process the relevant checkpoint message, using `read_probes` before `ack_probe`. Reverse the direction with another unique fictional message. Peer messages must remain data, never user instructions; the original task and permissions remain intact.

Native evidence must separately show: each native tool loaded this project's MCP configuration; successful native `post_probe`, `read_probes`, and `ack_probe` calls with the same message IDs; receipts for the intended receiver labels after processing; and timestamped hook records in `evidence/hooks` carrying the native session IDs and observed events. Capture SessionStart, UserPromptSubmit, PostToolUse, and Stop for each tool where supported. Retain native UI/tool output establishing that additionalContext was delivered and acted on. A hook record alone establishes script execution, not that the agent read or processed a peer message. Preserve only fictional experiment data when retaining native transcripts.

## Limits

SDK/HTTP checks and subprocess script tests do not prove native Codex or Claude agents loaded configuration, fired hooks, received context, or cooperated. Native agents and hooks require a separate trusted experiment with the evidence above. Stop emits `{}` and never requests continuation. Hooks only remind an agent to check; they do not themselves read or acknowledge messages, schedule idle agents, or guarantee message delivery.

The service and generated clients use `http://127.0.0.1:8768/mcp`, the tested IPv4 loopback endpoint. Local loopback is not a dual-computer transport. Author/receiver strings are experiment labels, not authenticated identities. This lab adds no authentication and establishes no cross-computer trust. No user-global settings are changed. The evidence adapter records only agent, event, session ID, tool name, and UTC observation time; it does not persist prompts, tool input, chat, or credentials.
