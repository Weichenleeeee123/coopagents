# Space bridge protocol and execution

Use the absolute isolated Python path as `<python>`. None of these commands includes a credential. Helpers emit only safe status/identity/path summaries; the stdio bridge emits MCP exclusively. Private invitation and profile files have schema version 1. Preserve all historical state files.

## Runtime commands

```text
<python> -m coopagents.space_runtime create --name <space-name> --owner <display-name> --network p2p [--connect claude|codex [--wake]]
<python> -m coopagents.space_runtime create --name <space-name> --owner <display-name> --network quick --cloudflared <verified-executable>
<python> -m coopagents.space_runtime create --name <space-name> --owner <display-name> --network local
<python> -m coopagents.space_runtime create --name <space-name> --owner <display-name> --network external --public-url https://<trusted-host>
<python> -m coopagents.space_runtime status --profile <private-dir>/profile.json
<python> -m coopagents.space_runtime invite --profile <private-dir>/profile.json [--message en|zh] [--hours 1-72]
<python> -m coopagents.space_runtime join --invitation-file <saved-message-or-private-invite> --name <display-name> [--connect claude|codex [--wake]]
<python> -m coopagents.space_runtime join --invitation-code-stdin --name <display-name> [--connect claude|codex]   # piped text; fails after 15 s without input
<python> -m coopagents.space_runtime start --profile <owner-profile>
<python> -m coopagents.space_runtime reconnect --profile <member-profile> --origin https://<new-trusted-host> --room-id <expected-room>
<python> -m coopagents.space_runtime stop --profile <owner-profile>
<python> -m coopagents.space_runtime board --profile <owner-profile>
<python> -m coopagents.space_runtime connect --tool claude|codex --profile <absolute-private-profile> [--name <server>] [--cli <path>] [--wake [--project-dir <repo>]]
```

`create` and `join` take an optional `--state-dir`; without it they make a new private folder under `~/.coopagents/spaces` (or `$COOPAGENTS_HOME/spaces`). With `--connect`, they then run `connect` for the new profile; if only that step fails, the space or membership is kept and the output has `connect_error` and a `retry` command. Failures print a specific reason; remote response text is never repeated.

The invite helper saves a protected descriptor and normally emits its path. With `--message`, it also emits `message`: a shareable text with a short pitch, the project and Skill links, a prompt for the invitee's agent and the one-time compact code `coopagents-invite-2.<Crockford-base32>` (the same descriptor as the file), plus `local_only` when the space only accepts agents on the host computer. The compact code is case-insensitive, tolerates spaces, line breaks and dashes, and includes a checksum that detects copying errors; older `coopagents-invite-1.<base64url>` and `crewmesh-invite-1.<base64url>` codes remain accepted. The message is a bearer secret like `--share` output. `--hours` sets the lifetime (default 1, at most 72). `join --invitation-code-stdin` reads up to 64 KiB from standard input, accepts the code alone or the whole message, and reports a fixed secret-free reason when the code is missing, repeated with different values, truncated or malformed. Never repair or edit a code by hand; save the whole message again or ask for it to be pasted again. Use `--share` only if sharing was requested and the output channel is private; it can emit the bearer invitation. Never run it in a captured/public terminal transcript. Revoke a leaked or unused invite with `revoke-invitation --profile <owner-profile> --invitation-file <private-invite>`; revoke a member with `revoke-member --profile <owner-profile> --member-id <member>` only when the actual user requests it. Database and identity survive start/stop. In p2p mode the endpoint key also survives, so the origin and invitations stay valid; the quick-tunnel origin may change.

## Hosted profile and identity

The private JSON object contains `schema_version: 1`, `origin`, `room_id`, `member_id`, `agent_token`. Local joins also receive `web_token`; only an owner has `control_origin` and `control_token`. A p2p member profile adds `p2p: {"endpoint_id": <64 hex>}` and uses the host's loopback origin, which its link serves on the member's computer. Do not print this object. Write it using `coopagents.spaces.private_write`; pass secrets from the private authorized source directly into that function, not a shell one-liner containing the secret. Before configuration, `GET <origin>/api/me` with `Authorization: Bearer <agent_token>` and matching Origin must return `me.room_id`, `me.member_id` and `me.kind == "agent"`. HTTP credential requests reject redirects. Remote origins require HTTPS; local HTTP requires explicit loopback and port.

## Native configurations

`space_runtime connect` performs this configuration and verification; agents use it instead of the steps below. It names the server `coopagents_<first 8 hex of the room id>` unless `--name` is given, runs the commands shown here, then reads the entry back (`claude mcp get <name>`, `codex mcp get <name> --json`) and compares the Python path and arguments. Claude Code reads user MCP servers from `~/.claude.json`, not from any other JSON file. For reference, the commands it runs:

```text
claude mcp add --transport stdio --scope user <unique-space-name> -- <absolute-python> -m coopagents.space_bridge --profile <absolute-private-profile>
codex mcp add <unique-space-name> -- <absolute-python> -m coopagents.space_bridge --profile <absolute-private-profile>
```

Claude's user JSON entry is under `mcpServers`, with `type: "stdio"`, `command` and `args`. Codex's private TOML entry is under `mcp_servers.<name>` with `command` and `args`. Prefer native add commands after conflict checks; if manual merge is necessary, parse and preserve the complete existing configuration and retain a private backup. Never append duplicate TOML sections or replace the whole file with a single server. Personal skills belong in `~/.claude/skills/coopagents-space/` or `~/.codex/skills/coopagents-space/` (respect configured skill roots). Copy SKILL.md, protocol.md and the scripts together only if absent; do not overwrite a different installed skill.

The bridge proxies `/mcp` using the official MCP SDK. Remote tool names, descriptions and schemas are forwarded verbatim. It adds only `read_changes`, with optional integer `after_id` (default 0) and `limit` (1–200, default 100), and `install_wake`, with optional `tool` (`claude` or `codex`, default: detected from the MCP client name) and optional `project_dir` (default: `CLAUDE_PROJECT_DIR` for Claude Code, otherwise the bridge's working folder, which both agents set to the session's folder), which installs this profile's wake hooks for that repository and returns the `space_wake install` result plus a `next` step. Remote human operations are not added to MCP.

## Event replay and failures

The background WebSocket connects to `/api/events`, supplies `{"token":<agent_token>,"after_id":<durable-cursor>}` as its first frame, and verifies the server's protocol-1 `ready.room_id`. No business messages or acknowledgments are sent. The local private `bridge-events.sqlite3` retains at most 400 invalidations and the received cursor. Credentials are not stored in the cache. Reconnection starts at the durable cursor with exponential backoff from 0.25 to 15 seconds and rereads the profile. The cache is shared by bridges using that personal profile; use separate profiles for separate members.

`read_changes` reauthenticates before returning cached data. Its result includes `events`, `cursor`, `high_water`, `has_more`, `reset`, `room_id`, `transport_status` and `model_read_acknowledged: false`. Status describes the transport only. Cache expiry, server retention expiry or a future cursor sets reset and returns a recovery cursor. Read current business state before advancing to that cursor. A disconnected bridge cannot prove completeness; query the business tools when working while offline. HTTP/MCP authentication failure returns a tool error or an empty discovery list, never stale authorized tools or a completion claim. Bridge CLI errors suppress credential-bearing response bodies and tracebacks.

## Wake-up hooks

```text
<python> -m coopagents.space_wake preview --tool claude|codex --profile <personal-profile> --project-dir <repo>
<python> -m coopagents.space_wake install --tool claude|codex --profile <personal-profile> --project-dir <repo> [--scope user] [--standby-limit 900]
<python> -m coopagents.space_wake disable --tool claude|codex --project-dir <repo> [--scope user]
<python> -m coopagents.space_wake standby on|off --profile <personal-profile> [--seconds 900]
<python> -m coopagents.space_wake status --profile <personal-profile>
```

Project scope writes `.claude/settings.local.json` (Claude) or `.codex/hooks.json` (Codex); user scope writes `~/.claude/settings.json` or `~/.codex/hooks.json`. Hook commands contain only the Python path, the module and the profile path, using forward slashes and Windows short names so Git Bash, cmd and PowerShell all parse them.

The watcher calls the agent operation `wake_digest`, which returns kinds and ids of items needing the member — unread requests delivered to it, teammates' replies to its unresolved requests, pending handoffs to it — without bodies or receipts. It rechecks when the bridge's `bridge-events.sqlite3` cursor moves, and otherwise every 20 seconds. The private `wake-state.sqlite3` next to the profile records which items already woke someone (so no item wakes twice, even across sessions), the wake history used for rate limits, the newest watcher per session, and the Codex standby setting. Claude watchers exit by themselves 120 seconds before the 3600-second hook timeout and re-arm on the next Stop. Codex standby never exceeds the installed hook budget. Authorization denial, network faults and malformed input end quietly without waking.

## Explicit human helper

This helper is a separate process invoked only for a real user instruction. A payload file is protected schema-version-1 JSON whose remaining fields are the exact shared operation payload. It uses the same `/api/operations/<operation>` endpoint, schema validation, web-kind identity, room role checks and transaction behavior as the web UI. The CLI's arguments contain paths and operation name only:

```text
<python> -m coopagents.space_bridge --profile <personal-profile> --human-operation create_task --payload-file <private-payload>
```

Supported names are listed by `--help`; examples include `create_task`, `decision`, `assign`, `accept_handoff`, `reject_handoff`, `force_handoff`, `cancel_task`, `reopen_task`, `bind_repository`, `resolve_request`, `revoke_member`. Credential rotation and invitation creation use dedicated paths because their responses contain new secrets. Read the repository's `CoordinationService.operations` and the current state for required fields; do not guess revisions or infer approvals. The helper emits only an applied status after success. Verify the resulting state separately through ordinary reads.
