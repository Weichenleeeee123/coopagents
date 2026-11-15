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

## Rerun — 2026-11-04

The exact RC1 wheel (SHA-256 `6f1a62a0…8a01`, built from `b742298`) was installed into two separate clean environments on D:. `src` and `pyproject.toml` are unchanged from `b742298` through the harness commits below.

**Claude host: passed.** All nine native sessions and eleven checks passed with harness commit `27e6a95`: create and join over P2P, fresh identities, file-derived request/reply in both directions, consumption by both models, doctor challenge for both members, and clean host shutdown. Models were Claude Code 2.1.316 with `claude-opus-5-5` and Codex 0.166.0-alpha.5.1 with `gpt-6-astra`.

**Model substitution, approved by the maintainer.** The configured `gpt-6.1-terra` returned HTTP 429 from the third-party provider on four attempts. In one probe `gpt-6-astra` and `gpt-5.5` answered while `gpt-5.6-luna` and `gpt-5.4` also returned 429. The harness read a private copy of the Codex configuration with only the model changed; the real configuration was not modified. This departs from the harness's default-model rule, so this pass proves the wheel with that model, not with the configured default.

**Codex host: not passed.** Creation, connection, doctor challenge and a fresh native `whoami`/`read_team` passed, and the invitation was created, on harness commit `c65a459`. The guest then failed to join, twice, because the host was unreachable. On Windows the Codex sandbox stops the background host when a command exits, and the restored host lives only while an owner native session is open. The harness runs sessions one at a time, so no owner session is open during the join. No Codex-hosted exchange has passed on any candidate. Whether a join succeeds while a Codex owner session stays open is untested.

The harness fixes in this rerun changed test instructions and approvals, not product code: Claude Code 2.1.316 prefers PowerShell, so that tool is disabled to keep the exact-path Bash approvals; Codex may read the Skill with a file command and is no longer told to use a Bash tool; and an owner whose host was stopped by its sandbox must complete the challenge in the new session instead. Launching the harness from Git Bash truncated PATH and broke the Codex CLI lookup, so these runs start from PowerShell. Because the harness disables Claude Code's PowerShell tool, the PowerShell path was not exercised. The command shape the Skill documents, `"<python>" -m coopagents.space_runtime ...`, is a parse error in PowerShell without a leading `&` (checked directly), and the Skill gives no PowerShell form.

**This record is for the RC1 wheel only, and that wheel is no longer the release candidate.** After `b742298`, `main` gained 14 changed files under `src/` (the multi-harness adapters and doctor changes from PR #20). The result above does not carry over to them. A new candidate needs its own exact-wheel run, and the unresolved items are the Codex-as-host exchange and the P2P join path (PR #21).

## Packaged lifecycle and product limits

Packaged Codex creation and a fresh session passed. The native host lifecycle run passed nine checks: accidental host loss and recovery, independent live doctor, unchanged profile, explicit stop without resurrection, explicit resume, and identity retention. Keep an owner native session open during collaboration; reopening it restores the managed host after it exits.

This work does not establish macOS support, two independent users, two devices behind separate home/mobile NAT networks, every harness, or stable 1.0 readiness. The GitHub App evidence covers the dedicated read-only test app and repository in the P0 record, not organization approval or production limits.

All raw native records, credentials, package reports, databases, backups and failed runs remain under ignored private directories. GitHub/PyPI publication of this RC1 wheel is not planned: the next candidate is built from current `main`, and it also needs a GPG signing key for the signed tag required by the release plan. Do not publish or claim full RC acceptance until that candidate passes its own exact-wheel run, and state the Codex-host limit and any substituted model in its release notes.
