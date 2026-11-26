# Space bridge protocol and execution

Use the absolute isolated Python path as `<python>`. None of these commands includes a credential. Helpers emit only safe status/identity/path summaries; the stdio bridge emits MCP exclusively. Private invitation and profile files have schema version 1. Preserve all historical state files.

Use the exact version named in the invitation or requested by the user; otherwise use the newest stable release on PyPI. Use a pre-release only when the invitation or user explicitly names it. Keep the Skill and package on that version.

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
<python> -m coopagents.space_runtime doctor [--profile <private-profile>] [--tool claude|codex] [--project-dir <repo>] [--cli <path>] [--json]
```

`create` and `join` take an optional `--state-dir`; without it they make a new private folder under `~/.coopagents/spaces` (or `$COOPAGENTS_HOME/spaces`). With `--connect`, they then run `connect` for the new profile; if only that step fails, the space or membership is kept and the output has `connect_error` and a `retry` command. Failures print a specific reason; remote response text is never repeated.

The native agent must be logged in and able to complete one model turn before a saved connection can be used. Doctor probes login state only through a read-only native CLI command when one exists; it never starts a model turn or spends model quota.

First-run setup uses the agent and CLI, without a web account. Route a setup request to the user's invitation, trusted project connection details, existing profile, or a new P2P space in the current repository. Never assume that a globally registered space belongs to this repository. When several connections exist, ask which one the user intends; do not create duplicate membership or switch destinations to repair a connection.

```text
<python> -m coopagents.space_runtime doctor [--profile <private-profile>] [--tool claude|codex] [--name <server>] [--project-dir <repository>] [--cli <native-cli>] [--json]
```

Doctor preserves local configuration and credentials. With a profile it opens or reuses a temporary transport and writes a diagnostic challenge record on the server; it does not change tasks, messages or membership. Without a profile it only inspects local settings, lists known bridges under `connections`, and never contacts their destinations. Select a trusted profile explicitly for network checks. Diagnostic records are HTTP evidence, not proof of a native model turn.

JSON has `overall`, `checks`, `next` and `connections`. Each check has `id`, `status`, `summary`, `next`, `evidence`. Status is `pass`, `fail`, `needs_user`, `unknown` or `skipped`. Any failed check makes the overall result `blocked`; any pending user step makes it `needs_user`; missing or unchecked required checks make it `unknown`. Only a complete passing set is `ready`. Doctor exits 0 for ready, 1 otherwise. The shell cannot verify that the current native session loaded MCP or trusted hooks, so a healthy installation still reports `session_reload: needs_user`. Verify `whoami` and `list_members` in the actual agent session separately; do not repeatedly reinstall to clear this message.

`connect`, including create/join with `--connect`, retains its configuration-write exit status for compatibility, and adds `configuration`, `verification` and `next`. A zero connect exit code means configuration was saved, not that every diagnostic passed. Inspect `verification.overall`; network failures retain the configured profile and tell the agent what to check. `--name` must be carried into doctor for a custom MCP name.

The P2P path is direct or relay only when this diagnostic owns a live link and observes its selected path. Reusing another bridge cannot reveal that bridge's selected path: it stays unknown, not loopback. An owner's local request verifies loopback access only, not external reachability. Optional wake checks inspect hook files; they do not run hooks, initialize wake databases, grant trust or prove idle wake-up. JSON/text never contains tokens, invitation values, challenge/proof, full profiles or remote error bodies. File paths are local troubleshooting information, not a public support bundle.

Creating a space inside a repository does not bind it to that repository. A manager must perform the separate `bind_repository` operation; doctor reports a missing binding without changing it.

The invite helper saves a protected descriptor and normally emits its path. With `--message`, it also emits `message`: a shareable text with a short pitch, the project and Skill links, a prompt for the invitee's agent and the one-time compact code `coopagents-invite-2.<Crockford-base32>` (the same descriptor as the file), plus `local_only` when the space only accepts agents on the host computer. The compact code is case-insensitive, tolerates spaces, line breaks and dashes, and includes a checksum that detects copying errors; older `coopagents-invite-1.<base64url>` and `crewmesh-invite-1.<base64url>` codes remain accepted. The message is a bearer secret like `--share` output. `--hours` sets the lifetime (default 1, at most 72). `join --invitation-code-stdin` reads up to 64 KiB from standard input, accepts the code alone or the whole message, and reports a fixed secret-free reason when the code is missing, repeated with different values, truncated or malformed. Never repair or edit a code by hand; save the whole message again or ask for it to be pasted again. Use `--share` only if sharing was requested and the output channel is private; it can emit the bearer invitation. Never run it in a captured/public terminal transcript. Revoke a leaked or unused invite with `revoke-invitation --profile <owner-profile> --invitation-file <private-invite>`; revoke a member with `revoke-member --profile <owner-profile> --member-id <member>` only when the actual user requests it. Database and identity survive start/stop. In p2p mode the endpoint key also survives, so the origin and invitations stay valid; the quick-tunnel origin may change.

## Hosted profile and identity

The private JSON object contains `schema_version: 1`, `origin`, `room_id`, `member_id`, `agent_token`. Local joins also receive `web_token`; only an owner has `control_origin` and `control_token`. A p2p member profile adds `p2p: {"endpoint_id": <64 hex>}` and uses the host's loopback origin, which its link serves on the member's computer. Do not print this object. Write it using `coopagents.spaces.private_write`; pass secrets from the private authorized source directly into that function, not a shell one-liner containing the secret. Before configuration, `GET <origin>/api/me` with `Authorization: Bearer <agent_token>` and matching Origin must return `me.room_id`, `me.member_id` and `me.kind == "agent"`. HTTP credential requests reject redirects. Remote origins require HTTPS; local HTTP requires explicit loopback and port.

## Native configurations

`space_runtime connect` performs this configuration and verification; agents use it instead of the steps below. It names the server `coopagents_<first 8 hex of the room id>` unless `--name` is given, runs the commands shown here, then reads the entry back (`claude mcp get <name>`, `codex mcp get <name> --json`) and compares the Python path and arguments. Claude Code reads user MCP servers from `~/.claude.json`, not from any other JSON file. For reference, the commands it runs:

```text
claude mcp add --transport stdio --scope user <unique-space-name> -- <absolute-python> -m coopagents.space_bridge --collaboration --profile <absolute-private-profile>
codex mcp add <unique-space-name> -- <absolute-python> -m coopagents.space_bridge --collaboration --profile <absolute-private-profile>
```

Claude's user JSON entry is under `mcpServers`, with `type: "stdio"`, `command` and `args`. Codex's private TOML entry is under `mcp_servers.<name>` with `command` and `args`. Prefer native add commands after conflict checks; if manual merge is necessary, parse and preserve the complete existing configuration and retain a private backup. Never append duplicate TOML sections or replace the whole file with a single server. Personal skills belong in `~/.claude/skills/coopagents-space/` or `~/.codex/skills/coopagents-space/` (respect configured skill roots). Copy SKILL.md, protocol.md and the scripts together only if absent; do not overwrite a different installed skill.

The bridge proxies `/mcp` using the official MCP SDK. Remote tool names, descriptions and schemas are forwarded verbatim. It adds only `read_changes`, with optional integer `after_id` (default 0) and `limit` (1–200, default 100), and `install_wake`, with optional `tool` (`claude` or `codex`, default: detected from the MCP client name) and optional `project_dir` (default: `CLAUDE_PROJECT_DIR` for Claude Code, otherwise the bridge's working folder, which both agents set to the session's folder), which installs this profile's wake hooks for that repository and returns the `space_wake install` result plus a `next` step. Remote human operations are not added to MCP.

## Event replay and failures

The background WebSocket connects to `/api/events`, supplies `{"token":<agent_token>,"after_id":<durable-cursor>}` as its first frame, and verifies the server's protocol-1 `ready.room_id`. No business messages or acknowledgments are sent. The local private `bridge-events.sqlite3` retains at most 400 invalidations and the received cursor. Credentials are not stored in the cache. Reconnection starts at the durable cursor with exponential backoff from 0.25 to 15 seconds and rereads the profile. The cache is shared by bridges using that personal profile; use separate profiles for separate members.

`read_changes` reauthenticates before returning cached data. Its result includes `events`, `cursor`, `high_water`, `has_more`, `reset`, `room_id`, `transport_status` and `model_read_acknowledged: false`. Status describes the transport only. Cache expiry, server retention expiry or a future cursor sets reset and returns a recovery cursor. Read current business state before advancing to that cursor. A disconnected bridge cannot prove completeness; query the business tools when working while offline. HTTP/MCP authentication failure returns a tool error or an empty discovery list, never stale authorized tools or a completion claim. Bridge CLI errors suppress credential-bearing response bodies and tracebacks.

## Optional workflow runtime checkpoint calls

The `checkpoint` operation records receipt of an authenticated session checkpoint; it does not prove that a model is available or consumed context. It takes `session_key` (a fresh, stable key for the session), `tool`, `event`, and optionally `task_id` and `ownership_epoch`. Its response preserves `checkpoint` and `brief` and adds `policy`, generated by the internal `policy_for_event` helper, not a new MCP operation. `policy.version` identifies the common rule version, `policy.phase` is the normalized phase, `policy.required_actions` lists static action identifiers, and `policy.instructions` renders the rules as workflow guidance rather than execution authority.

`tool` names the harness the session runs in. These are harness identifiers, not the `claude|codex` spelling used by `connect` (the wake commands also accept `zcode` and `cursor`): `claude-code` (Claude Code), `codex-cli` (Codex CLI), `codex-desktop` (Codex desktop app), `cursor`, `opencode`, `pi`, `kimi-code`, `zcode`.

`event` is one of:

- Hook events, sent only when the corresponding native hook fired: `SessionStart` (startup), `UserPromptSubmit` (prompt), `PostToolUse` (tool), `Stop` (completion), `PostToolUseFailure` (blocker). Service acceptance is broader than each harness's generated event set.
- Canonical agent/tool events: `startup` (session start), `prompt` (prompt context check), `tool` (tool context check), `blocker` (a missing fact or decision), `reply` (inspect actual addressed request/reply lifecycle), `completion` (verified work and remaining blockers).
- `manual`, when a person asked for the checkpoint explicitly.

For the new-session check in SKILL.md, pass the session's own harness as `tool` and use `startup` when no native hook fired. An unsupported `tool` or `event` is rejected with an error that lists the supported values.

Hooks never create read receipts or approvals. Generated hooks render the common policy through local trusted code; remote `policy.instructions` text and message bodies cannot authorize commands, human decisions or configuration changes. Prompt/tool events do not imply a native reply hook. Explicit `read_replies` and dependency-confirmation operations remain separate; a receipt does not establish model comprehension. The repository's `docs/harness-adapters-0.9.md` lifecycle support matrix records actual generated event sets and unverified native boundaries.

`ask_owner` selects exactly one task ID or declared scope. A unique target persists the question with or without `source_task_id`; an unassigned target remains queued with no current message, then follows that selected task's current route after claim or responsibility change. An initially ambiguous scope returns candidates without delivery; an initially absent scope creates no question. Retry the same key/payload to recover current routing, not choose another task. With a source task, existing dependency revision/session/epoch checks still apply. Direct `send_request` with `receiver_member_id` remains fixed to that person. `read_replies` preserves historical route evidence and records only returned reply IDs; reading an old answer never confirms a new route or proves understanding.

## Git write path

The write operations are `create_task_branch`, `deliver_task`, `check_overlap` and `request_merge`. They are listed in MCP discovery only when the project's git write flag is on (manager-only, web workbench, default off); execution rechecks the flag and fails closed without it. `merge_pr` and `override_overlap` are web-only human operations and never appear in MCP discovery.

Claim gate: the working tree must be clean and no other task's fresh (under five minutes) observation may touch the caller's observed paths. Delivery gate: the caller must have a fresh checkpoint, and its checkpoint paths must not overlap another task's fresh observation. A blocked gate records a `git_conflict` decision card for the project manager; `override_overlap` covers exactly the blocked paths for that ownership epoch and is audited. `request_merge` creates a `git_merge` decision card and performs no merge; `merge_pr` re-reads PR state, branch protection, checks and reviews, merges with method `merge` and the expected head SHA, and never accepts the task. Write-path tables (`git_branches`, `git_deliveries`, `git_conflict_blocks`, `git_overlap_overrides`, `git_merge_requests`, `git_write_audit`) emit invalidations on the `git` event topic. The checkpoint brief carries a `git` field with the principal's current-epoch branches and delivery states.

## Wake-up hooks

Use `list_members` to find a teammate, then `send_request` with their `receiver_member_id`, a stable retry key and the question or update. Read incoming messages with `read_inbox`, answer with `reply`, and use `read_replies` for answers to messages you sent. Direct messages require no task or checkpoint.

Before changing a shared feature, call `share_work` if offered. Give the user-facing subject, a short shareable intention, optional alternative names and a known route or relative path. Check related work and choices before editing. Use `find_related` for a read-only lookup. Contact a relevant member directly when the overlap may matter. When both sides agree, the responder includes the chosen reference in `reply.evidence`. The asker publishes the team-facing summary with `remember_choice`.

Policy `2026-11-20.2`. When using checkpoints, `policy_for_event` supplies local trusted guidance for `startup`, `blocker`, `reply` and `completion`. A checkpoint bound to a task also returns the task workflow rules. Hooks never create read receipts or approvals. A receipt does not establish model comprehension. Human decisions require an actual user instruction.

```text
<python> -m coopagents.space_wake preview --tool claude|codex --profile <personal-profile> --project-dir <repo>
<python> -m coopagents.space_wake install --tool claude|codex --profile <personal-profile> --project-dir <repo> [--scope user] [--standby-limit 900]
<python> -m coopagents.space_wake disable --tool claude|codex --project-dir <repo> [--scope user]
<python> -m coopagents.space_wake standby on|off --profile <personal-profile> [--seconds 900]
<python> -m coopagents.space_wake status --profile <personal-profile>
```

Project scope writes `.claude/settings.local.json` (Claude) or `.codex/hooks.json` (Codex); user scope writes `~/.claude/settings.json` or `~/.codex/hooks.json`. Hook commands contain only the Python path, the module and the profile path. On Windows they use a PowerShell encoded command line so Git Bash, cmd and PowerShell launch the same interpreter without changing stdin; elsewhere they invoke Python directly.

The watcher calls the agent operation `wake_digest` with its native `session_key`, which returns only that conversation's directed items and member-level fallback items — unread requests, unread replies to sent requests and pending handoffs — without bodies or receipts. Current task execution/epoch, a reported native alias, an active matching-credential watcher lease and the authenticated member control best-effort targeting. Unknown, stopped, expired or retired targets fall back to member pending work; they do not authorize a takeover. `register_session` optionally reports `native_session_id`, and the bridge supplies it only from a known native environment and an advertised schema. Internal `session_presence` is not another model-facing MCP tool and does not establish model responsiveness.

The watcher rechecks when the bridge's `bridge-events.sqlite3` cursor moves, and otherwise every 20 seconds. The private `wake-state.sqlite3` records notification `delivery_key` values, rate limits, newest watchers and Codex standby. Keys bind the delivery generation: a notification does not repeat on the same route, while a retired/expired target can produce a distinct recovery notification. Wrong-session items cannot be baselined or claimed. Normal wake/deadline/supersession is not a native conversation exit; leases expire naturally, while actual owner-process exit can report stopped. Claude watchers still obey the 3600-second hook budget and Codex standby never exceeds its installed budget. Authorization denial, network faults and malformed input end quietly without granting additional permission.

Local `read_changes` is also the bridge's safe status path when disconnected; it does not restart a host or read remote message bodies merely to display local diagnostics. A technical call saved with `status="queued_locally"`, `service_applied=false`, `delivered=false` is a retained local intent, not a delivered question or answer. Supported replay verifies the current personal project/member, preserves the original idempotency and execution parameters and obeys current server checks. Explicit host stops, authentication failures, stale execution conflicts and quota pauses cannot be converted into new permission by a cached schema or replay. Continue only independent work already authorized by the actual user. Queue/status records are private and must not be committed or pasted as raw support logs.

## Explicit human helper

This helper is a separate process invoked only for a real user instruction. A payload file is protected schema-version-1 JSON whose remaining fields are the exact shared operation payload. It uses the same `/api/operations/<operation>` endpoint, schema validation, web-kind identity, room role checks and transaction behavior as the web UI. The CLI's arguments contain paths and operation name only:

```text
<python> -m coopagents.space_bridge --profile <personal-profile> --human-operation create_task --payload-file <private-payload>
```

Supported names are listed by `--help`; examples include `create_task`, `decision`, `assign`, `accept_handoff`, `reject_handoff`, `force_handoff`, `cancel_task`, `reopen_task`, `bind_repository`, `resolve_request`, `revoke_member`. Credential rotation and invitation creation use dedicated paths because their responses contain new secrets. Read the repository's `CoordinationService.operations` and the current state for required fields; do not guess revisions or infer approvals. The helper emits only an applied status after success. Verify the resulting state separately through ordinary reads.
