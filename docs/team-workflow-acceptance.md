# Team workflow implementation and acceptance

Date: 2026-11-16. Branch: `codex/team-workflow-implementation`.

Completion clarification: this document records the earlier development pass and its narrower delivered scope. It does **not** establish completion of the original ten requirements. The remaining original foundations are now tracked in [strict foundation completion](superpowers/plans/2026-11-16-foundation-completion.md); [foundation 1 native acceptance](foundation-1-native-acceptance.md) records the new real-execution work and retained failures. Later foundations must not start until their predecessor's gate is met.

All ten approved points have a first implementation, maintained guides and automated coverage. The remaining implementation was delegated in parallel following the user's request to finish the whole first round before a unified review. That review found two projection defects; both were reproduced, corrected and covered by regressions. This is an unreleased development implementation, not native-model, independent-user or production acceptance.

Final verified source commit: `490ed15ece923bc5b185e04b53d3785efd88dc6a`. Later changes to this record and the plan are documentation only. Scope: [approved design](superpowers/specs/2026-11-16-team-workflow-design.md). Usage: [team workflow guide](team-workflow.md). Evaluation: [tool-free workflow evaluation](workflow-evaluation.md).

## Ten-point delivery and evidence

| ID | Delivered behavior | Automated evidence and remaining boundary |
| --- | --- | --- |
| R1 | Five tool-free development scenarios with separate participant goals and private evidence filenames; conservative normalized scoring of identity, current route, model reply, requester effect and independent human/device/session/network provenance | 20 evaluator tests within the 80-test experiment suite. References are reviewer-supplied attestations, not independently authenticated proof. No real model or two-user run performed here. |
| R2 | One versioned daily policy across HTTP MCP, P2P bridge and local Git, with checkpoint, focused context, responsibility questions, sent-reply reads, agreement review and human authority guidance | Policy tests, existing MCP/bridge/Git regressions, explicit equality of new-tool descriptions across HTTP/Git. Native loading and voluntary model use remain separate gates. |
| R3 | `ask_owner` and paginated `read_replies`, preserving exact sender/route facts and separate explicit reply reads | Domain, authenticated HTTP/MCP and actual bound-project Git forwarding. Same-member sessions also supported. A read does not prove comprehension or resolve dependencies. |
| R4 | `work_brief` with current execution validation, task/direct-dependency context, approved agreement changes and 16,000-byte bounded paging | Cursor identity/focus/session/epoch/limit binding, semantic change reset, no skipped records, stale authority before cursor fast path, HTTP wire-size and no-receipt tests. Changed content resets; this is not a delta stream. |
| R5 | Separate delivered/read/processing/replied/requester-read/resolved facts, observed session times, wait reasons and recovery hints | Lifecycle, durable reopen and UI behavior tests. Unknown model responsiveness remains unknown. Recorded confirmation reads survive closure without authorizing new transitions. |
| R6 | Same-exchange two-distinct-member onboarding milestones and navigation to existing request details | Synthetic sender/recipient exchange, first-use projection, browser rendering and navigation. Project read identity and explicit reply reading are not native loading or useful model-work evidence. |
| R7 | Declared task/scope responsibility routing with explicit ambiguity/not-found/unassigned results | Atomic lookup/delivery, payload-bound retry, target handoff history and task dependency rerouting. Member-level questions intentionally retain their original fixed recipient. |
| R8 | Durable questions, reply reads and outstanding work across service reopen; queued task dependencies route after target claim | Retained SQLite/domain and actual HTTP reopen tests. Simulated offline means no responder action before reopen; no new network-outage or cross-device wake claim. Existing optional wake behavior is unchanged. |
| R9 | Epoch/session-scoped `record_agreement_use`, approved-version reliance, newer-approved-version impact and monotonic baseline | Draft/approved version, older retry, room isolation, legacy-to-bound session, retired execution and signed-64 identifier boundary tests. No automatic approval or adoption. |
| R10 | Bounded human decision summaries with exact operation payloads, eligibility and links to existing authorized surfaces | Pending contracts, recipient handoffs, unassigned claims, current-epoch delivery suggestions and agreement review tests. MCP has no human mutation tools; cards authorize nothing by themselves. |

## Verification results

| Check | Observed result |
| --- | --- |
| Full Python suite after initial integration | **850 tests run, no failures, 3 platform skips**, 806.416 seconds. Log: `.local/test-evidence/final-python.log`. This run preceded the last two projection fixes and the two additional Git forwarding tests. |
| Final affected integration suite against source `490ed15` | **124 tests passed**, 76.467 seconds. Includes all workflow tests, agreement usage, policy, dependencies, messages, HTTP/MCP/Git, events, checkpoints, context and capabilities. Log: `.local/test-evidence/final-postfix-integration.log`. |
| Agent-integration experiment regressions | **80 tests passed**, 15.843 seconds. Includes 20 tool-free evaluator tests. Log: `.local/test-evidence/final-experiments.log`. These native-free fixtures do not execute real model collaboration. |
| JavaScript CI and syntax | **37 commands passed**, 0 failures: all 32 Node commands in CI plus 5 extra checks covering every static JavaScript file. Node `v22.23.2`; log `.local/test-evidence/final-node-20261116-210415-b0170597.log`. No JavaScript changed after this run. |
| Live synthetic browser | Workbench rendered at **1440 x 1000** and **390 x 844**. Mobile document width was exactly 390; no horizontal overflow. A new workflow request link opened the existing request dialog. Retained screenshots: `.local/test-evidence/team-workflow-desktop.png` and `team-workflow-mobile.png`. |
| Final distributions | Wheel and sdist built from clean `490ed15`; required source, JavaScript, Skills and protocols matched exact source bytes; no private paths. Fresh isolated wheel imports/resources and five-operation service composition smoke passed. |
| Repository checks | Whitespace check clean; no tracked file deletions from base `53b0b68`. Worktree, databases, environments, screenshots, failure records and old package artifacts retained. No release or remote push performed. |

The full-suite skips were Windows POSIX-mode inspection and two unavailable symlink-creation checks. An earlier uncontrolled broad run had two environment-dependent failures: inherited native-agent marker variables affected a caller-detection test, and PATH selected the Windows Bash launcher rather than Git Bash for a native-shell test. The successful full run cleared those markers only inside the test process and explicitly selected Git Bash. No product permission, native configuration or model settings were changed to obtain a pass. Earlier failed logs remain retained.

The browser console contained one `/account/session` 401 during synthetic self-hosted account probing; no additional script exception was observed in the inspected console. Project-switch/stale-click isolation and safe text rendering are covered by behavioral JavaScript tests; the browser check did not certify two real users or every project-switch route.

## Commands and import isolation

Commands ran from the retained feature worktree. Its ignored `.local/pythonpath/coopagents` junction resolves to that worktree's `src`. The new environment executable stalled in this host, so tests used the existing interpreter with this explicit import path; `coopagents.__file__` was verified before testing. A separate isolated wheel smoke did not use this editable import.

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location) '.local/pythonpath')
$python='C:/Users/Weichen Li/Documents/Codex/2026-10-10/wo-zhe/.venv/Scripts/python.exe'
$env:CODEX_THREAD_ID=''
$env:CODEX_SESSION_ID=''
$env:CLAUDECODE=''
$env:PATH='C:\Program Files\Git\bin;'+$env:PATH
& $python -c "import coopagents; print(coopagents.__file__)"
& $python -m unittest discover -s tests -v
& $python -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
```

The final 124-test command used one `unittest.TestSuite` over these discover patterns: `test_*workflow*.py`, `test_agreement_usage.py`, `test_collaboration_policy.py`, `test_dependencies.py`, `test_messages.py`, `test_mcp.py`, `test_git_adapter.py`, `test_events.py`, `test_checkpoints.py`, `test_shared_context.py`, `test_capability_discovery.py`. JavaScript commands are retained in the Node log and CI; the new workflow UI regression is explicitly included in CI.

## Final package evidence

Internal development artifacts retain existing `1.0.0rc1` package metadata. They have not been published and do not establish public RC readiness.

Artifacts: `.local/dist-team-workflow-0488e19aed0e432e989b0808e4053b2e/`. Audit: `.local/test-evidence/team-workflow-0488e19aed0e432e989b0808e4053b2e/`.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `coopagents-1.0.0rc1-py3-none-any.whl` | 436566 | `92152dd74091d054be21d8321539699182d5c29d3efb678135692503d37f0d15` |
| `coopagents-1.0.0rc1.tar.gz` | 569073 | `b35f2c3e7c369e6e7e57fad8cd49a0f738c1aac517e709a7028721d882aa82f1` |

The audit checked 102 wheel and 191 sdist members. Required modules include `collaboration_policy.py`, `workflow.py`, `agreement_usage.py`, `team_workflow.py`, service/MCP/Git integration, updated collaboration JavaScript and bundled Skills/protocols. A retained extraction was imported in a fresh `python -I` process; it verified resources, instantiated the shared service on a private smoke database and exercised the five new registrations plus workflow snapshot/brief. Existing setuptools license-metadata and namespace/package-data warnings remain; checked resources are present. Old artifacts were not removed.

## Unified review corrections

- A large task list could consume the entire workflow projection and hide all pending questions/decisions. A 57-task regression reproduced the failure. The bounded response now samples each nonempty category, prioritizing pending requests and agreement changes, while retaining totals/truncation and the byte budget. Focused brief pagination order is unchanged.
- A dependency read fact disappeared when successful resolution incremented the dependency revision. Read evidence now retains its recorded revision, epoch, session and time separately from `currently_valid`; closure or historical routing makes it invalid for a new transition without erasing the observation. Read-resolve-reopen tests cover this distinction.

Both fixes were red before implementation and passed their 56-test affected suite, followed by the final 124-test integration run. No repeated per-task approval/review gate was added after the user's sequencing correction.

## External gates not exercised

- Actual native agents completing ordinary development goals without tool-name prompting, with file-derived answers and observable requester implementation effects.
- Two independent people on their own devices, sessions and networks accepting the experience; same-maintainer, fixture and loopback evidence do not satisfy this gate.
- New cross-device outage/wake/recovery combinations, every harness/platform and production latency/cost measurements.
- Publishing, deployment, production data migration, or organization-wide approval of new native hooks.

No credentials, raw native transcripts, private profiles or test databases are committed. The feature branch and its ignored worktree are retained for subsequent real-user acceptance and release work.
