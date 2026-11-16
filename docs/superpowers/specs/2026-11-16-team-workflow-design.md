# Reliable collaboration between teammates' own agents

Date: 2026-11-16. Status: first implementation and automated verification complete; external native/two-user acceptance remains unperformed.

## Approved outcome and requirements

The user approved all ten recommendations, with multiple people using their own agents as the primary scenario. This is an additive improvement to the shared coordination core, P2P bridge and existing workbench. It does not require a prescribed team workflow or replace native development tools.

| ID | Requirement | Observable acceptance |
| --- | --- | --- |
| R1 | Evaluate ordinary development goals without naming tools | A retained scenario suite gives task goals, records reminders, tool calls, replies and actual answer consumption separately; fixture/protocol results cannot count as model acceptance. |
| R2 | Consistent daily collaboration instructions | HTTP MCP, P2P bridge and Git adapter use a shared policy covering startup, blocker, replies and completion; Skills explain it. |
| R3 | Shorter question and reply paths | A question can target a unique task owner by task or scope; ambiguity and no owner return explicit results without silent delivery. Sent-request replies have an explicit, paginated read operation. |
| R4 | Task-focused context and execution routing | A bounded work brief prioritizes the current task, direct dependencies, relevant agreements and changes. Routing uses declared task responsibility and session/epoch evidence, never inferred private transcripts. |
| R5 | Explain waits and support recovery | Request lifecycle facts, freshness, pending replies and actionable recovery hints remain distinct. Reopening a session can retrieve outstanding work without resolving it. |
| R6 | First useful two-person collaboration | An onboarding projection shows identity/session evidence, addressed question, recipient read/reply and requester consumption as distinct milestones. |
| R7 | Responsibility-based teammate discovery | Owner lookup uses existing explicit task scopes; unique, ambiguous, unassigned and not-found cases are handled, with reassignments governed by current task state. |
| R8 | Durable asynchronous work | Questions and replies persist across client/session restart. Waiting items are visible; other independent work can continue. Wake remains optional and budgeted. |
| R9 | Versioned shared agreements and impact | Task execution can explicitly record reliance on an approved contract version; a newer approved version is surfaced as an update requiring review. Drafts never replace effective decisions. |
| R10 | Clear human decision work | Pending agreements, handoffs, unassigned responsibilities and delivery proposals are summarized with impact and references to existing authorized actions. Ordinary agent discovery does not acquire human mutation tools. |

## Architecture

Keep existing message, dependency, task ownership, contract, delivery, event and identity stores authoritative. Add a small workflow composition layer rather than duplicate those domain rules. New APIs are additive and exposed through the common operation schema so the HTTP service, local Git adapter and P2P bridge agree.

1. `collaboration_policy.py` provides the shared MCP instructions plus transport-specific notes. External message bodies remain untrusted data; guidance does not grant authorization.
2. `workflow.py` composes owner questions, sent-reply reading and a bounded task-focused brief. Owner questions reuse explicit task dependencies when a source task is supplied, retaining transactional rerouting, read-before-confirmation and ownership epochs. Member-level questions use addressed ordinary requests and disclose their fixed-recipient semantics.
3. `agreement_usage.py` stores append-preserving, epoch-scoped task reliance on approved versions, and exposes current/changed agreement projections. It does not approve contracts or accept changes automatically.
4. `team_workflow.py` projects request lifecycle facts, onboarding milestones and authorized human decision summaries from current shared state. Its reads do not manufacture receipts or model consumption.
5. A retained native workflow evaluation module contains tool-free user goals and evidence evaluation. It reports synthetic evidence, native execution and two-independent-user acceptance separately.

## Proposed API contracts

- `ask_owner(request_key, body, target_task_id?, scope?, source_task_id?, expected_revision?, context='', session_key?, ownership_epoch?)`: exactly one target selector. Resolve the selector using existing owner lookup. Return candidates on ambiguity, and explicit not-found/unassigned states without sending an unaddressed ordinary message. With a source task, call the existing dependency creation path, preserve its idempotency and return dependency/request identifiers; with no source, address the current unique owner explicitly and return the target revision so the fixed recipient is visible.
- `read_replies(after_id=0, limit=20, task_id?)`: a reply-id cursor reads only replies to the authenticated sender's requests. Include request/route metadata and distinguish current from historical dependency replies. Explicit reading records the exact reply id for this member, not resolution, approval or a dependency read receipt. Snapshot/brief calls never call this operation implicitly.
- `work_brief(task_id?, session_key?, ownership_epoch?, after_cursor?, limit=20)`: authenticate, validate supplied task/session ownership, then return relevant tasks, current dependencies, requests/replies, agreement updates and allowed next-step metadata within a fixed byte budget. An opaque cursor is bound to project/member/focus and content versions; changing focus or an invalid cursor produces a reset. Return the complete current identifiers and explicit truncation indicators so a bounded brief cannot imply completeness.
- `record_agreement_use(task_id, contract_id, version, session_key?, ownership_epoch?)`: record that this active task execution relies on an approved version. New records retain old evidence. Reject draft, foreign-room or retired-execution input. Reading a new version does not accept it.
- `read_workflow(task_id?)`: project shared request states, onboarding milestones, relevant agreement impacts and human decisions. Human decisions contain operation names/references and expected revisions for display, not automatic execution authority. Server-produced actions use an allowlist and never parse message text into executable instructions.

## State, permissions and failure behavior

- A delivered request, recorded read, acknowledgement, reply, explicit requester reply-read and resolution are different facts. No status claims that the model understood content without behavioral evidence.
- New receipt/reliance tables are additive. No deletion, destructive migration, credential rotation or modification of personal agent configuration is part of this work.
- Scope ambiguities do not guess an owner. Project authorization is checked before every operation. Task-bound writes and context use the existing session/ownership-epoch model.
- Historical dependency routes remain visible as history; stale replies cannot satisfy the current dependency. Existing domain methods remain the only mutation paths for dependencies and decisions.
- Wait state and session freshness are separate dimensions. Missing evidence stays unknown. No promise of idle wake for unsupported native tools.
- Reconnect/reopen uses durable server state. Reminders are guidance, not unsolicited external messages or new automatic model turns. Existing wake quotas remain unchanged.
- Private profiles, credentials, raw native transcripts and per-run databases remain in ignored local storage. Evaluation reports store only bounded aggregate conclusions in maintained documentation.

## Interface and onboarding

Extend the existing collaboration panel with compact first-collaboration milestones, current wait reasons and a human-decision list. Preserve existing typography, navigation, detail actions, project-switch isolation and focused inputs. Use safe text DOM only. Where existing task/contract/handoff actions are available, link to them rather than invent another mutation interface. The P2P host board remains read-only.

## Evaluation and completion boundaries

Automated coverage includes domain, real authenticated HTTP/MCP, bridge policy, focused context cursors, room isolation, scope ambiguity, stale owner/epoch, ordinary and dependency reply paths, agreement version change, durable reopen and safe workbench rendering.

The native scenario goals never name Coopagents tool calls. A sender and recipient receive separate goals and evidence files. A report distinguishes protocol success, actual native model calls, file-derived answers, requester consumption, reminders, call count and elapsed times. Two independent people/devices/networks must explicitly provide their evidence; same-machine, fixtures and one-maintainer remote runs do not meet that gate.

## Staged delivery

1. Commit this design and the implementation plan.
2. Implement tool-free workflow evaluation and shared collaboration policy.
3. Implement owner questions, reply reading, focused briefs and recovery evidence.
4. Implement agreement reliance, shared impacts, onboarding and human decisions.
5. Integrate the existing collaboration panel, guides and API/bridge regressions.
6. Run review, full feasible regressions and packaging; commit an acceptance report separating implemented behavior from external validation still required.
