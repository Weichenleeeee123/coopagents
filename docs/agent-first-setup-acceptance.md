# Agent-first setup acceptance

Date: 2026-10-31. Scope: agent/CLI onboarding and diagnostics. No frontend implementation changes.

## Delivered behavior

- The bundled space Skill routes setup through an invitation, trusted existing project details, a selected registered profile, or a new P2P space in the current repository. Wake-up and invitation creation remain explicit choices.
- `space_runtime doctor` reports Python isolation/dependencies, native CLI version, MCP registration, Skill consistency, profile identity, transport, challenge round trip, session-loading limits and optional hook configuration.
- Without a profile, doctor lists registered bridge paths without contacting their destinations. The agent must select the intended project before networking; multiple global connections do not establish repository membership.
- `connect`, `create --connect` and `join --connect` return configuration, verification and next steps. Saved configuration survives network/authentication failures. Custom MCP names are supported by doctor through `--name`.
- Diagnostic HTTP challenges leave service-side diagnostic records. Local configuration, credentials, tasks, messages and membership remain unchanged. Native MCP loading and hook trust cannot be certified by this shell diagnostic.
- English and Chinese user guides describe both the cold-start Skill link and the shorter request available after Skill installation. Doctor is unreleased; published 0.9.0 does not have this command.

## Evidence

| Check | Result and limit |
| --- | --- |
| Full Python regression at feature baseline | 644 tests run, 1 platform skip, no failures, 396 seconds. Subsequent review corrections were checked by the focused final suite below. |
| Final related Python regression | 65 tests passed in 94.8 seconds: doctor, native connection, runtime, agent touchpoints and wake installation. |
| Real local service | Create, join, identity and challenge round trip, custom server name, repeated diagnosis, and revoked-credential rejection passed. Native CLI is a fixture in these automated tests. |
| Native Codex CLI | Version 0.146.0 registered/read back a synthetic profile in a separate configuration directory. Doctor completed identity/challenge checks and preserved configuration bytes on repeat. |
| Real stdio bridge | SDK client called whoami and read_team through the configured bridge; project identity matched. This is protocol evidence, not a model turn. |
| Web regressions | Workspace navigation, collaboration diagnostics, and agent connection privacy regressions passed; app/collaboration JavaScript syntax checks passed. |
| Distribution | Wheel and sdist include the doctor module and bundled Skill. Archive inspection found no private profiles, runtime logs or databases. Local build metadata remains 0.9.0; no release was published. |

Raw logs, synthetic profiles and configuration remain under ignored `.local/`. No real user's native configuration was modified by the native CLI fixture. The first native smoke failed because its isolated CODEX_HOME directory did not exist; creating the test configuration directory resolved it, and the failed log was retained.

## Remaining release acceptance

A real model must still execute the complete cold-start instruction in Claude Code and Codex. Two-device P2P, direct/relay behavior across home/mobile networks, macOS, and cross-device wake-up remain separate 1.0 gates. The present checks do not establish those outcomes. The shell intentionally keeps session_reload pending; the actual agent session must verify whoami/read_team rather than repeatedly reinstalling.

User guides: [English](agent-first-setup.md) · [简体中文](agent-first-setup.zh-CN.md).
