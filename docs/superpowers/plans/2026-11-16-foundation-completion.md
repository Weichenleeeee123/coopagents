# Foundation completion in strict order

> Execution: use the existing isolated feature worktree, implementation subagents within the active foundation only, test first, and verify evidence before completion. The user's explicit sequence supersedes repeated per-task spec/quality review gates.

**Goal:** Finish the five original foundations at code level, in order, with staged commits.

**Scope correction from the user (2026-11-16):** Implement the first five foundations and their necessary automated checks only. Stop real native-agent, cross-device and independent-user validation for now. Do not expand into the five multiplayer product outcomes. A later single PR will contain the staged implementation commits. This instruction supersedes the earlier requirement to run real acceptance before advancing.

**Architecture:** Keep the common coordination service authoritative and add the missing reusable capabilities there. Complete each foundation's code and focused automated regressions before starting its successor. Retain the native evaluator for later opt-in acceptance, without running it in this pass.

**PR branch (consolidated 2026-11-17):** `codex/foundation-sequential-pr`, worktree `foundation-sequential-pr`. Implementation and private verification logs remain in `foundation-sequential-completion`; the earlier `team-workflow-implementation` worktree and all experiment records also remain intact. The PR branch starts at `65a4177` and contains only this task's staged implementation/scope commits, without unrelated parallel documentation commits. No existing files or worktrees were removed.

**Tech stack:** Python unittest, the installed authenticated Codex and Claude CLIs, native HTTP MCP, isolated private profiles and SQLite; existing JavaScript where later product work requires it.

## Strict gate ledger

| Order | Foundation | Current status | Exit evidence |
| --- | --- | --- | --- |
| 1 | Real goals without tool-name prompting | CODE COMPLETE — `4961b38` | Native execution framework, five original cases, isolated answers/artifact oracle, native event/usage parsers, paired comparison and retained failures; 149 native-free tests passed. Actual acceptance deferred. |
| 2 | Shared daily collaboration behavior on all supported paths | CODE COMPLETE — `2d8b544` | Shared lifecycle policy data, consistent MCP/Git/P2P notices, supported hook/plugin wiring and Skills; 50 focused automated checks passed. Native behavior deferred. |
| 3 | Short request/reply paths | CODE COMPLETE — `dddf017` | Owner questions persist without a source task, queue and follow current responsibility; stale routes cannot answer/confirm, latest reply reads are explicit, history remains visible; 108 focused Python checks and 7 Node/syntax commands passed. |
| 4 | Task-focused incremental context and session delivery | CODE COMPLETE — `35fc2c0` | Persistent frozen snapshot/delta batches, added/updated/removed records and resync; current execution/native aliases, short watcher leases, directed delivery and member fallback; 119 focused automated checks passed. Native behavior deferred. |
| 5 | Observable waiting and concrete recovery | CODE COMPLETE — `0f39cb2` | Bounded factual service/local diagnostics and recovery guidance; protected identity-bound bridge/Git outbox, original-payload replay, bounded retries and explicit stop/auth/quota handling; final affected suite 152 checks plus 7 Node/syntax commands passed. |

Code completion requires the original capability to be implemented and its focused regressions to pass, followed by a coherent commit. Actual model behavior and independent-user acceptance remain unverified and must not be inferred from those tests. They no longer block this user-authorized code-only pass. Do not start the next foundation until the current code-level gate is met.

## Foundation 1 implementation

### A. Native trace interpretation

Files: `experiments/agent-integration/workflow_native_trace.py`, `test_workflow_native_trace.py`.

- [x] Write failing tests for actual Codex JSONL and Claude stream-JSON calls, failed/partial calls, duplicated usage and missing costs.
- [x] Implement `parse_trace(harness, events)` and conservative aggregate metrics, preserving unknown values.
- [x] Run the targeted tests and existing native parser regressions.

### B. Isolated business cases and real artifact oracle

Files: `experiments/agent-integration/workflow_native_cases.py`, `test_workflow_native_cases.py`.

- [x] Prepare `frontend-backend`, `three-member-routing`, `reply-continuation`, `session-reopen`, `teammate-unavailable` as separate role projects.
- [x] Place a generated backend-only interface field outside the requester project. Give goals without tool names, call order, or the answer.
- [x] Verify a requester source change against the backend oracle in a separate bounded interpreter, with two input names and independent work checked separately.
- [x] Reject overwrites and retain all generated evidence.

### C. Actual native execution and collection

Files: `experiments/agent-integration/workflow_native_runner.py`, `test_workflow_native_runner.py`.

- [x] Implement and test opt-in execution, exact approvals, private profiles, credential-safe output, bounded processes and fresh directories.
- [x] Reuse existing private-home preparation without modifying the user's live settings or changing their model.
- [x] Implement ordinary project/member/task seeding and native MCP process execution; the harness does not send the evaluated questions or replies itself.
- [x] Implement private timestamped event, usage, source/config fingerprint, prompt, artifact and snapshot collection.
- [x] Implement concurrent workers, ordinary continuations and fresh-session recovery, with separate continuation/reminder counts.
- [x] Implement paired arms with identical goals/data/model configuration and explicit exposure differences.
- [x] Implement structured native-call/source/artifact verification; receipts alone cannot pass it. Actual acceptance remains deferred.

### D. Run, measure and document

Files: `docs/workflow-evaluation.md`, `docs/foundation-1-native-acceptance.md`, this ledger.

- [x] Run the native-free regression suite and inspect all results (149 passed before framework commit).
- [ ] Run real native preflight without substituting models or retrying quota failures.
- [ ] Execute and retain the five scenarios in both paired arms; record failures as failures.
- [ ] Publish a sanitized measured summary with denominators and unknown metrics. No fabricated monetary estimate or independent-user claim.
- [x] Commit source/tests and maintained documentation in coherent stages. Preserve every file and leave existing branches/worktrees available.

Instrumentation findings retained before a valid baseline: (1) a missing private Windows sandbox backend silently changed effective permissions; (2) sequential requester/responder process scheduling could deadlock on an otherwise valid native wait. The private adapter now selects the normal restricted-token backend, and normal cases run actual workers concurrently after a durable question appears. The reopen case has an explicit owned-process cancellation event. Neither discovery advanced work to Foundation 2.

## Subsequent foundations

Only after the current foundation's code-level gate passes and its changes are committed, implement the next foundation. Do not implement the five later multiplayer outcomes in this pass. The unchecked real-run tasks above are deliberately deferred acceptance work, not permission to resume lengthy native experiments.

## Code-only verification record

All logs below are private retained files in the `foundation-sequential-completion` worktree's ignored `.local/test-evidence/`, except the original framework log in the retained `team-workflow-implementation` worktree.

| Stage | Actual automated result | Retained log |
| --- | --- | --- |
| 1 framework | 149 native-free experiment tests passed | `foundation-1-experiments-precommit.log` |
| 2 policy/hooks | 50 focused tests passed | `foundation-2-code-tests.log` |
| 3 owner questions | 108 focused Python tests; 7 Node/syntax commands passed | `foundation-3-code-tests.log` |
| 4 deltas/session dispatch | 119 focused tests passed | `foundation-4-code-tests-final.log` |
| 5 final affected set | 152 focused tests passed in 85.880 seconds; 7 Node/syntax commands passed | `foundations-final-code-tests.log` |

Counts overlap across stages and must not be added as a unique-test total. The final affected set covers outbox/Git/bridge recovery, diagnostics, deltas, workflow scenarios, policy/Skills contracts and session routing. It is not a claim that the entire repository CI suite, real native-agent sessions or independent-device acceptance was run. The existing protocol integration fixtures were updated for the new contracts but their actual stdio/native runs remain outside this pass.

The consolidated PR worktree's production, tests, experiments and CI Git trees were compared with the verified implementation branch and were identical. Its checkout-specific import path was then checked and 5 focused schema/recovery tests plus the 2 affected Node UI regressions passed. Only this documentation record differs afterward. No branch was pushed, no PR was opened, and no real native/cross-device validation was resumed.
