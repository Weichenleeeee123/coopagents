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
| Cursor | `.cursor/mcp.json` | `mcpServers[name]` with remote URL | hook install (project or user scope), live acceptance unverified / unsupported |
| OpenCode | `opencode.json` | `mcp[name]` with `type: remote` | unknown / unsupported |
| Pi | `.pi/mcp.json` | `mcpServers[name]` with remote URL, `exposure: direct` | unsupported / unsupported |
| Kimi Code | `.kimi-code/mcp.json` | `mcpServers[name]` with remote URL; `bearerTokenEnvVar` verified against official docs | unsupported / unsupported |
| ZCode | `.zcode/config.json` | `mcp.servers[name]` with remote URL, no header (auth in user scope) | hook install (user scope), live acceptance unverified / unsupported |

These statuses are intentionally conservative. MCP setup is implemented and tested as a remote configuration contract; a harness's native hooks, plugins, ACP transport or idle wake are not claimed until that exact combination has a real acceptance result. Kimi ACP remains available for a later verified adapter extension. Without `--service-url`, the CLI emits a manual plan and deliberately does not write a dead local runner.

Pi's wake avenue is its [extension API](https://pi.dev/docs/latest/extensions), not shell hooks. A TypeScript extension auto-discovered from `.pi/extensions/` (project-local, after trust) or `~/.pi/agent/extensions/` (global) can subscribe to `session_start`, `before_agent_start` and `agent_end` via `pi.on()` and send a message with `pi.sendUserMessage()`; shell hooks (`agent_end.sh` in `.pi/hooks/`) are fire-and-forget scripts with a 30-second timeout and cannot inject context. No extension is installed by the adapter — extensions run inside the Pi process with full OS permissions, so installing one is a trust decision for the user — and the design is unverified until a real Pi session runs it.

Kimi Code's [official MCP docs](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp.html) document `bearerTokenEnvVar` as a field for HTTP/SSE servers and automatic discovery of project-level `.kimi-code/mcp.json` (a same-named project entry overrides the user-level file). The earlier note citing the archived `kimi-cli` guide (`~/.kimi/mcp.json`, explicit `--mcp-config-file`) described the old Python CLI, not the current Kimi Code CLI. Verified-against-docs is not live acceptance: native Kimi authentication and session loading in a real Kimi session remain acceptance blockers.

The adapter does not install a native hook, parse session files, inspect prompts, or upload any project files. It only makes the MCP server available to a new session. Existing local P2P board security and the rule against sharing full conversation text are unchanged.

### ZCode wake hooks (user scope)

Wake-up for ZCode is installed separately by `coopagents.space_wake`, not by the MCP adapter above. ZCode's [official hooks docs](https://zcode.z.ai/en/docs/hooks) specify the contract: hooks are subprocesses that read one JSON line on stdin and reply with stdout JSON; configuration-file hooks require `hooks.enabled: true`; and **project-level hooks are not executed** — any `hooks` configuration in `<workspace>/.zcode/config.json` is ignored as a whole and logged as `config_project_hooks_ignored`. Hooks therefore install to user-scope `~/.zcode/cli/config.json` only, and the installer refuses project scope.

The installed hooks mirror the Codex end-of-turn model: a `SessionStart` hook (matcher `startup|clear`, so a compact never swallows items that arrived during the session) only baselines the current items, and a `Stop` hook checks once when a turn ends and, with standby enabled (`space_wake standby on`), keeps the session waiting. On wake it returns `{"decision": "block", "reason": ...}` with the fixed counts-only template; ZCode caps consecutive Stop continuations at 3. The Stop hook sets `timeoutMs` to cover the standby budget, since ZCode's default hook timeout is 60 seconds. Install and disable preserve MCP servers and unrelated hooks in the same file, and never delete user configuration.

Hook installation is implemented and tested (config merge, idempotence, subprocess execution of the process hook). Whether a real ZCode session runs the hooks and wakes is unverified: ZCode is build-from-source with no public installer, and live acceptance needs a real ZCode session with a model backend.

A checkpoint-hook fragment for ZCode is generated separately by `python -m coopagents.checkpoint_hook --tool zcode --config-preview` (or `--export` to a file). It uses the same `hooks.events` shape with process hooks on `SessionStart` (matcher `startup`), `PostToolUse` and `UserPromptSubmit`; ZCode's stdin carries the Claude-compatible `session_id`/`hook_event_name` aliases, so the handler runs unchanged. The fragment is merged into user-scope `~/.zcode/cli/config.json` by hand — when re-applying it, remove the old `coopagents.checkpoint_hook` groups first — and it coexists with the wake hooks above: the wake installer never removes checkpoint groups, and disabling wake-up keeps them.

### Cursor hooks (project or user scope)

Cursor's [official hooks docs](https://cursor.com/docs/hooks) specify the contract: hooks are command processes defined in `hooks.json` (`version: 1`) at `<project>/.cursor/hooks.json` (project scope, loaded in trusted workspaces and shared through version control, including cloud agents) or `~/.cursor/hooks.json` (user scope). Each event maps to flat command definitions; exit 0 uses the JSON output, exit 2 blocks, and other exit codes fail open. Hook payloads carry `conversation_id` as the stable session identifier and camelCase event names.

Checkpoint hooks are generated by `python -m coopagents.checkpoint_hook --tool cursor --config-preview` (or `--export` to a file) and merged into `hooks.json` by hand. The fragment covers `sessionStart`, `postToolUse` and `beforeSubmitPrompt`, mapped to the canonical `SessionStart`, `PostToolUse` and `UserPromptSubmit` events; `sessionStart` and `postToolUse` inject the brief through `additional_context`, while `beforeSubmitPrompt` honors only `continue`/`user_message`, so a checkpoint recorded there returns an explicit allow and cannot inject its brief. A failed Cursor hook stays silent on stdout (Cursor blocks on output that does not match a hook's schema); the stderr warning is its visible channel.

Wake-up is installed by `coopagents.space_wake` (`install --tool cursor --scope project|user --profile <path>`; an explicit `--profile` is required because Cursor has no native bridge registration to discover). A `sessionStart` hook only baselines the current items — Cursor runs it fire-and-forget — and a `stop` hook checks once when a turn ends and returns `followup_message` with the fixed counts-only template when items are pending; Cursor's default `loop_limit` of 5 follow-ups per script caps the loop. With standby enabled (`space_wake standby on`), the stop hook keeps the session waiting up to the installed timeout budget. Install and disable preserve the file's `version` and unrelated hooks, and never delete user configuration.

Hook installation is implemented and tested (payload mapping, config merge, idempotence, subprocess execution of the generated command). Whether a real Cursor session runs the hooks, injects context and wakes is unverified: live acceptance needs a real Cursor session with a model backend.

## Verification

- Five adapter capability reports and configuration contracts pass focused tests.
- ZCode wake hooks install to user-scope config and pass merge, idempotence and subprocess tests; a ZCode checkpoint-hook fragment is generated in the same events shape and coexists with the wake hooks; live ZCode session acceptance remains unverified.
- Cursor checkpoint and wake hooks pass payload-mapping, merge, idempotence and subprocess tests; live Cursor session acceptance remains unverified.
- Cursor, OpenCode, Pi and Kimi Code remote config shapes are generated with a placeholder environment reference and no credential value. ZCode's entry carries no header because ZCode config files do not expand templates; its auth step is documented in the plan output.
- Existing authenticated MCP task/message behavior remains covered by the full Python suite; unavailable native CLIs are reported as unverified rather than simulated.
