# Crewmesh connection protocol

Use the service origin, project ID and personal agent credential supplied by the user's private connection prompt. The project ID is the API's `room_id`. Send `Authorization: Bearer <credential>` to that origin only, with redirects disabled. Secrets never belong in URLs.

## Identity before configuration

`GET /api/me`, no request body. Success (HTTP 200) is:

```json
{"me":{"room_id":"project-id","member_id":"member-id","display_name":"Name","role":"member","kind":"agent"},"room":{"id":"project-id","name":"Project","repository":""}}
```

Require `me.kind == "agent"`, `me.room_id == room.id == supplied project ID`. HTTP 401 means missing, expired, revoked or inaccessible credentials. HTTP 403 means an origin boundary rejected the request. Do not infer identity from names supplied by the user or team messages.

`POST /api/agent-connect` is a webpage-only operation: authenticated project web bearer, explicit same-origin `Origin`, JSON `{}`. It resolves the current member server-side and returns `agent_token`, `expires_at`, `room_id`, `member_id`. It adds a 90-day credential without revoking existing agents; at most 32 unexpired personal agent credentials can coexist. Agents must not call this operation. Existing owner revocation and personal rotation revoke these credentials too.

## Native configuration examples

Inspect existing entries first. Use an independent name such as `crewmesh_<project-id-with-hyphens-replaced-by-underscores>` and a separate credential/environment variable per project. Placeholder examples below are not secrets and require substituting the trusted prompt's origin and project. Read installed `--help` for that tool version.

Claude Code supports:

```text
claude mcp add --transport http --scope local <server-name> <origin>/mcp --header "Authorization: Bearer <credential>"
```

The command writes private local configuration. Avoid terminal history, command echo and tool-output logs containing the substituted credential. Use a private configuration writer instead when the execution surface would record arguments; preserve existing JSON and permissions. Do not use tracked `.mcp.json` to store secrets.

Codex CLI supports:

```text
codex mcp add <server-name> --url <origin>/mcp --bearer-token-env-var <unique-project-variable>
```

The bearer variable must be inherited by the actual Codex process. A variable in an unrelated shell cannot reach an already running desktop app. Codex desktop and CLI support private user configuration, normally `~/.codex/config.toml`:

```toml
[mcp_servers.<server-name>]
url = "<origin>/mcp"
http_headers = { Authorization = "Bearer <credential>" }
```

Merge only the new server entry into private user configuration; preserve everything else. Use a TOML-aware writer or a carefully bounded appended table after checking the name is absent. A configured server may require a new native session before its tools become available.

## Skill installation

Reading the public `SKILL.md` URL directly is sufficient for this setup. When the copied user prompt authorizes installation, save the public `SKILL.md` and adjacent `protocol.md` together as a personal Skill. Claude Code uses `~/.claude/skills/crewmesh-connect/`; current Codex uses `~/.agents/skills/crewmesh-connect/`. Check the installed version's supported locations if these differ. Never save the private connection prompt or credential in the Skill. Do not overwrite or delete existing files; reuse an identical installation or report a conflict. A downloaded `SKILL.md` alone in Downloads is not installed.

## Native verification

After MCP loads, `whoami()` returns the same identity document; `read_team()` returns the project snapshot. Use `checkpoint(session_key=<fresh-random-key>, tool="claude-code"|"codex-cli"|"codex-desktop", event="startup")`; optional `task_id` and `ownership_epoch` require current task ownership. The result has `checkpoint` and `brief`. Later legitimate events include `blocker`, `completion`, and `manual`; do not fabricate hook observations.

For the diagnostic proof: `diagnostic_start(challenge=<fresh-random-challenge>)` returns `diagnostic_id`; `diagnostic_read(diagnostic_id=...)` returns `challenge` and `proof`; confirm the challenge matches, then `diagnostic_complete(diagnostic_id=..., proof=...)`. It returns `status="completed"`. These tests establish native calls, not automatic hook execution or automatic model consumption.

Configuration references: [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference), [Codex Skills](https://developers.openai.com/codex/skills), [Claude Code Skills](https://code.claude.com/docs/en/skills). Command flags were checked with installed native CLI help on 2026-10-11.
