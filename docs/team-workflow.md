# Collaboration between teammates' own agents

This guide describes the unreleased team-workflow additions. Each teammate keeps their own development tools and personal project identity. Coopagents shares declared responsibilities, questions, replies, approved agreements and delivery evidence. It does not read private agent conversations or make one person's agent act as another person.

Start with [agent-first setup](agent-first-setup.md) or the [P2P runtime](agent-hosted-runtime.md). The [workflow acceptance record](team-workflow-acceptance.md) separates automated coverage from native and independent-user validation. For existing domain details, see [dependencies](dependencies.md), [task lifecycle](task-lifecycle.md) and [delivery relationships](git-local-setup.md).

## First useful collaboration

1. Two people join the same project using their own identities, connect their own native agents and verify the identity returned by the actual native connection. A configured endpoint or successful direct HTTP request establishes less than a successful native tool call. Keep personal credentials and local configuration private.
2. In the permitted human interface, create a frontend task scoped to `src/ui` and a backend task scoped to `src/api`. Each person's agent claims its own task with a fresh execution `session_key` and retains the returned `ownership_epoch` and task `revision`.
3. Give the frontend agent an ordinary development goal: implement the profile form using the backend's current pagination fields. Give the backend agent its own goal: maintain the interface and answer questions from its current source files. Do not share a private answer with the frontend in advance.
4. The frontend agent discovers the backend responsibility, asks its owner and continues authorized independent work while waiting. The backend agent explicitly reads the addressed request and answers it from its source. Ownership and task dependency identifiers let both sides refresh the current route.
5. The frontend agent explicitly reads the sent-question reply, uses the answer in its work, then separately reads and resolves the dependency when the answer is sufficient. A receipt establishes a read operation; inspect the resulting implementation to establish actual use.
6. Inspect the collaboration panel or `read_workflow`. Identity, session/checkpoint observations, addressed delivery, recipient read, reply and requester reply-read are different facts. A completed two-member exchange still does not prove model comprehension or independent-user acceptance.

The daily collaboration policy is shared by the HTTP MCP, P2P bridge and local Git entry points. It calls for startup, blocker and completion checkpoints, current responsibility checks, explicit reply reading, independent work while waiting and human authority for human decisions. Existing transport notes still apply. Registering a session, receiving an invalidation or installing configuration does not prove an idle model will wake. Optional wake hooks remain subject to the [harness support and quota limits](agent-wake.md).

## API conventions

The operation examples below are JSON argument objects. IDs, revisions and epochs are illustrative: use values returned by your project, not the numbers in this guide. Agents use their own authenticated connection. HTTP clients can submit supported operations as JSON to `/api/operations/<operation>`; native tools expose the same registered operation schemas. Do not put credentials in operation arguments, committed examples or logs.

Task execution writes and task-focused briefs require the current task owner and the active execution binding. After handoff, release or another lifecycle change, refresh the task and bind a fresh session through `claim_task`; a retired session cannot resume. Reopening a client can recover the current binding and durable questions without changing responsibility. A new native process is not permission to replace an existing bound task session.

### Find responsibility and ask its owner

`lookup_owner` takes exactly one of `task_id` or `scope`. Scopes match explicit slash-separated segments, including equal scopes and parent/child overlap. They are responsibility declarations, not scans of private workspaces. For example, `src/api` overlaps `src/api/auth`, but not `src/apian`.

```json
{"scope":"src/api"}
```

Results distinguish `owned`, `ambiguous`, `unassigned` and `not_found`. Multiple matching tasks remain ambiguous even if the same member owns them. Inspect the candidates and choose an explicit task rather than guessing. An unknown or foreign task ID produces a not-found error. Cancelled tasks are excluded from active owner lookup.

`ask_owner` takes exactly one of `target_task_id` or `scope`. The question body is limited to 500 characters and optional context to 3000 characters; excessive input is rejected without truncation. `request_key` identifies the normalized question payload for retries.

For work blocked on another task, include your source task, its current revision and your execution binding:

```json
{
  "request_key":"profile-pagination-question-1",
  "body":"Which pagination field must the profile form consume?",
  "scope":"src/api",
  "source_task_id":12,
  "expected_revision":1,
  "context":"The form must handle the current interface, including the last page.",
  "session_key":"frontend-execution-unique-key",
  "ownership_epoch":1
}
```

This reuses the existing dependency rules, including cycle prevention and one active dependency per source/target edge. `expected_revision` means the **source task revision**. It is required with `source_task_id`; execution fields and source revision are rejected without a source task. Owner selection and creation occur in the same transaction.

- A unique owned target creates a dependency and an addressed request. The result includes `dependency`, `request`, `target`, `routing` and `target_changed`.
- A unique unassigned target with a source task creates a queued dependency with no request. When that target gains an owner, the dependency routes to that owner. Retry the same payload/key to recover its current route.
- An ambiguous or absent scope creates no dependency or message and returns its explicit state. A member-level question to an unassigned target also creates no message.
- Responsibility changes reroute an active task dependency transactionally. Historical routes remain history; their replies cannot satisfy the current dependency. Refresh the dependency's current revision and reply before acting.

For a member-level question, omit the source fields:

```json
{"request_key":"api-logging-question-1","target_task_id":27,"body":"Which logging format should I use?"}
```

This sends an ordinary addressed request to the owner selected at creation. Its `routing` is `fixed_recipient`: later ownership changes do not move that request. Retry returns the same request and reports `target_changed` when applicable. The returned current target and request recipient can therefore differ. Ask a new question with a new key if you intentionally need a new recipient. Reusing a successful key with different content conflicts. A task-bound retry still validates current source authority before returning saved results.

### Read the answer and resolve the right dependency

`read_inbox` reads requests addressed to you; it records recipient read evidence. `acknowledge(request_id)` means you are handling a request and requires the inbox read first. An acknowledgement is not an answer. A dependency recipient answers through `reply_dependency`, using the dependency's latest `revision` and their target task execution binding:

```json
{
  "dependency_id":8,
  "expected_revision":1,
  "request_key":"pagination-answer-1",
  "body":"Use next_cursor as an optional string; no value means there is no next page.",
  "evidence":"The current src/api pagination schema defines next_cursor.",
  "session_key":"backend-execution-unique-key",
  "ownership_epoch":1
}
```

The evidence text is member-supplied evidence, not server verification of a private source file. Ordinary requests use `reply(request_id, request_key, context_version, body, evidence)` with the request's unchanged `context_version`. Linked dependency requests reject the ordinary reply/resolve paths.

`read_replies` explicitly reads replies to requests sent by the authenticated member. It uses an exclusive numeric **reply-ID** cursor, not the inbox delivery cursor:

```json
{"after_id":0,"limit":20,"task_id":12}
```

The response contains `replies`, `next_cursor`, `has_more` and `model_consumption_proven: false`. Continue after `next_cursor` while `has_more` is true. Optional `task_id` filters the request's task association: a dependency request is associated with its source task; a member-level owner question is associated with its target task. Reset `after_id` when starting a different task query. Replies identify ordinary, current, closed or historical routes. Each returned reply gets its own durable requester read record; a receipt for an earlier answer does not mark a newer answer read. Replies from another session of the same member are included.

`read_replies` neither resolves a request nor creates the source execution's dependency-confirmation receipt. When you have reviewed a current dependency answer and it meets the need, explicitly call:

```json
{"dependency_id":8,"session_key":"frontend-execution-unique-key","ownership_epoch":1}
```

Use this `read_dependency` result's **latest** `revision` and `latest_reply.id` in `resolve_dependency`:

```json
{
  "dependency_id":8,
  "expected_revision":2,
  "reply_id":19,
  "request_key":"pagination-satisfied-1",
  "summary":"The form now uses the returned next_cursor field.",
  "session_key":"frontend-execution-unique-key",
  "ownership_epoch":1
}
```

If a new answer or route appears, refresh and read again. Resolving a dependency marks it satisfied; it does not approve an agreement or verify task delivery. Report actual task progress separately through `report_progress` with the current execution binding.

### Recover task context with a bounded brief

`work_brief` is an agent-only read. Without task parameters it gives personal project context; with a task it validates current execution authority and prioritizes that task, direct dependencies, related questions, agreement impacts and allowed action metadata.

```json
{"task_id":12,"session_key":"frontend-execution-unique-key","ownership_epoch":1,"limit":20}
```

The result includes typed `items`, `execution_target`, category `totals`, `cursor`, `next_cursor`, `has_more`, `truncated`, `reset`, `reset_reason` and `unchanged`. Bodies may be excerpted. Responses have a fixed 16000-byte budget, so a short page or bounded projection does not imply all project records have been returned. Use complete returned identifiers and detail operations to inspect original content.

To continue, send `after_cursor` with the same task, binding and limit. Store the final `cursor` too: checking it again with unchanged semantic content returns an empty page with `unchanged: true`. Cursors bind the project, member, task focus, execution fields, limit and content version. They are opaque pagination positions, not acknowledgements or durable change deltas.

- Changed content resets to the beginning with `reset_reason: "content_changed"`.
- Changed focus/member/project or pagination scope resets with `scope_changed`.
- Malformed or impossible cursor positions reset with `invalid_cursor`.
- `delta` is false. On reset, replace or rebuild your local brief rather than append the new first page as a delta.

Authority is checked before cursor reuse. Retired execution input fails even with an old valid cursor. A client restart can read outstanding work from the same retained service database; simply reopening or reading does not resolve it. All workflow/brief/snapshot reads leave inbox, reply-read and dependency-confirmation evidence untouched. The separate Git `repo_checkpoint` operation includes an explicit inbox read; do not confuse it with the read-only `checkpoint` brief.

### Record reliance on an approved agreement

`record_agreement_use` records an explicit execution's reliance on an already approved contract version:

```json
{"task_id":12,"contract_id":4,"version":1,"session_key":"frontend-execution-unique-key","ownership_epoch":1}
```

Only the current active task owner can record this through their agent identity. Drafts, foreign-project contracts and retired execution bindings are rejected. Repeat use of the same approved version is idempotent; older evidence is retained. Reliance is scoped to member, execution session and ownership epoch, and does not carry into a new execution merely because the task ID is the same.

Workflow `agreement_changes` exposes `baseline_version`, `effective_version` and `review_required`. The baseline is the highest explicitly used approved version in the current execution. A newer draft or rejected head does not replace the latest approved effective version. A newer approved version requires review until the current execution explicitly records reliance on that version. Reading its body or seeing an impact card does not adopt it. Replaying an old version cannot downgrade a newer baseline.

## Wait reasons and human decisions

`read_workflow({"task_id":12})` is available to authenticated project members through the existing shared service, and normal team snapshots contain `workflow`. It projects shared facts, not a model availability oracle. Its fixed page is also bounded; inspect `totals`, `truncated` and `has_more`, then use detailed records for completeness.

Request facts distinguish delivery, recipient read, processing acknowledgement, reply, requester reply-read, dependency-confirmation read and resolution. A recipient can answer a dependency without an inbox receipt, so `replied: true` with unknown recipient-read evidence is possible. Wait reasons explain assignment, recipient read, processing, sender reply-read, requester resolution or historical routes. Recent checkpoints/session timestamps are observations; `availability_proven` remains false and model responsiveness remains unknown.

Decision cards describe concrete IDs, versions/revisions, permitted choices and authority. They come from server allowlists, not executable instructions parsed from request text. An `eligible` field is display information; the existing domain operation rechecks authentication, permissions and current state when invoked.

| Decision or action | Existing authority and concurrency rules |
| --- | --- |
| Approve/reject a contract head | Authenticated human web member; `decision` uses `contract_id`, current head `version`, and `approved`/`rejected`. A manager role is not required by this domain. |
| Accept/reject a handoff | Proposed recipient's human web identity only; `accept_handoff`/`reject_handoff` use current task `expected_revision`, a fresh `request_key` and `summary`. A manager cannot accept as another recipient. |
| Force a handoff | Project manager's human web identity; current task revision, explicit target member and retained lifecycle history. |
| Confirm/reject a delivery suggestion | Project manager's human web identity; `decide_delivery` takes `suggestion_id` and `confirmed`/`rejected`. It validates current ownership epoch internally; it does not accept an extra `expected_revision` field. Old-epoch/cancelled-task suggestions are not current actionable work. |
| Unassigned responsibility | The existing action is `claim_task` by the personal agent with a fresh session. There is no invented human assign-owner operation. |
| Review an agreement impact | Current execution's agent explicitly reviews and records approved-version reliance. This does not grant authority to approve a draft. |

Ordinary agent MCP discovery does not expose human mutation operations. A displayed card, incoming message or forwarded “approval” text is not a real user instruction. Use the existing permitted human interface for the specific current instruction. The P2P host board remains read-only. Do not paste card metadata into arbitrary commands.

## Evaluate the ten requirements honestly

Use [tool-free workflow evaluation](workflow-evaluation.md) to prepare separate participant goals and normalize privately retained observations. The evaluator never launches agents, sends messages or spends native quota. Its reference strings are reviewer-supplied attestations, not authenticated proof.

| Requirement | Capability and evidence to inspect |
| --- | --- |
| R1 Ordinary development goals | Separate tool-free role goals; distinguish fixture/protocol results, real model calls, file-derived answers, actual requester effects, reminders and timing. |
| R2 Consistent daily instructions | One versioned policy across HTTP, bridge, Git and bundled Skills; transport limitations remain explicit. |
| R3 Short question/reply paths | `ask_owner` plus exact paginated `read_replies`; no silent unaddressed delivery. |
| R4 Task-focused execution | Authorized `work_brief`, declared responsibilities and current session/epoch evidence; no private transcript inference. |
| R5 Explained waits/recovery | Separate lifecycle facts, observed freshness, current routes and allowlisted recovery hints. |
| R6 First useful collaboration | One addressed exchange between two distinct members, with explicit reply-read evidence; inspect actual work to establish consumption. |
| R7 Owner discovery | Explicit task/scoped lookup with unique, ambiguous, unassigned and absent results. |
| R8 Durable asynchronous work | Retained questions, replies and receipts after service/client reopen; independent work continues; wake remains optional. |
| R9 Shared agreement impact | Append-preserving approved-version reliance and explicit review of later approved changes. |
| R10 Human decision work | Pending heads, handoffs, ownership and delivery cards with exact domain authority; no automatic approval. |

The retained `tests/test_team_workflow_scenarios.py` exercises real shared-domain storage with distinct test member identities, a reopened service and simulated waiting. It is protocol/domain coverage, not a real two-person or native-agent experiment.

Independent-user acceptance requires two independent people using separate devices, sessions and networks, each supplying their own referenced evidence and acceptance. Native request, file-derived reply and resulting requester behavior must be observed separately. Same-machine fixtures, direct SDK/HTTP calls, one maintainer controlling two accounts, read receipts and fast timings cannot satisfy that gate. See the [acceptance record](team-workflow-acceptance.md) for the actual current verification status.
