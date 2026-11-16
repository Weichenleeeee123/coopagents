# Foundation completion in strict order

> Execution: use the existing isolated feature worktree, implementation subagents within the active foundation only, test first, and verify evidence before completion. The user's explicit sequence supersedes repeated per-task spec/quality review gates.

**Goal:** Finish the five original foundations at code level, in order, with staged commits.

**Scope correction from the user (2026-11-16):** Implement the first five foundations and their necessary automated checks only. Stop real native-agent, cross-device and independent-user validation for now. Do not expand into the five multiplayer product outcomes. A later single PR will contain the staged implementation commits. This instruction supersedes the earlier requirement to run real acceptance before advancing.

**Architecture:** Keep the common coordination service authoritative and add the missing reusable capabilities there. Complete each foundation's code and focused automated regressions before starting its successor. Retain the native evaluator for later opt-in acceptance, without running it in this pass.

**Working branch:** `codex/foundation-sequential-completion`, retained isolated worktree `foundation-sequential-completion`. The earlier `team-workflow-implementation` worktree and all private experiment records remain intact.

**Tech stack:** Python unittest, the installed authenticated Codex and Claude CLIs, native HTTP MCP, isolated private profiles and SQLite; existing JavaScript where later product work requires it.

## Strict gate ledger

| Order | Foundation | Current status | Exit evidence |
| --- | --- | --- | --- |
| 1 | Real goals without tool-name prompting | CODE COMPLETE — `b8fea59` | Native execution framework, five original cases, isolated answers/artifact oracle, native event/usage parsers, paired comparison and retained failures; 149 native-free tests passed. Actual acceptance deferred. |
| 2 | Shared daily collaboration behavior on all supported paths | CODE COMPLETE | Shared lifecycle policy data, consistent MCP/Git/P2P notices, supported hook/plugin wiring and Skills; 50 focused automated checks passed. Native behavior deferred. |
| 3 | Short request/reply paths | NOT STARTED | Complete responsibility-following question semantics and reply consumption; focused domain/transport regressions |
| 4 | Task-focused incremental context and session delivery | NOT STARTED | Real additions/updates/removals, cursor recovery, current execution binding, targeted native delivery and member fallback |
| 5 | Observable waiting and concrete recovery | NOT STARTED | Evidence-based service/network/session/hook/watcher states, durable local outbox and authorized recovery |

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

- [ ] Test first: opt-in native runs, exact approvals, private profiles, credential-safe output, bounded processes and fresh directories.
- [ ] Reuse existing private-home preparation without modifying the user's live settings or changing their model.
- [ ] Seed only ordinary project/member/task setup. Start actual native processes with native MCP. The harness must not send the evaluated questions or replies itself.
- [ ] Capture timestamped events, model usage, source/config fingerprints, exact prompts, immutable artifacts, and service snapshots privately.
- [ ] Schedule initial work, responder work, neutral continuation and truly fresh native-session recovery. Count every harness continuation and any human reminder separately.
- [ ] Offer paired arms with identical goals/data/model configuration: improved primitive descriptions versus composite request/reply entries. Report the exposure difference explicitly.
- [ ] Verify actual native successful calls and linked service changes plus requester oracle; never infer comprehension from receipts or prose alone.

### D. Run, measure and document

Files: `docs/workflow-evaluation.md`, `docs/foundation-1-native-acceptance.md`, this ledger.

- [ ] Run the native-free regression suite and inspect all results.
- [ ] Run real native preflight without substituting models or retrying quota failures.
- [ ] Execute and retain the five scenarios in both paired arms; record failures as failures.
- [ ] Publish a sanitized measured summary with denominators and unknown metrics. No fabricated monetary estimate or independent-user claim.
- [ ] Commit source/tests and maintained documentation in coherent stages. Preserve every file and leave the existing branch/worktree available.

Instrumentation findings retained before a valid baseline: (1) a missing private Windows sandbox backend silently changed effective permissions; (2) sequential requester/responder process scheduling could deadlock on an otherwise valid native wait. The private adapter now selects the normal restricted-token backend, and normal cases run actual workers concurrently after a durable question appears. The reopen case has an explicit owned-process cancellation event. Neither discovery advanced work to Foundation 2.

## Subsequent foundations

Only after the current foundation's code-level gate passes and its changes are committed, implement the next foundation. Do not implement the five later multiplayer outcomes in this pass. The unchecked real-run tasks above are deliberately deferred acceptance work, not permission to resume lengthy native experiments.
