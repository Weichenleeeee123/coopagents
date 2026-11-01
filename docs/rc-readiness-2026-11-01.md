# 1.0 RC readiness — 2026-11-01

## Native Codex discovery

Fixed in `2d38114`. Codex 0.166.0-alpha.5.1 can omit an optional MCP server from the first turn while discovery is still pending. A longer server timeout alone does not make the turn wait. A controlled delayed-discovery experiment failed with defaults, failed with only an increased timeout, and passed actual `whoami` / `read_team` calls when the connection was required as well.

The connection helper now sets `required = true` and a minimum 120-second startup budget for its verified native entry. It preserves larger budgets, unrelated TOML values and formatting, retains a protected original backup, and refuses unsupported layouts or detected concurrent edits. Doctor reports legacy settings without modifying them. Existing users rerun connect and open a new native session. A failed required connection blocks startup until corrected or disabled in native settings.

Three consecutive fresh native sessions passed actual identity and team calls without per-invocation discovery overrides. Seven focused regressions cover preservation, idempotence, larger budgets, quoted tables, unsupported/foreign configuration, read-only doctor and concurrent user edits. Full core regression: 677 tests, one skipped; the subsequently added seventh focused test also passes. Integration experiment regression: 54 tests pass. Independent review found no blocking correctness or security defect.

## Installed-distribution checks

The preparation wheel is an unpublished development artifact with version 0.9.0 and SHA-256 `9b1fdbc381b7a0a355c7059d0061ec774459ab1d147fc8458966d51a48100679`. It is distinct from the published 0.9 baseline. Candidate and peer use separate clean virtual environments; acceptance verifies both imports are inside their environments and installed archive hashes match the exact wheel. The bundled Skill comes from the installed package.

Packaged native Codex creation and a fresh session passed. The packaged lifecycle run passed all nine checks: unintentional host loss, native recovery and independent live doctor, unchanged profile, explicit stop without resurrection, explicit resume and independent live doctor, and retained identity. Native owner sessions must stay open during collaboration; reopening recovers the host after all owner sessions close.

Complete bidirectional cold-start acceptance is pending. The first Claude-owner run failed before any tool call because its `sonnet` alias resolved to an unavailable upstream model (`claude-sonnet-5-5`, HTTP 503). A separate exact `claude-sonnet-5` preflight succeeded. A new run using that isolated model setting passed create, fresh owner identity and Codex join; Codex then loaded and successfully called `whoami`, `read_team` and `send_request`, but its old custom provider returned HTTP 403 insufficient balance before the model completed its turn. This run remains failed. The user changed their third-party provider; subsequent runs copy current settings afresh. Real user settings are unchanged, and no official-provider fallback is used. Failed runs are retained and do not count as a pass.

## Published 0.9 upgrade

An isolated environment installed `coopagents[space]==0.9.0` from official PyPI. The retained pip report identifies the official archive and SHA-256. That version created synthetic owner/peer identities, a P2P host, claimed task/session/progress, request/reply and explicit asset. It stopped before a retained backup and hash manifest were made.

The separately installed candidate passed all nine upgrade checks: unchanged profiles/P2P host key, both existing identities accepted, task ownership/epoch retained, original request/reply retained, original asset content retained, existing claimed session continues without rejoin, actual candidate stdio MCP identity/team calls, and unchanged baseline backup hashes. Stdio checks here are protocol evidence; full native-model evidence is reported separately.

## Scope

All raw native records, credentials, package reports, databases, backups and failed runs remain under ignored private directories. No acceptance bypasses native sandbox or substitutes a runner-started host for native cold-start recovery. This work does not establish macOS support, two independent human users, both endpoints behind home/mobile NAT, every harness, or stable 1.0 readiness. RC entry remains conditional on the complete installed-wheel exchange and the release checks.

Production fix and documentation CI passed at `dfe4f65`; the acceptance harness commit `4b6bf43` also passed [release verification](https://github.com/Weichenleeeee123/coopagents/actions/runs/41272862665): Python 3.11/3.13 each ran 678 core tests (three platform-specific skips) and 54 experiment regressions, plus Node checks, distribution builds, and container/TLS smoke. This verifies that commit, not a future versioned RC artifact.
