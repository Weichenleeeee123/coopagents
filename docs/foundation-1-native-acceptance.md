# Foundation 1 native evaluation acceptance

Started: 2026-11-16. PR consolidation: 2026-11-17 on `codex/foundation-sequential-pr`. Framework commit `4961b38` preserves the implementation first recorded as `b8fea59` on `codex/team-workflow-implementation`; private verification records remain in their original retained worktrees.

**Status: framework code complete; actual native acceptance deferred at the user's request.** The final native-free experiment suite ran **149 tests, all passed**, in 47.228 seconds before commit `b8fea59`. The current [strict ledger](superpowers/plans/2026-11-16-foundation-completion.md) now gates advancement on implementation, focused tests and staged commits. Real native experiments have stopped. Their unfinished acceptance is not being reported as passed.

The later DSH network sandbox implementation is tracked separately in [the sandbox runbook](dsh-sandbox-runbook.md). Its local components and automated checks do not complete this native acceptance gate; real DSH sessions and cloud-network evidence remain outstanding.

## Implementation scope

The new execution path comprises `workflow_native_cases.py`, `workflow_native_process.py`, `workflow_native_trace.py` and `workflow_native_runner.py` under `experiments/agent-integration/`, with corresponding native-free regression tests. It complements the existing normalized-evidence scorer, which remains explicitly reviewer-attested rather than authenticated native proof. The [evaluation guide](workflow-evaluation.md) describes execution, measurement, pairing, and evidence boundaries.

## Retained unsuccessful controls

These records remain in the retained `team-workflow-implementation` worktree; they were not copied into or committed with the new code-only worktree.

These observations are not successful collaboration acceptance and are not included in a valid paired baseline:

- `20261116-213343-46871b37` under `.local/cold-start-acceptance/`: actual native no-tools preflight. Codex returned the expected visible control response. Claude exited with code 0 and a native successful result envelope but produced no visible answer; its response control failed. No alternate model was substituted. A process exit is not a successful answer.
- `.local/test-evidence/foundation-1-smoke-20261116-2146/`: first single-case instrumentation smoke. The recorded native sandbox was read-only despite requested workspace-write. The owned runner and its private process tree were stopped; an explicit failure note and raw partial evidence remain.
- `.local/test-evidence/foundation-1-smoke-b-20261116-2150/`: moving the option to the `exec` command did not establish write capability. The private native sandbox log recorded MXC unavailable and Windows sandbox selection disabled. The owned runner was stopped and all evidence retained. A normally completed requester turn from this run is still not a valid writable implementation baseline.
- `.local/test-evidence/foundation-1-smoke-c-20261116-2200/`: effective workspace-write was confirmed. The native requester emitted a real question, changed the independent-work source and polled for an answer. Sequential harness scheduling withheld the responder while that requester turn remained active, so the runner was stopped with a retained scheduling-failure note. The runner now supports simultaneous real workers and an explicit owned-worker cancellation boundary only for the reopen scenario. This partial smoke is not a paired baseline.

The missing private Windows backend was diagnosed against retained native records and the installed-version native implementation. The adapter now selects `windows.sandbox="unelevated"` only in its new private Windows profile, retains workspace-write and normal approvals, and no longer requests the unavailable experimental MXC backend. No live personal configuration, global trust or permission mode was changed. A fresh smoke records effective workspace-write; its end-to-end result remains to be checked before baseline execution.

## Deferred actual acceptance

- Finish a complete real request → backend source read → model answer → requester implementation run and inspect the artifact oracle.
- Run and retain all five original scenarios in both paired arms on fixed actual native models/configuration/source.
- Verify complete metric windows, pair fingerprints, every failure and actual model/permission evidence.
- Record the measured baseline with denominators and limitations. A framework or passing helper tests alone cannot complete this gate.

No release, deployment, remote push or independent-user acceptance has occurred in this pass. Raw events, private native profiles, credentials and databases remain uncommitted. No files have been deleted by this implementation work.
