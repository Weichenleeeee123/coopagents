# Team workflow acceptance — in progress

Date: 2026-11-16. Branch: `codex/team-workflow-implementation`.

This is an initial evidence record while the approved ten-point implementation is still being integrated. It is not a release or native/two-person acceptance claim. The final source commit and integrated verification results are pending. Scope is defined by the [approved design](superpowers/specs/2026-11-16-team-workflow-design.md) and explained in the [practical workflow guide](team-workflow.md).

## Checks performed for this draft

Commands ran from the dedicated team-workflow worktree with its ignored `.local/pythonpath` junction prepended to `PYTHONPATH`, using the original verified environment's interpreter. Import verification resolved `coopagents.__file__` through this worktree's `.local/pythonpath/coopagents/__init__.py` rather than another checkout.

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location) '.local/pythonpath')
& 'C:/Users/Weichen Li/Documents/Codex/2026-10-10/wo-zhe/.venv/Scripts/python.exe' -c "import coopagents; print(coopagents.__file__)"
& 'C:/Users/Weichen Li/Documents/Codex/2026-10-10/wo-zhe/.venv/Scripts/python.exe' -m unittest discover -s tests -p 'test_team_workflow_scenarios.py' -v
```

The scenario command passed **3 tests**. These use the actual `CoordinationService` and SQLite domain stores with fresh UUID-named retained databases under ignored `.local/test-evidence/`. They do not mock business behavior, contact a live project, start native agents or delete evidence.

The same scenario command was rerun after writing the guides and again passed all 3 tests. A read-only local Markdown-link check found every relative link in the two new guides present. `git diff --check -- docs/README.md docs/team-workflow.md docs/team-workflow-acceptance.md tests/test_team_workflow_scenarios.py` reported no whitespace errors.

| Automated scenario | Observed result |
| --- | --- |
| Frontend/backend question and recovery | Source-task owner question is durable; an unanswered request remains pending; a newly constructed service on the same database recovers it and the backend answers through the current dependency route. |
| Explicit reads, confirmation and progress | Sent-reply reading records the exact reply without satisfying the dependency; resolution fails before the separate dependency read; reading and resolving the latest revision/reply succeeds, followed by an authorized progress report. |
| Agreement version change | Approved v1 reliance is explicit; draft v2 leaves v1 effective; approved v2 projects review required; explicit current-execution v2 reliance clears that impact. |
| Human handoff boundary | A pending handoff card is eligible for the proposed recipient's web identity; the recipient's agent cannot accept it and the pending decision remains. |
| Discovery and route semantics | Overlapping scopes return ambiguity without a message; an unassigned target queues a source dependency and routes after claim; a member-level question retains its original recipient across a target handoff. |
| Project isolation and read evidence | Other-room task/request/reply markers do not appear in the local workflow; foreign IDs fail; workflow/brief/snapshot peeks create no local inbox, reply-read or dependency-confirmation receipts. |

“Offline” here means the test deliberately performs no backend action before reopening the service. It is not a network outage, process wake or native-session recovery test. Test credentials represent distinct synthetic members; they do not represent two independent people. The supplied answer/evidence strings are fixtures, not observed native file-derived answers.

## Ten-point implementation/evidence matrix

The entries below identify evidence locations rather than declare final completion. Other workers are integrating source, API exposure and UI in the shared worktree; their final results must be added after the unified verification run.

| Requirement | Retained implementation/evidence location | Final verification status |
| --- | --- | --- |
| R1 Tool-free evaluation | `experiments/agent-integration/workflow_evaluation.py`; [evaluation guide](workflow-evaluation.md) | Final evaluator run pending in this record; native observations absent. |
| R2 Shared daily instructions | `src/collaboration_policy.py`, HTTP/bridge/Git entry points, bundled Skills | Integrated policy/transport regression results pending. |
| R3 Short owner/reply paths | `src/workflow.py`, `tests/test_workflow.py`, full-flow scenarios | Three full-flow scenarios passed; complete API/MCP/Git results pending. |
| R4 Focused context/routing | `src/team_workflow.py`, `tests/test_team_workflow.py` | Full-flow content-reset behavior passed; full cursor/authority suite pending in this record. |
| R5 Wait explanations/recovery | Workflow lifecycle projections and full-flow service reopen | Pending question, recovery and read distinctions passed; UI verification pending. |
| R6 First useful collaboration | Workflow onboarding projection, separate participant evaluation goals | Synthetic two-member exchange observed; actual model consumption/two-user acceptance pending. |
| R7 Responsibility discovery | Existing owner lookup plus `ask_owner` | Ambiguous, queued and fixed-recipient route scenarios passed; integrated transport coverage pending. |
| R8 Durable asynchronous work | Existing SQLite stores plus additive workflow receipts | Same-database service reopen passed; independent network and harness wake behavior untested here. |
| R9 Agreement reliance/impact | `src/agreement_usage.py` and agreement projections | v1/draft-v2/approved-v2/explicit-use-v2 full flow passed; broader suite pending in this record. |
| R10 Human decision work | Workflow decision projections and existing domain authorization | Pending handoff/agent rejection passed; full decision/UI authority coverage pending. |

## Remaining validation gates

- Complete all ten implementation points, then run the requested unified review; no separate new per-stage approval gate is implied.
- Run and record the final full Python suite, integration experiments and required JavaScript regressions against the final source state.
- Verify real authenticated HTTP/MCP and Git forwarding for all new operations in the final integration.
- Inspect the real synthetic-data workbench at desktop and mobile widths, including project switching, focused input preservation, safe text rendering and existing detail actions.
- Build and inspect distributions for new modules/Skills and absence of private state; perform final whitespace and no-tracked-file-deletion checks.
- Record final source commit, exact commands/counts, packaging results and any environment limits. This draft's 3-test result does not stand in for those checks.
- Run separately authorized native experiments with actual native tool discovery/calls, file-derived answers and observable requester implementation effects. No such run was performed for this draft.
- Obtain evidence and explicit acceptance from two independent people/devices/sessions/networks. Fixture/protocol scores and one-maintainer tests cannot satisfy this external gate.

No credentials, raw native transcripts, private profiles or test databases belong in this report or Git. Retain private evidence under ignored local paths. No files were deleted for these scenarios.
