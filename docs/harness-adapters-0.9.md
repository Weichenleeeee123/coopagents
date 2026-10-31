# 0.9 Harness MCP Adapters

## Native space connections

The primary P2P setup path uses the bundled `coopagents-space` Skill and the harness's native MCP CLI. It does not require a web account. Published 0.9.0 and the newer, unreleased doctor flow have different setup capabilities; see [agent-first setup](agent-first-setup.md).

| Harness | Connection | Optional wake | Evidence boundary |
| --- | --- | --- | --- |
| Claude Code | Native MCP registration and personal space profile | Idle wake through installed hooks, while the session remains open | Real single-machine Windows collaboration; other OS and cross-device wake remain separate acceptance gates |
| Codex | Native MCP registration and personal space profile | End-of-turn check; explicit standby can wait. No ordinary idle wake. User reviews new hooks in `/hooks` | Real single-machine Windows collaboration; CLI registration is separate from loading MCP in a fresh model session |

The [single-machine acceptance report](solo-acceptance-2026-10-29.md), [setup diagnostic acceptance](agent-first-setup-acceptance.md) and [two-machine checklist](two-machine-acceptance.md) describe what has and has not been verified. A session registration is not proof that a model is currently active, and an MCP configuration adapter is not a native wake adapter.

## Remote MCP configuration adapters

The 0.9 adapter contract configures a project-local MCP server without reading or copying agent conversations. The adapter writes only the harness's documented project configuration file, preserves unrelated JSON entries, refuses symlink/path escapes, and refuses to overwrite a different existing `coopagents` entry. Re-running an identical install is idempotent.

The CLI is:

```powershell
python -m coopagents.harness_adapters --list
python -m coopagents.harness_adapters --harness cursor --project . --service-url https://team.example/mcp
python -m coopagents.harness_adapters --harness cursor --project . --service-url https://team.example/mcp --install
```

The generated remote entry references `COOPAGENTS_AGENT_TOKEN` and never stores the token value. Cursor and ZCode entries use `${env:NAME}`, Pi uses `${NAME}`, and OpenCode uses `{env:NAME}` config interpolation. OpenCode's syntax is confirmed against its [1.1.65 configuration loader](https://github.com/anomalyco/opencode/blob/v1.1.65/packages/opencode/src/config/config.ts); `${NAME}` is not expanded by that loader. Kimi Code's generated `bearerTokenEnvVar` field remains unverified. The user must export that variable in the harness's process environment and start a new agent session after changing MCP configuration. The HTTP endpoint must be HTTPS, or loopback HTTP for local development.

| Harness | Project config | Entry shape | Native hook / idle wake |
| --- | --- | --- | --- |
| Cursor | `.cursor/mcp.json` | `mcpServers[name]` with remote URL | unknown / unsupported |
| OpenCode | `opencode.json` | `mcp[name]` with `type: remote` | unknown / unsupported |
| Pi | `.pi/mcp.json` | `mcpServers[name]` with remote URL | unsupported / unsupported |
| Kimi Code | `.kimi-code/mcp.json` (generated path; native autodiscovery unverified) | `mcpServers[name]` with remote URL; `bearerTokenEnvVar` unverified | unsupported / unsupported |
| ZCode | `.zcode/config.json` | `mcp.servers[name]` with remote URL | unsupported / unsupported |

These statuses are intentionally conservative. MCP setup is implemented and tested as a remote configuration contract; a harness's native hooks, plugins, ACP transport or idle wake are not claimed until that exact combination has a real acceptance result. Pi's extension API, Kimi ACP and ZCode hooks remain available for a later verified adapter extension. Without `--service-url`, the CLI emits a manual plan and deliberately does not write a dead local runner.

Kimi Code's [official MCP guide](https://github.com/MoonshotAI/kimi-cli/blob/main/docs/en/customization/mcp.md) documents global `~/.kimi/mcp.json` and explicit `kimi --mcp-config-file <path>` loading. It does not establish automatic loading of the adapter's `.kimi-code/mcp.json` or support for its `bearerTokenEnvVar` field. Generated JSON and fixture tests do not establish native Kimi authentication or session loading; both remain acceptance blockers.

The adapter does not install a native hook, parse session files, inspect prompts, or upload any project files. It only makes the MCP server available to a new session. Existing local P2P board security and the rule against sharing full conversation text are unchanged.

## Verification

- Five adapter capability reports and configuration contracts pass focused tests.
- Cursor, OpenCode, Pi, Kimi Code and ZCode remote config shapes are generated with a placeholder environment reference and no credential value.
- Existing authenticated MCP task/message behavior remains covered by the full Python suite; unavailable native CLIs are reported as unverified rather than simulated.
