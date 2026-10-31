# Contributing to Coopagents

[简体中文](docs/CONTRIBUTING.zh-CN.md)

Coopagents connects people’s coding agents around a shared project. Contributions should add composable capabilities without requiring a fixed team workflow. Keep configuration, transport connectivity, agent activity and verified delivery evidence distinct.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/` | Python package, mapped to the import name `coopagents` |
| `src/static/` | Production web workbench and read-only board; plain HTML, CSS and JavaScript |
| `src/skills/` | Bundled agent setup and connection Skills |
| `tests/` | Domain, HTTP, transport and JavaScript regression tests |
| `docs/` | Maintained guides, designs, plans and acceptance reports |
| `docs/prototypes/` | Design references; not the production frontend |
| `experiments/agent-integration/` | Native agent integration experiments |
| `deploy/` | Deployment configuration and dependency constraints |
| `.local/` | Ignored local databases, private evidence and runtime state |

The P2P space and self-hosted service share `CoordinationService`, domain storage, HTTP/MCP operations and real-time events. Change shared business rules in their common implementation; keep entry-point differences in `space_runtime.py`, `space_server.py` and the account composition layer.

## Development setup

Use Python 3.11+ and Node.js (CI uses Node 22). Create a dedicated virtual environment for each checkout. Always call its interpreter explicitly; activation is unnecessary.

Windows PowerShell:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -c deploy/constraints.txt -e ".[service,space]" build
& .\.venv\Scripts\python.exe -c "import coopagents; print(coopagents.__file__)"
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c deploy/constraints.txt -e '.[service,space]' build
.venv/bin/python -c 'import coopagents; print(coopagents.__file__)'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
```

Confirm that the printed package path belongs to this checkout. An editable install from another worktree can otherwise test the wrong code. The standard-library domain package alone needs only `pip install -e .`; the full suite requires both `service` and `space` extras. Dependency declarations live in `pyproject.toml` and the reproducible release constraints in `deploy/constraints.txt`.

For a running instance, follow [local service setup](docs/app-running.md) or [space runtime](docs/agent-hosted-runtime.md). Keep credentials and databases under private local paths. Do not use a real team database for UI experiments.

## Web checks

There is no frontend build step. Run the JavaScript checks in [.github/workflows/ci.yml](.github/workflows/ci.yml), including the scripts that take explicit source arguments:

```text
node tests/web_session_regression.js src/static/app.js
node tests/agent_connect_ui_regression.js src/static/app.js
node tests/account_ui_regression.js src/static/accounts.js
node tests/billing_ui_regression.js src/static/billing.js src/static/accounts.js
```

Other `tests/*_regression.js` scripts run without arguments. Check changed browser scripts with `node --check <file>` as well. When changing UI, verify it against the approved [workspace prototype](docs/prototypes/project-workspace/index.html) in an actual browser at desktop and mobile widths. Structural tests alone do not establish visual parity. Exercise the real backend, permissions, empty states and project switching; use synthetic data for screenshots.

## Changes and evidence

- Submit source, tests and documentation in coherent stages. Explain the user-visible behavior and the checks you actually ran.
- Keep maintained documentation in `docs/`. English is the default for the README and contribution guide; update their Chinese companions together.
- Preserve unrelated agent configuration. Installation success does not prove the current native session loaded MCP, trusted a hook or consumed a message.
- Never claim all harnesses support wake-up. Record native-tool and platform limitations in the [adapter support matrix](docs/harness-adapters-0.9.md) and acceptance reports.
- Never commit credentials, personal configuration, real conversations, test databases or raw experiment records.
- **Never delete files.** If deletion is necessary, stop and ask the repository owner to perform it. Preserve generated databases and evidence; do not use automatically cleaned temporary directories.

## Release verification

CI covers Python 3.11 and 3.13, native JavaScript regressions, integration experiments, Python distributions, container startup and TLS smoke. Run checks appropriate to your change and report anything not exercised.

Build the distribution with your environment’s interpreter: `<python> -m build`. For deployment changes, with a running Docker engine:

```text
docker build -t coopagents:local-check .
python scripts/deployment_smoke.py --image coopagents:local-check
```

Run `docker compose ... config --quiet` to validate deployment combinations without printing expanded secrets. Docker CLI availability alone is not evidence of a running engine. Native acceptance requires actual authenticated tools; simulated data cannot substitute for model consumption or two-device connectivity.

See [deployment and recovery](docs/deployment.md), [agent-first setup acceptance](docs/agent-first-setup-acceptance.md), [two-machine acceptance](docs/two-machine-acceptance.md) and the [documentation index](docs/README.md). Report security issues privately as described in [SECURITY.md](SECURITY.md).
