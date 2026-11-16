# Team Workflow Implementation Plan

> **For agentic workers:** Use subagent-driven-development for bounded implementation tasks and independent spec/code review. The user approved execution of all ten requirements; proceed through the stages without requesting the same authorization again.

**Goal:** Make collaboration between teammates' own agents discoverable, task-focused, asynchronous and verifiable across all ten approved requirements.

**Architecture:** Reuse the existing CoordinationService, messages, task dependencies, contracts and identity. Add shared policy, small workflow composition/projection modules and additive receipt/reliance tables. Keep human operations out of ordinary MCP discovery and keep native/two-person evidence separate from automated tests.

**Tech Stack:** Python 3.11+, SQLite, existing MCP/Starlette services, native JavaScript workbench, unittest/Node regressions.

**User execution adjustment:** Complete the first implementation round for all ten points through delegated tasks before the unified review. Do not insert repeated per-task spec/quality review gates. Necessary functional tests continue during implementation.

## Execution environment and invariants

- Worktree: `C:/Users/Weichen Li/Documents/Codex/2026-10-10/wo-zhe/.local/worktrees/team-workflow-implementation`.
- Branch: `codex/team-workflow-implementation`; base: `53b0b68`.
- The dedicated new interpreter stalls in this host. Reuse the original verified interpreter with the worktree's ignored `.local/pythonpath/coopagents` junction prepended to PYTHONPATH. Verify `coopagents.__file__` before testing; it must resolve through this worktree's junction to `src`.
- Python command in this plan: `& 'C:/Users/Weichen Li/Documents/Codex/2026-10-10/wo-zhe/.venv/Scripts/python.exe'`. Set `$env:PYTHONPATH=(Join-Path (Get-Location) '.local/pythonpath')` in each shell.
- Never delete files, including test databases, environments and failed-run evidence. Tests create UUID paths under `.local/test-evidence`.
- No private profiles, credentials, raw experiments or local configuration in commits. No push, release, membership changes or personal hook installation is required.

## Task 1: Shared policy and tool-free evaluation (R1, R2, R6)

**Files:** create `src/collaboration_policy.py`, `experiments/agent-integration/workflow_evaluation.py`, `experiments/agent-integration/test_workflow_evaluation.py`, `tests/test_collaboration_policy.py`; modify `src/mcp_service.py`, `src/space_bridge.py`, `src/git_adapter.py`, bundled Skills/protocols.

- [x] Write failing tests asserting HTTP, bridge and Git instructions include the same versioned policy, while retaining transport-specific wake/security notes.
- [x] Add scenario goals for frontend/backend dependency, three-member routing, offline/reopen, agreement change and human decision. Goals must not include MCP method names or a sequence of calls.
- [x] Test evidence scoring against missing/wrong sender, stale route, fixture-only evidence, actual native file-derived reply, requester consumption and independent-user provenance. Missing evidence must remain unknown/unverified; performance metrics cannot imply correctness.
- [x] Run `python -m unittest discover -s tests -p 'test_collaboration_policy.py' -v` and the new experiment tests; observe the missing-behavior failure first.
- [x] Implement common policy with task checkpoints, explicit reply reading, independent-work guidance, human authority and untrusted-content boundaries. Expose it via existing servers without automatically installing hooks.
- [x] Run new and existing MCP/space bridge/Git adapter tests; update exact-tool-set tests only when the tool set actually changes in later tasks.
- [x] Commit source, tests and corresponding docs as a coherent stage.

## Task 2: Owner questions and explicit sent-reply reads (R3, R7, R8)

**Files:** create `src/workflow.py`, `tests/test_workflow.py`; modify `src/coordination.py`, `src/mcp_service.py`, `src/git_adapter.py`, `src/events.py` and API integration tests.

- [x] Add failing tests that `ask_owner` uses exactly one of target task/scope, returns ambiguity/unassigned/not-found without creating a message, and sends only to a current authenticated-room owner.
- [x] With a source task, use `create_dependency` and its session/epoch/revision validation so owner changes reroute correctly. Verify request-key replay, changed-payload conflicts, retired sessions, cross-project targets and concurrent ownership changes.
- [x] Add explicit `read_replies` tests for sender isolation, numeric cursor pagination, task filtering, current/historical routes and no automatic resolution. Persist exact reply-read evidence separately from inbox/dependency receipts.
- [x] Run the focused tests and observe the absent operations fail.
- [x] Register additive schemas and tool descriptions through the shared service. Add ordinary MCP/Git forwarding and real HTTP/MCP smoke coverage. Reuse domain mutations rather than duplicating SQL for dependency state transitions.
- [x] Run focused workflow, dependencies, messages, MCP and Git adapter tests; commit the stage.

## Task 3: Focused briefs and recovery projection (R4, R5, R8)

**Files:** extend `src/workflow.py`; create `src/team_workflow.py`, `tests/test_team_workflow.py`; modify shared service registrations, MCP/Git forwarding and event registration for new tables.

- [x] Add failing tests for task-authorized `work_brief`, stable content cursor, changed-content delta, project/member/focus cursor binding, invalid/future cursor reset, fixed byte budget and explicit truncation.
- [x] Prioritize current task, direct dependencies, relevant requests and current approved agreements. Keep member-level access additive; enforce execution authority whenever task/session is supplied.
- [x] Project request lifecycle facts separately: delivered/read/acknowledged/replied/requester-read/resolved; include latest checkpoint timestamps as observations, not model availability guarantees.
- [x] Provide allowlisted recovery hints and task execution targets. Preserve historical-route status and never claim a status from transport events alone.
- [x] Reopen a fresh service instance on the retained test database and verify outstanding questions, explicit reply reads and changes can be recovered.
- [x] Run focused and existing context/checkpoint/capability tests; commit the stage.

## Task 4: Agreement impact and human decisions (R9, R10)

**Files:** create `src/agreement_usage.py`, `tests/test_agreement_usage.py`; extend `src/team_workflow.py`; modify service/MCP/Git exposure and event schema.

- [x] Add failing tests for `record_agreement_use`: approved versions only, active task owner/session/epoch required, room isolation, idempotent reliance records and retained previous evidence.
- [x] Verify a new draft does not change effective agreement, a newer approved version reports review required, and only an explicit current-execution reliance record updates the accepted baseline.
- [x] Project decision cards for pending contract heads, handoffs, unassigned ownership and delivery suggestions. Include concrete identifiers/revisions and bounded summaries; do not expose human mutation tools to agent MCP.
- [x] Verify permissions and source/member filtering, stale responsibility cycles and no automatic approval/acceptance/read receipts.
- [x] Run domain, events, task lifecycle, contract, HTTP and MCP regressions; commit the stage.

## Task 5: Team experience and first collaboration (R5, R6, R8, R9, R10)

**Files:** modify `src/static/collaboration.js` and its existing invocation; create `tests/team_workflow_ui_regression.js`; extend collaboration UI regressions; add `docs/team-workflow.md`, `docs/team-workflow-acceptance.md` and link from `docs/README.md`.

- [x] Add behavioral Node tests for milestone display, request wait reasons, human decision summaries, safe text rendering, task links, empty state and project-switch isolation.
- [x] Add compact sections to the existing collaboration panel using native text DOM and existing task navigation callbacks. Keep the P2P board read-only and do not redesign the workbench.
- [x] Show identity/checkpoint, real addressed exchange and explicit requester reply-reading as separate onboarding facts. Explain that explicit reading is not proof of model comprehension.
- [x] Document owner questions, focused recovery, reply reads, agreement reliance and human decision boundaries with exact API examples. Include the ten-row requirement/evidence matrix.
- [x] Run Node behavioral regressions and syntax checks. Visually inspect the real synthetic-data service at desktop/mobile widths using the available browser skill; retain screenshots privately.
- [x] Commit interface and maintained documentation.

## Task 6: Integration, independent review and acceptance

- [ ] Review requirements R1-R10 against implementation, tests and guides, then request independent code-quality review. Correct important issues and repeat affected verification.
- [ ] Run full Python tests, agent-integration experiment tests, all JavaScript regression commands from CI, syntax checks and build artifacts where feasible.
- [ ] Inspect distributions for the new source/Skill modules and absence of private state. Run `git diff --check` and check no tracked file deletion.
- [ ] Record exact tested commands/counts, source commit, known environment limits and unperformed native/two-independent-user gates in `docs/team-workflow-acceptance.md`.
- [ ] Commit the final acceptance record and report branch/worktree, delivered scope, verification and genuine external limits. Do not claim two-user model acceptance from fixtures or local service tests.

## Coverage self-review

R1/R2: task 1. R3/R7: task 2. R4/R5/R8: tasks 2-3. R9/R10: task 4. R6 and visible team experience: task 5. Cross-cutting permission/isolation/durability/budgets: tasks 2-6. All ten remain in scope; external users, devices, network conditions and native trust are validation gates, not fabricated successes.
