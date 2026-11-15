# DeepSeek Harness gaps

Checked 2026-11-12 against official sources only (deepseek.com,
api-docs.deepseek.com, deepseek-harness.github.io, github.com/deepseek-ai).
DeepSeek Harness (`dsh`) is in developer preview with breaking changes
expected, has had no security audit (per its SAFETY.md), and must not be
treated as production-ready. The live items below were verified
2026-11-15 against a real `dsh` process; everything still open needs a
live `dsh` installation, a backend key, or both, and none of it is faked
on this VM.

## Verified live 2026-11-15 (dsh 0.2.2-rc.1)

- **MCP row loading.** A real `dsh` process loaded the generated
  `dsh-mcp-client` row from a local-only `--patch` overlay, discovered
  the Coopagents tools as `mcp__coopagents__<tool>`, and called
  `whoami` + `read_team` natively against a local space. The model
  backend was an OpenAI-compatible gateway (route override in the same
  overlay); the default DeepSeek route was not exercised.
- **Header auth.** The client schema accepts a literal `headers`
  mapping carrying the Authorization header in a local-only overlay;
  no env expansion exists for MCP client headers. The generated row
  still carries no header: auth is added by hand in a local overlay,
  never in a shared layer.

## Needs a live dsh session

- **Cordis checkpoint plugin.** Checkpoint-like observation would be a
  TypeScript Cordis plugin on `tools/post-execute` / `tools/result` /
  `agent/turn-stopping`. The extension points are documented, but no
  plugin is written or tested here: it needs the Cordis SDK surface and a
  live session to verify event shapes and injection behavior.
- **Wake-up.** No documented CLI command wakes a running idle Web/Desktop
  session from outside, and no Stop-hook/stdout wake contract exists.
  In-process `Agent.followup()` / `agent.inject()` are explicitly not
  wake-up ("an idle agent stays idle"). Programmatic driving would go
  through the ACP profile or the Python SDK, both unverified here.
- **ACP profile / Python SDK.** The `acp` profile and
  `deepseek-harness-sdk` (`dsh --profile sdk-minimal`) are documented
  programmatic surfaces, but no client is implemented or tested here;
  SDK homes never read `~/.dsh`, and `sdk-minimal` omits most tools.

## Undocumented in the official sources checked

- Current `dsh` version number / stable release (version 0.2.2-rc.1 was
  observed live 2026-11-15; do not quote a version without re-checking
  the releases page).
- Node.js version requirement for `npx @deepseek-ai/dsh` (docs say only
  "Install Node.js").
- Desktop app OS/arch list and download URLs.
- No `dsh doctor` / health-check command; doctor checks are composed from
  `dsh` presence, `$DSH_HOME`, and patch-layer text scans.
- No project-level MCP config or per-project patch discovery; config is
  profile/home-level plus `--patch` overlays.
- No official guidance on multiple `dsh` profiles/machines against one
  Coopagents space, or multi-agent coordination beyond DSH's own Agent
  Teams/subagents.

## Provider side (for other harnesses)

Official DeepSeek integration guides exist for Claude Code, Codex,
OpenCode, Pi and others, but none for Cursor, Windsurf, ZCode or Kimi
Code. Generic OpenAI/Anthropic compatibility means those tools can be
pointed at DeepSeek by configuration, but any such setup is a Coopagents
recipe, not DeepSeek's, and is untested here. Current model names are
`deepseek-flash` and `deepseek-v4-pro`; `deepseek-chat` /
`deepseek-reasoner` do not appear in the current quickstart/pricing pages
and must not be used in new config. No official DeepSeek MCP server or IDE
extension was found.
