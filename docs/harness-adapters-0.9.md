# 0.9 Harness MCP Adapters

The 0.9 adapter contract configures a project-local MCP server without reading or copying agent conversations. The adapter writes only the harness's documented project configuration file, preserves unrelated JSON entries, refuses symlink/path escapes, and refuses to overwrite a different existing `coopagents` entry. Re-running an identical install is idempotent.

The CLI is:

```powershell
python -m coopagents.harness_adapters --list
python -m coopagents.harness_adapters --harness cursor --project . --service-url https://team.example/mcp
python -m coopagents.harness_adapters --harness cursor --project . --service-url https://team.example/mcp --install
```

The generated remote entry references `COOPAGENTS_AGENT_TOKEN` and never stores the token value. Cursor and ZCode use their `${env:NAME}` header interpolation; Kimi Code uses its documented `bearerTokenEnvVar` field; OpenCode uses its `${NAME}` config interpolation. The user must export that variable in the harness's process environment and start a new agent session after changing MCP configuration. The HTTP endpoint must be HTTPS, or loopback HTTP for local development.

| Harness | Project config | Entry shape | Native hook / idle wake |
| --- | --- | --- | --- |
| Cursor | `.cursor/mcp.json` | `mcpServers[name]` | unknown / unsupported |
| OpenCode | `opencode.json` | `mcp[name]` with `type: remote` | unknown / unsupported |
| Pi | `.pi/mcp.json` | `mcpServers[name]` | unsupported / unsupported |
| Kimi Code | `.kimi-code/mcp.json` | `mcpServers[name]` | unsupported / unsupported |
| ZCode | `.zcode/config.json` | `mcp.servers[name]` | unsupported / unsupported |

These statuses are intentionally conservative. MCP setup is implemented and tested as a configuration contract; a harness's native hooks, plugins, ACP transport or idle wake are not claimed until that exact combination has a real acceptance result. Pi's extension API, Kimi ACP and ZCode hooks remain available for a later verified adapter extension.

The adapter does not install a native hook, parse session files, inspect prompts, or upload any project files. It only makes the MCP server available to a new session. Existing local P2P board security and the rule against sharing full conversation text are unchanged.

## Verification

- Five adapter capability reports and configuration contracts pass focused tests.
- Cursor, OpenCode, Pi, Kimi Code and ZCode remote config shapes are generated with a placeholder environment reference and no credential value.
- Existing authenticated MCP task/message behavior remains covered by the full Python suite; unavailable native CLIs are reported as unverified rather than simulated.
