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
- **Provider recipe (OpenAI-compatible gateway).** The fastest
  verified `llm-pi-ai` route override in a local-only `--patch`
  overlay uses `api: openai-completions` with
  `compat: {thinkingFormat: deepseek}`, plus an `agent-default-model`
  row pointing at the same provider and model. Sketch (base URL and
  key by env reference, as already configured; no values here):

  ```yaml
  - id: llm-pi-ai
    config:
      providers:
        mota:
          apiKeyEnv: MOTA_API_KEY
          api: openai-completions
          baseURL: <gateway base URL>
          compat:
            thinkingFormat: deepseek
          models:
            - id: deepseekv41flash-auto-b
              contextWindow: 131072
              maxTokens: 2048
  - id: agent-default-model
    config:
      provider: mota
      model: deepseekv41flash-auto-b
  ```

  A same-task benchmark 2026-11-15 (dsh 0.2.2-rc.1 headless,
  maxTokens 2048, no MCP row) ran 13s/15s with the compat setting vs
  22s/30s without it; two runs per path is a small sample, but the
  compat setting is also the documented-correct reasoning format for
  DeepSeek-style endpoints, so it wins on correctness as well as
  observed speed. Combine with the MCP row above for Coopagents use.
  The same benchmark found a second gateway's model slower with high
  variance (77s/25s), and openai-next returning 401 Invalid token on
  all three endpoints that day — dsh fails fast on auth errors with
  no retry, so a dead relay aborts the run in seconds.

## Needs a live dsh session

- **Cordis checkpoint plugin — implemented and verified live
  2026-11-15.** `python -m coopagents.deepseek_harness
  --export-plugin <file>` writes an ESM Cordis plugin
  (`coopagents-checkpoint`) that posts SessionStart on
  `agent/created`, UserPromptSubmit on `agent/inbox/inserted`, and
  PostToolUse on `tools/result` (throttled to one POST per 30s per
  session), authenticates with GET /api/me on every event, and
  injects the brief with `agent.inject(createUserMessage(...))`.
  The connection comes from the dsh process environment; the plugin
  carries no credential and fails open. Load it with a patch row
  naming the plugin file beside the patch layer (relative paths are
  anchored beside the patch file). Live verification (dsh 0.2.2-rc.1
  headless, stub service, scratch home): all three events post with
  the documented shapes and the injected brief reaches the model.
  One trap found live: injected context also fires
  `agent/inbox/inserted`, so the inbox handler only fires for
  genuine user messages (`message.source.kind === 'user'`) —
  without that guard the plugin re-injects forever.
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
