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

The generated remote entry references `COOPAGENTS_AGENT_TOKEN` and never stores the token value, except for ZCode (see below). Cursor entries use `${env:NAME}`, verified against the [official Cursor MCP docs](https://prod.cursor.com/docs/mcp), which resolve variables in `command`, `args`, `env`, `url` and `headers`. Pi uses `${NAME}`. OpenCode uses `{env:NAME}` config interpolation, confirmed against its [1.1.65 configuration loader](https://github.com/anomalyco/opencode/blob/v1.1.65/packages/opencode/src/config/config.ts); `${NAME}` is not expanded by that loader. Kimi Code's `bearerTokenEnvVar` field and project-level `.kimi-code/mcp.json` autodiscovery are verified against the [official Kimi Code MCP docs](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp.html); project-level servers need workspace trust (headless runs need `KIMI_CODE_TRUST_WORKSPACE=1` or `[workspace] require_trust = false`). The user must export that variable in the harness's process environment and start a new agent session after changing MCP configuration. The HTTP endpoint must be HTTPS, or loopback HTTP for local development.

ZCode is the exception: ZCode config files do not expand `${env:}` or any other template, so a placeholder would reach the server literally as the token. The generated ZCode entry therefore carries no `Authorization` header; the bearer token belongs in user-scope `~/.zcode/cli/config.json` under the same server name, which overrides the workspace entry. ZCode's entry schema is strict — an entry carrying a key outside `type`/`url`/`headers`/`enabled`/`timeoutMs` is dropped silently — so the generated entry carries exactly `type: http`, `url` and `enabled`.

Pi is the other special case: Pi defaults MCP tools to `codemode` exposure, callable only from codemode scripts and not declared to the model. The generated Pi entry sets `exposure: direct`, which declares the tools like built-in tools. Pi project config is read only after the project is trusted.

| Harness | Project config | Entry shape | Native hook / idle wake |
| --- | --- | --- | --- |
| Cursor | `.cursor/mcp.json` | `mcpServers[name]` with remote URL | unknown / unsupported |
| OpenCode | `opencode.json` | `mcp[name]` with `type: remote` | unknown / unsupported |
| Pi | `.pi/mcp.json` | `mcpServers[name]` with remote URL, `exposure: direct` | unsupported / unsupported |
| Kimi Code | `.kimi-code/mcp.json` | `mcpServers[name]` with remote URL; `bearerTokenEnvVar` verified against official docs | unsupported / unsupported |
| ZCode | `.zcode/config.json` | `mcp.servers[name]` with remote URL, no header (auth in user scope) | unsupported / unsupported |

These statuses are intentionally conservative. MCP setup is implemented and tested as a remote configuration contract; a harness's native hooks, plugins, ACP transport or idle wake are not claimed until that exact combination has a real acceptance result. Pi's extension API, Kimi ACP and ZCode hooks remain available for a later verified adapter extension. Without `--service-url`, the CLI emits a manual plan and deliberately does not write a dead local runner.

Kimi Code's [official MCP docs](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp.html) document `bearerTokenEnvVar` as a field for HTTP/SSE servers and automatic discovery of project-level `.kimi-code/mcp.json` (a same-named project entry overrides the user-level file). The earlier note citing the archived `kimi-cli` guide (`~/.kimi/mcp.json`, explicit `--mcp-config-file`) described the old Python CLI, not the current Kimi Code CLI. Verified-against-docs is not live acceptance: native Kimi authentication and session loading in a real Kimi session remain acceptance blockers.

The adapter does not install a native hook, parse session files, inspect prompts, or upload any project files. It only makes the MCP server available to a new session. Existing local P2P board security and the rule against sharing full conversation text are unchanged.

## Verification

- Five adapter capability reports and configuration contracts pass focused tests.
- Cursor, OpenCode, Pi and Kimi Code remote config shapes are generated with a placeholder environment reference and no credential value. ZCode's entry carries no header because ZCode config files do not expand templates; its auth step is documented in the plan output.
- Existing authenticated MCP task/message behavior remains covered by the full Python suite; unavailable native CLIs are reported as unverified rather than simulated.
