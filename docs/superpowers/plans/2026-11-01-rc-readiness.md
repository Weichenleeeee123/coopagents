# 1.0 RC Readiness Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to execute the following steps in order. Preserve every file and failed experiment. The user authorized implementation, verification and entry into RC.

**Goal:** Resolve intermittent native Codex tool discovery, verify the candidate wheel from a clean install and with retained 0.9 data, then enter 1.0 RC.

**Architecture:** Keep the authenticated stdio bridge and existing owner lifecycle. Trace the native client, stdio discovery, host recovery and authenticated remote boundary before selecting a fix. Test distributions with independent interpreters that cannot import the editable checkout. RC is a prerelease with explicit platform/network limitations.

**Tech Stack:** Python 3.11+, MCP 2.3.0, native Codex/Claude, wheel/sdist, GitHub Actions and PyPI Trusted Publishing.

## 1. Locate the discovery failure

- [x] In isolated private homes, record timestamps, method names, safe error classes and tool counts at bridge startup, identity verification, remote discovery and return to Codex. Never log credentials or remote bodies.
- [x] Reproduce startup, intentional stop and explicit resume with the native CLI. Compare passing and failing traces, including the native MCP discovery timeout and whether discovery returns an empty success result.
- [x] Add a failing regression for the observed cause in `tests/test_space_bridge.py` or `tests/test_native_host.py`; implement the smallest fix and run the targeted tests.
- [x] Require consecutive fresh native sessions to load and call `whoami`/`read_team`, including recovery and explicit resume. Preserve each failed run; do not retry a failed acceptance into a pass.

## 2. Verify the packaged candidate

- [x] Build the wheel/sdist into a new ignored directory; create independent virtual environments and install the exact wheel with its SHA-256 recorded.
- [x] Extend the native acceptance runner to accept an installed distribution, verify imports are under that environment, and load the Skill from that installed package.
- [ ] Keep the native owner session open during peer collaboration; do not have the runner substitute its own background host. Complete create, invitation, join, fresh native identities, file-derived requests/replies and model consumption in both directions.

## 3. Verify 0.9 upgrade

- [x] Install published `coopagents[space]==0.9.0` in an isolated environment. Create synthetic identities, invitation and business records using that version; stop it and retain a database/profile backup and hashes.
- [x] Install the candidate wheel in a separate environment, start the retained owner state and prove identity, P2P endpoint and business records persist. Exercise existing member access and a new native connection without repeating membership join.
- [x] Run the candidate's full core/experiment suites, build checks and CI; retain evidence outside Git. `4b6bf43` CI passed Python 3.11/3.13, 678 core and 54 experiment tests, Node, build and container/TLS smoke.

## 4. Enter RC

- [x] Set `1.0.0rc1`, record tested client versions and known macOS/two-user/NAT/Harness limits in RC notes, and synchronize installation/support documentation.
- [x] Build versioned RC artifacts and verify clean install/CLI smoke plus published 0.9 migration. The exact-RC1 full native exchange stopped before its reverse reply when the chosen provider reported insufficient balance.
- [ ] Prepare/publish the prerelease with the exact verified assets using Trusted Publishing. Complete the exact-RC1 native flow and configure a GPG signing key first. Do not publish a final 1.0 or claim unverified combinations as supported.
