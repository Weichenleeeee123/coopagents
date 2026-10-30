# Pre-0.9 Abilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver the three confirmed pre-1.0 capability improvements as composable API, MCP, storage, UI, and regression-test surfaces: shared context, member and Harness capability discovery, and traceable delivery associations.

**Architecture:** Extend the existing `CoordinationService` and SQLite-backed stores with bounded, evidence-bearing read models. Preserve existing task, message, GitHub, and Harness contracts; add explicit read operations where consumers need a stable capability boundary. The web board and MCP expose the same structured facts, while freshness and source semantics remain server-derived.

**Tech Stack:** Python 3.11+, SQLite, Starlette, MCP SDK, vanilla JavaScript regression harnesses, pytest/unittest.

---

### Task 1: 0.9.1 shared context contract

**Files:**
- Create: `src/context.py`
- Modify: `src/coordination.py`
- Modify: `src/api.py`
- Modify: `src/coordination_http.py`
- Modify: `src/mcp_service.py`
- Test: `tests/test_shared_context.py`

- [ ] Add a `ContextStore` that authenticates the caller, accepts bounded filters (`task_id`, `member_id`, `after`, `limit`), and projects only structured collaboration records. Each item must include `source`, `scope`, `observed_at`, `freshness`, and `privacy='shared_structured'`; omit private transcript or tool payload fields.
- [ ] Expose `read_context` as a read operation and `/api/context`; include the same result in the room snapshot under `shared_context` for existing consumers.
- [ ] Add MCP `read_context` with a description that distinguishes context availability from model consumption and does not mark messages as read or perform workflow actions.
- [ ] Cover task, progress, session, request, contract, and Git delivery facts, filtering, limits, stale timestamps, privacy boundaries, and cross-room denial.
- [ ] Run focused tests and commit `feat: deepen shared collaboration context`.

### Task 2: 0.9.2 member and Harness capability discovery

**Files:**
- Create: `src/capabilities.py`
- Modify: `src/activity.py`
- Modify: `src/coordination.py`
- Modify: `src/api.py`
- Modify: `src/coordination_http.py`
- Modify: `src/mcp_service.py`
- Modify: `src/static/space_board.js`
- Modify: `src/static/index.html`
- Modify: `src/static/app.js`
- Test: `tests/test_capability_discovery.py`
- Test: `tests/capability_discovery_ui_regression.js`

- [ ] Extend session registration with optional Harness version, platform, and capability evidence; keep old callers valid and reject unsafe/oversized values.
- [ ] Build a discovery projection that separates member, agent session, connection freshness, event delivery, and declared capability status. Report `supported`, `unsupported`, `unknown`, `unavailable`, or `stale` with evidence timestamp and constraints.
- [ ] Include all seven target Harness entries even before a member connects, using the adapter contract for MCP/project context/native hook/idle wake evidence and explicit unknown semantics for unverified combinations.
- [ ] Expose `/api/capabilities`, `read_capabilities` MCP, and `capabilities` in snapshots; render a compact discovery panel showing teammates, tools, versions, platform, last-seen, and capability status without implying model activity.
- [ ] Add backend and UI regression coverage, run focused tests, and commit `feat: add member and harness capability discovery`.

### Task 3: 0.9.3 delivery association and evidence traceability

**Files:**
- Create: `src/delivery.py`
- Modify: `src/github_sync.py`
- Modify: `src/coordination.py`
- Modify: `src/api.py`
- Modify: `src/coordination_http.py`
- Modify: `src/mcp_service.py`
- Modify: `src/project_activity.py`
- Modify: `src/static/git.js`
- Modify: `src/static/board.js`
- Test: `tests/test_delivery_traceability.py`
- Test: `tests/delivery_ui_regression.js`

- [ ] Add a normalized delivery projection across branch, commit, PR, and Release with task reverse lookup, relationship source (`explicit`, `observed`, `suggested`), actor, evidence timestamp, stale/unavailable flags, and many-to-many grouping.
- [ ] Preserve existing GitHub reference tables and linking behavior; make association source and confirmation explicit, never infer task completion or acceptance from merge/release facts.
- [ ] Expose `/api/deliveries`, `read_deliveries` MCP, and a task/project view that shows the same normalized evidence and reverse links.
- [ ] Extend project activity with delivery association events while retaining bounded summaries and safe URL handling.
- [ ] Add regression coverage for multiple tasks per delivery, stale evidence, revoked/unavailable objects, suggested versus explicit relations, and the no-auto-close rule; run focused tests and commit `feat: improve delivery traceability`.

### Verification

- [ ] Run the full Python test suite and every JavaScript regression script listed by `CONTRIBUTING.md`.
- [ ] Run `git diff --check`, inspect the staged diff for credentials or raw experimental data, and verify the worktree is clean after the three commits.
