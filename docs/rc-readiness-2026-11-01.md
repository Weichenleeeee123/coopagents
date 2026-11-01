# 1.0 RC readiness — 2026-11-01

## Native Codex discovery

Fixed in `2d38114`. Codex 0.166.0-alpha.5.1 can omit an optional MCP server from the first turn while discovery is pending. A longer server timeout alone does not make the turn wait. A controlled delayed-discovery experiment failed with defaults, failed with only an increased timeout, and passed actual `whoami` / `read_team` calls when the connection was required as well.

The connection helper now sets `required = true` and a minimum 120-second startup budget for its verified native entry. It preserves larger budgets, unrelated TOML values and formatting, retains a protected original backup, and refuses unsupported layouts or detected concurrent edits. Doctor reports legacy settings without modifying them. Existing users rerun connect and open a new native session. A failed required connection blocks startup until corrected or disabled in native settings.

Three consecutive fresh native sessions passed actual identity and team calls without per-invocation discovery overrides. Seven focused regressions cover preservation, idempotence, larger budgets, quoted tables, unsupported/foreign configuration, read-only doctor and concurrent user edits. Full core regression: 677 tests, one skipped. Integration regressions subsequently reached 56 passing tests. Release CI at `b742298` passed Python 3.11/3.13, 678 core tests and 56 experiments per version (three platform skips), Node checks, package builds, and container/TLS smoke. Independent review found no blocking correctness or security defect.

## Versioned RC1 artifacts

Final RC1 assets were rebuilt from commit `b742298d066022209c181a9901fcc71941a47b35` on D:. Wheel SHA-256: `6f1a62a0b06ca492e44b7128ae901202ea83c06cebb3b55ef1731179c42d8a01`. Sdist SHA-256: `617f62066a338fcb3d80eba6b73b69ed37a431d86d64685aaac2180de3a7fb34`.

A clean D: virtual environment installed the exact wheel and passed version/import-path and `space_runtime --help` checks. A first install attempt failed because pip tried to use the full C: temp volume; its environment/log were retained, and a new install with temporary storage on D: passed.

The exact RC1 wheel passed nine migration checks from a fresh synthetic space created using published PyPI `coopagents[space]==0.9.0`: owner/member profiles and P2P key unchanged; both old identities accepted; task owner/epoch and request/reply retained; asset content retained; old claimed session continued without rejoin; candidate stdio MCP used the existing member identity; baseline backup hashes unchanged. This proves protocol/data migration, not native-model use.

## Native cold start

The exact pre-versioned development wheel (SHA-256 `9b1fdbc381b7a0a355c7059d0061ec774459ab1d147fc8458966d51a48100679`) completed all nine native sessions on Windows with two separately installed environments. Claude Code 2.1.282 and Codex 0.166.0-alpha.5.1 created/joined, verified fresh identities, exchanged exact contents from separate local files in both directions, and consumed the replies. Independent backend records confirmed both exchanges. This result predates the version bump and final harness prompt change; it does not substitute for the exact RC1 wheel.

The versioned RC1 wheel passed creation, fresh host identity, invitation, join, fresh member identity and the first file-derived request/reply/consumption. A later RC1 run completed the reverse request but stopped before its reply: the configured third-party provider reported balance `0.068916`, below that request's estimate of `0.075094`. The final two sessions did not run, so the exact RC1 wheel lacks a complete native-model pass. Earlier runs also exposed an unavailable Claude model alias and a Claude sandbox refusal caused by unapproved `pip`/`git` probes; the harness now states its prechecked environment and exact command limits, without weakening sandbox permissions. The current-user settings were only copied into private homes. No official-model fallback was used.

## Packaged lifecycle and product limits

Packaged Codex creation and a fresh session passed. The native host lifecycle run passed nine checks: accidental host loss and recovery, independent live doctor, unchanged profile, explicit stop without resurrection, explicit resume, and identity retention. Keep an owner native session open during collaboration; reopening it restores the managed host after it exits.

This work does not establish macOS support, two independent users, two devices behind separate home/mobile NAT networks, every harness, or stable 1.0 readiness. The GitHub App evidence covers the dedicated read-only test app and repository in the P0 record, not organization approval or production limits.

All raw native records, credentials, package reports, databases, backups and failed runs remain under ignored private directories. GitHub/PyPI RC publication remains pending the full exact-RC1 native exchange and a GPG signing key for the signed tag required by the release plan. Do not publish or claim full RC acceptance until those items pass.
