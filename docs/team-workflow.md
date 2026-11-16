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

- A unique target persists the owner question with or without a source task. An owned target gets an addressed request. With a source task, the question reuses a task dependency; without a source, `routing` is `task_owner`. The result retains `dependency`, `request`, `target`, `routing` and `target_changed`.
- A unique unassigned target queues the durable question with no current request. With a source task, its dependency is queued too. When the selected target gains an owner, routing delivers a current addressed request. Retry the same key and same payload to recover that current route; absence of a request does not mean the question was lost.
- An initially ambiguous or absent scope creates no question, dependency or message and returns its explicit state and available candidates. Select a specific declared task rather than guessing an owner. Once a question has selected its target task, scope text is not reinterpreted on retry to silently select a different task.
- Claim, release, handoff, cancellation and reopening of the selected target update owner-question routing in the task transaction. Release leaves the question waiting for an owner; target cancellation reports `target_cancelled`. Historical messages, replies and read evidence remain retained, but old routes cannot be acknowledged, answered or resolved as the current route. Existing source-task dependency authority and lifecycle rules remain in force.

Routing metadata includes `routing_state`, `current_request_id`, `route_version` and `route`. The `route` object identifies the request's current/historical state and selected target; it is null while queued without a delivered route. Use these identifiers to refresh current responsibility instead of treating an earlier recipient or reply as current. A response already explicitly resolved is `closed`; rerouting does not silently adopt a historical answer. None of these states proves delivery to a running model or model comprehension.

For an owner question without a source task, omit the source fields:

```json
{"request_key":"api-logging-question-1","target_task_id":27,"body":"Which logging format should I use?"}
```

This persists a `task_owner` question and follows the selected task's current responsibility, including waiting without a request while unassigned. Retry returns its current request, which can differ from a historical request after a handoff. It does not select a new target task. Reusing a saved key with a different payload conflicts. A task-bound retry still validates current source authority before returning saved results.

Direct `send_request` remains the way to choose a fixed recipient by `receiver_member_id`; it does not follow task ownership changes:

```json
{"request_key":"question-for-this-person-1","receiver_member_id":"specific-member-id","context_version":1,"body":"Can you explain the logging example you shared?"}
```

That fixed recipient is deliberate personal addressing, separate from `ask_owner`. Omitting its receiver still means no addressed delivery until the existing authorized assignment path is used. This does not make an unaddressed direct request an owner-following question.

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

The evidence text is member-supplied evidence, not server verification of a private source file. Direct requests and owner questions without a source task use `reply(request_id, request_key, context_version, body, evidence)` with the current request's `context_version`. For owner questions, refresh the current request ID and route first; historical routes reject reply, acknowledgement and resolution. Linked dependency requests reject the ordinary reply/resolve paths.

`read_replies` explicitly reads replies to requests sent by the authenticated member. It uses an exclusive numeric **reply-ID** cursor, not the inbox delivery cursor:

```json
{"after_id":0,"limit":20,"task_id":12}
```

The response contains `replies`, `next_cursor`, `has_more` and `model_consumption_proven: false`. Continue after `next_cursor` while `has_more` is true. Optional `task_id` filters the request's task association: a dependency request is associated with its source task; an owner question without a source task is associated with its target task. Reset `after_id` when starting a different task query. Replies identify ordinary direct requests or current, closed and historical owner-question/dependency routes. A historical answer is retained evidence, not an answer on the current route. Each returned reply gets its own durable requester read record; reading an old route or an earlier answer does not mark a newer answer read, select a recipient or confirm the current route. Replies from another session of the same member are included.

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

To continue, send `after_cursor` with the same task, binding and limit. A batch is frozen while `has_more` is true: finish it before checking for later changes. Store the final `cursor` too. Checking it again compares the completed baseline with current relevant source records. An unchanged baseline returns an empty page with `unchanged: true`; changed records arrive as a real delta.

- Each item has a stable `item_key`. Delta items use `change: "added"`, `"updated"` or `"removed"`; removed items are tombstones, not instructions to delete source data or assume a dependency was satisfied. Decision payloads retain their nested shape, and queued `owner_question` records use their genuine question identity rather than fabricated message IDs.
- New changes during pagination do not erase the frozen batch. They are compared after its final cursor, so records are not skipped when the source changes between pages.
- Opaque cursor state is retained in a bounded private cache and binds project, member, task focus, logical execution, ownership epoch and page limit. Invalid, missing, expired or differently scoped state requests an explicit full resync, with `reset`, `resync` and `reset_reason`; rebuild the local baseline instead of appending that new full snapshot as a delta.
- Complete record hashes drive changes even when displayed bodies are excerpted. Continue through all pages, and use the existing detail tools for original content. Relevant unread member-level questions/answers remain recoverable when their source execution cannot be determined; known unrelated task rows are excluded.

Authority is checked before cursor reuse. Retired execution input fails even with an old valid cursor. A client restart can read outstanding work from the same retained service database; simply reopening or reading does not resolve it. All workflow/brief/snapshot reads leave inbox, reply-read and dependency-confirmation evidence untouched. The separate Git `repo_checkpoint` operation includes an explicit inbox read; do not confuse it with the read-only `checkpoint` brief.

### Route pending work to a current native conversation

`register_session` can link a current task execution to an actual native conversation with optional `native_session_id`. The existing `session_key` remains the logical execution key used by task authority; `ownership_epoch` is still required where the task binding requires it. This alias is routing metadata, not a new grant of task ownership. A registration with no task does not infer ownership or select a task merely because one exists for the member.

The P2P bridge only supplements the native alias when the native process actually supplies it and the remote schema advertises the field. On a successful claim it can report the same authorized execution through the existing registration operation. An absent native identifier or an older server keeps the existing member-level fallback; no conversation is guessed from a display name, a tool name or teammate text.

An opted-in watcher reports its native session through internal authenticated `session_presence`, using a short lease (90 seconds by default) and explicit watcher observations. This operation is not an extra model-facing MCP tool. `wake_digest(session_key=<native conversation>)` returns only that session's directed work and member-level fallback work. An omitted key does not consume work reserved for another currently eligible conversation. Items include `delivery_scope`, `target_session_key`, `execution_target` and a generation-bound `delivery_key`, without message bodies or read receipts.

Incoming dependencies and responsibility questions use the actual target execution; outgoing dependency answers use the source execution. When there is no reliable task association, or the alias/credential/lease/ownership epoch is no longer current, pending work falls back to the member. A stopped or expired route receives a different delivery key so a prior notification cannot permanently swallow a needed recovery notification. Another watcher cannot baseline or claim a different session's targeted item. Same-member cross-session answers are supported, and already explicitly read answers are not fresh wake items.

Watcher presence, a successful alias report and an invalidation never prove model consumption. A normal wake return does not mean the native conversation exited; its short lease is allowed to expire naturally. Only a real observed owner-process exit or explicit stop is reported as stopped. No personal hook installation, native trust, task approval or sandbox settings are changed by this routing code. Actual native/cross-device validation remains deferred in this code-only pass.

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
