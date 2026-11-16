# Foundation completion in strict order

> Execution: use the existing isolated feature worktree, implementation subagents within the active foundation only, test first, and verify evidence before completion. The user's explicit sequence supersedes repeated per-task spec/quality review gates.

**Goal:** Finish the five original foundations without advancing past an incomplete predecessor.

**Architecture:** Keep the existing common coordination service authoritative. First build a real native-agent evaluation harness around that unchanged service; use its retained observations to drive subsequent product work. Fixture, protocol, native behavior, and independent-user acceptance remain separate.

**Tech stack:** Python unittest, the installed authenticated Codex and Claude CLIs, native HTTP MCP, isolated private profiles and SQLite; existing JavaScript where later product work requires it.

## Strict gate ledger

| Order | Foundation | Current status | Exit evidence |
| --- | --- | --- | --- |
| 1 | Real goals without tool-name prompting | IN PROGRESS | Native runner; five original scenarios; independent answer source; verified implementation effect; exact native versions/models/source; all attempts retained; measured reminders, routing, reply latency, answer use, tools, tokens and honestly reported cost; paired primitive/composite comparison |
| 2 | Shared daily collaboration behavior on all supported paths | NOT STARTED | Actual startup/blocker/reply/completion behavior across supported transports and hooks, with native trust and authority preserved |
| 3 | Short request/reply paths | NOT STARTED | Complete responsibility-following question semantics and reply consumption, measured against primitive tools |
| 4 | Task-focused incremental context and session delivery | NOT STARTED | Real additions/updates/removals, cursor recovery, current execution binding, targeted native delivery and member fallback |
| 5 | Observable waiting and concrete recovery | NOT STARTED | Evidence-based service/network/session/hook/watcher states, durable local outbox and authorized recovery |

No row can become complete merely because its unit tests pass. If native authentication, quota, or another required input prevents its exit evidence, retain the failure and stop advancement at that row. Do not implement later foundations to conceal a failed evaluation. A failing measured product workflow can be a valid baseline result, but an unexecuted required scenario is not a baseline.

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

Only after Foundation 1's gate passes, write the concrete next-item tests and implementation steps based on its observed results, then implement Foundation 2. Repeat the same transition rule for Foundations 3, 4, and 5. The original ten-point first-pass checklist does not certify these original requirements; this ledger supersedes its completion interpretation.
