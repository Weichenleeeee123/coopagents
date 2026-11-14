# Coopagents 1.0.0rc1

`1.0.0rc1` is the prepared release candidate for Coopagents 1.0. It includes the agent-first P2P setup, recovery and doctor work developed after 0.9.0, plus the Codex MCP startup discovery fix. It is a prerelease and must not be treated as the stable 1.0 release. GitHub/PyPI publication is pending a full exact-RC1 native model run and signed-tag setup.

## Verification

- A pre-versioned development wheel was installed into two separate clean Windows virtual environments. Claude Code 2.1.282 created a P2P space; fresh Claude and Codex 0.166.0-alpha.5.1 sessions verified their identities. Both agents asked and answered questions using the exact contents of separate local files, and the requesting models consumed the replies. Backend records independently confirmed both exchanges.
- The versioned RC1 wheel installs in a clean Windows environment, its CLI starts, and its 0.9.0 migration passes. Its native rerun passed the first exchange and the reverse request, then stopped before the reverse reply when the configured third-party provider reported insufficient remaining balance. The exact RC1 archive has not passed the complete model flow.
- A synthetic 0.9.0 space created with the published PyPI distribution upgraded in place. Existing identities, P2P host key, task ownership, session progress, request/reply and asset content remained accessible; the existing member connected without joining again. The retained pre-upgrade backup remained unchanged.
- Codex 0.166.0-alpha.5.1's optional MCP startup grace could omit a delayed server from the first model turn. Coopagents now marks its verified Codex connection required and assigns at least 120 seconds for startup discovery. Controlled delayed discovery and three consecutive fresh native sessions passed.
- Release CI passed on Python 3.11 and 3.13: 678 core tests and 55 native-free experiment tests per version, three platform-specific skips, JavaScript checks, package builds, and container/TLS smoke.

## Known limits

- Native acceptance used Windows and two agent profiles on one computer, with a third-party model provider. It does not establish two independent users or two-device connectivity.
- macOS was unavailable and is not verified. Linux runtime support is not a substitute for native macOS or cross-platform harness testing.
- Both peers behind separate home/mobile NAT networks, direct-versus-relay behavior in those networks, and host availability when all native owner sessions close are not certified. Keep a native owner session open for collaboration; reopening it restores the managed host after it has exited.
- 1.0 commits only to Claude Code and Codex on Windows and Linux. Cursor, OpenCode, Pi, Kimi Code, ZCode, DeepSeek and the Windsurf/Devin spec ship as experimental adapters. This candidate does not establish a complete native task loop for any of them. Consult the [adapter support matrix](harness-adapters-0.9.md) and [P0 acceptance record](release-1.0-p0-acceptance.md).
- Claude Code MCP setup runs permitted local `space_runtime` commands. If the native session has no command approval surface, setup cannot proceed in that session; do not bypass its policy.
- Codex marks its Coopagents server required so a startup failure can block native Codex startup until the connection is fixed or disabled. Existing Codex users must rerun `connect` and open a new session to apply the setting.
- The release plan calls for a signed release tag. No GPG signing key is configured on the current workstation; publication waits for signing to be configured.
- GitHub App evidence covers the dedicated read-only test app and repository described in the P0 record; it does not certify organization approval, merge workflows, or production rate limits.

See the [RC readiness report](rc-readiness-2026-11-01.md) for the exact archive hash and evidence boundaries. The latest installable stable release remains 0.9.0. These prepared artifacts are not published; do not install from PyPI or fetch a tag until a published RC is announced.
