# 0.9 Release Acceptance Report

Date: 2026-10-30 (Asia/Taipei)

Status: 0.9.0 is published as GitHub Release `v0.9.0` and is available on PyPI. The report does not claim real multi-device, public deployment, native harness hooks, idle wake, or live GitHub App acceptance.

## Delivered stages

- `d3431f9`: explicit project asset storage, SHA-256 metadata, project/member isolation, paired SQLite/asset backup and restore.
- `4235fa2`: authenticated multipart HTTP upload/list/download and MCP `list_assets`/`read_asset` operations.
- `8c3cf12`: self-hosted asset workbench, explicit upload UI, source references, activity filters, stale/unavailable labels, task navigation, static resource allowlist fixes and deployment limits.
- `d23023f`, `fcc8d19`, `5957954`: shared harness adapter contract, official auth interpolation, bounded MCP asset reads, permission hardening and project MCP configuration adapters for Cursor, OpenCode, Pi, Kimi Code and ZCode.

## Acceptance evidence

| Check | Result |
| --- | --- |
| Complete Python suite on Python 3.13.3 with service + space extras | 607 passed; one Windows symlink-mode test skipped |
| JavaScript UI regressions | 13 scripts passed |
| Harness adapter focused tests | 6 tests passed, including all five config shapes |
| Compose configuration | `docker compose config --quiet` passed with a synthetic domain variable |
| Package identity/build | version `0.9.0`; sdist and wheel built successfully |
| Package metadata | `twine check` passed for both artifacts |
| GitHub release | [v0.9.0](https://github.com/Weichenleeeee123/coopagents/releases/tag/v0.9.0), assets include wheel, sdist, deploy ZIP and `SHA256SUMS.txt` |
| PyPI publication | Trusted Publishing workflow [40991695099](https://github.com/Weichenleeeee123/coopagents/actions/runs/40991695099) succeeded; PyPI index reports `0.9.0` as latest |
| Real loopback browser | Account, two projects, explicit upload/download, project-relative source, task navigation, project isolation, real-time online state passed |
| Mobile layout | 390px browser check kept document and body width at 390px; no horizontal overflow |
| Privacy marker scan | Private marker matches exist only in deliberate tests and privacy documentation; no product runtime payload or renderer consumes them |

The browser walkthrough used `127.0.0.1` and an ignored `.local/asset-ui-qa.sqlite3` data root. It is local evidence only. The Docker engine was not used for this run.

## Harness adapter contract

All five adapters configure project-local MCP entries and reference `COOPAGENTS_AGENT_TOKEN` rather than writing a token value:

| Harness | Config | Transport |
| --- | --- | --- |
| Cursor | `.cursor/mcp.json` / `mcpServers` | remote streamable HTTP |
| OpenCode | `opencode.json` / `mcp` | remote streamable HTTP |
| Pi | `.pi/mcp.json` / `mcpServers` | remote streamable HTTP |
| Kimi Code | `.kimi-code/mcp.json` / `mcpServers` | remote streamable HTTP |
| ZCode | `.zcode/config.json` / `mcp.servers` | remote streamable HTTP |

Config writes preserve unrelated entries, are idempotent, refuse conflicting same-name entries, and reject symlink/path escape targets. `native_hook` and `idle_wake` remain `unknown` or `unsupported`; no adapter claims that an agent will wake or consume messages automatically.

## Remaining 1.0 gates

- Real GitHub App install, callback, webhook, revoke and reauthorization against a dedicated repository.
- Two physical devices, NAT/relay behavior, restart recovery and cross-device agent acceptance.
- Real CLI acceptance for each harness and any native hook/ACP/idle-wake claim.
- CI/container evidence for the final release environment.
