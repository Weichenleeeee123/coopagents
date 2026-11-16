# Tool-free workflow evaluation

There are two separate paths. The original `workflow_evaluation.py` prepares goals and scores reviewer-supplied normalized observations. The new `workflow_native_runner.py` actually starts native coding-agent processes against an authenticated local MCP service, captures their private event streams, and checks the resulting implementation. Neither path certifies two independent people by itself. The strict foundation completion ledger is in [foundation completion](superpowers/plans/2026-11-16-foundation-completion.md).

## Real native execution

Native runs spend the selected native account's model quota. They require an explicit execution switch, use newly created private profiles, preserve the existing selected model/provider, and never edit the user's live configuration. Run from the feature checkout using a verified interpreter whose `coopagents.__file__` belongs to that checkout:

```text
python experiments/agent-integration/workflow_native_runner.py run --execute-native --output .local/test-evidence/<fresh-run> --requester codex --responder claude
```

Use `--codex <executable>` and `--claude <executable>` when the native executables are not on PATH. On Windows, use the actual executable or `.cmd` entry point rather than the PowerShell `.ps1` shim. `--requester codex --responder codex` is a same-harness experiment, not cross-harness acceptance. A selected harness that fails preflight must be reported separately; changing to another model does not repair its result. `--timeout` bounds each native turn. `--scenario` and `--arm` allow an explicitly partial smoke run; partial coverage never completes the foundation gate.

The original five foundational scenarios are `frontend-backend`, `three-member-routing`, `reply-continuation`, `session-reopen` and `teammate-unavailable`. Each uses separate role projects. Only the backend role receives a generated field definition. The requester starts with an unfinished payload builder and independent work; its prompt contains neither the field nor MCP tool names/call order. A bounded verifier checks two different input names against the private oracle, separately checks independent progress, and records source hashes. Correct code alone does not prove collaboration: the audit also requires native structured request/reply calls linked to real stored rows, a source-file read, a later answer read, and an implementation effect after the waiting-stage check. An answer observed in requester tool results before the response invalidates that exchange.

The ordinary cases start a real responder worker as soon as a durable question appears, while the requester can still be working. The three-member case retains real task ownership-change history before the evaluated request. The reopen case closes the old worker after an actual question and independent progress exist, creates a genuinely different native conversation, and requires recovery of that outstanding work. The unavailable case holds the responder offline until a real question and independent progress have been observed, then starts it. These are single-machine native scenarios; they do not establish network outage handling, native hook wake-up or separate-device connectivity.

Two paired arms use identical role goals, backend facts, selected models and tool-neutral initialization instructions. The `primitive` arm exposes the existing primitive descriptions. The `composite` arm adds only `ask_owner` and `read_replies`. A scoped evaluation registration adapter filters the real production MCP catalog; it does not copy domain mutations or alter authentication. Both arms deliberately use the same neutral evaluation instructions, so this experiment does not certify the production initialization policy or hooks. Results with different source bytes, configuration, actual native models or case fingerprints are rejected as paired comparisons. Arm order alternates across scenarios. One pair per scenario is an exploratory baseline, not a statistically reliable production success rate.

The owner-question contract now preserves questions for a unique selected task even without a source task, queues them while unassigned and follows owner-question routes after responsibility changes. Initial ambiguity returns candidates and an initially missing scope creates no question. Saved retries keep the selected task and return its current route; old messages/replies remain historical. Direct `send_request` to a specific member keeps its fixed recipient. A changed contract is not retroactive evidence: older fixed-recipient traces cannot validate the new owner-following behavior, and pure schema/mock/text checks are not native acceptance. Native evaluation is paused for the current code-first work; this contract update starts no native processes or service validation.
The harness seeds project/member/task setup, but never sends the evaluated question or answer itself. Native resumes are scheduled with ordinary continuation goals. Report `scheduler_continuation_count` separately from actual `human_reminder_count`: zero manual reminders does not prove autonomous wake-up. The backend answer is not inserted into a requester prompt or hidden requester test. Approval operations and task setup performed by the synthetic harness are not attributed to agents or real human decisions.

Metrics include the routing/answer-use denominators, observed response latencies, all native tool calls, manual reminders, scheduled continuation turns and native-reported input/output/cache tokens. Claude cache-creation tokens are separate from reported input tokens; cache reads are not added again. Missing usage or costs remain `null`. The intentionally closed pre-reopen worker can lack a final usage report; its observed calls remain visible separately from a complete count and its missing tokens are not invented. USD cost is copied only from native billing output; a subscription tool that does not report per-run money is not assigned an invented price or a zero cost. Failed workflow attempts remain in summaries. Quota, timeout, capture failures and effective-policy mismatches stop a suite and retain partial evidence; an unexecuted scenario cannot become a baseline result.

Evidence includes exact goals, native CLI versions, actual native model/session metadata, selected-configuration hashes, source commit/content hashes, timestamped raw events, service snapshots and artifact checks. All such records stay in ignored private `.local/test-evidence/` directories. The native runner requires a fresh output directory and never deletes or overwrites old attempts. Windows profiles explicitly select the ordinary restricted-token backend and verify effective `workspace-write` from the native session record; permission flags alone are not accepted as proof. No permission/trust bypass or global native-setting edit is performed.

Pure helper regressions can run without models or credentials:

```text
python -m unittest discover -s experiments/agent-integration -p 'test_workflow_native_*.py' -v
```

Fixture subprocesses used by these tests are labeled native-free and never count as successful native sessions. A native trace ending successfully means only that the native turn ended; receipts and successful process exits cannot replace the exchange/implementation audit. See [foundation 1 native acceptance](foundation-1-native-acceptance.md) for actual observed runs and remaining gates.

## Supplied normalized scoring

`experiments/agent-integration/workflow_evaluation.py` prepares outcome goals and scores supplied normalized evidence. It does not start a native agent, open a connection, install hooks, send requests or spend model quota. Coordinate any real native experiment separately. Retain evidence under ignored `.local/test-evidence/`; never commit credentials, profiles, raw conversations or raw experiment logs.

From the repository root, using the verified environment's Python:

```text
python experiments/agent-integration/workflow_evaluation.py prepare
python experiments/agent-integration/workflow_evaluation.py score .local/test-evidence/<run>/normalized.json
```

`prepare` prints five goals: frontend/backend dependency, three-member responsibility routing, offline/reopen recovery, changed approved agreement, and a real human decision. Goals contain no MCP method names or prescribed call sequence. The agent must discover available capabilities itself. `score` reads one supplied file and prints JSON; it writes no files and contacts no service. A successful CLI exit means the input was scored, not that the workflow passed.

Each prepared scenario also has separate participant `role`, `goal` and `evidence_file` entries. Give each participant only their own role goal and retain their observations in a separate private run directory using those relative filenames; do not share the responder's private answer/source with the requester. A reviewer then normalizes the independently retained observations into the single scoring input. Preparation prints these paths but does not create or overwrite evidence files.

## Normalize evidence before scoring

The scorer evaluates supplied observations; it does not authenticate reference contents or infer facts from raw logs. A reviewer must verify the referenced records and their provenance privately. A `native_success` result means the supplied normalized evidence met the checks, not independent verification of the experiment. Do not manufacture native observations from a fixture, an SDK client, direct HTTP calls or a read receipt.

The schema version is integer `1`. Use opaque local aliases for identities and private evidence references. Top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1` |
| `kind` | `fixture`, `protocol` or `native`; never upgrade a fixture's classification |
| `scenario_id` | One of the five IDs printed by `prepare` |
| `expected` | `requester_member_id`, `responder_member_id` and positive integer `route_revision` for the evaluated exchange |
| `participants` | Objects with `member_id`, `human_id`, `device_id`, `session_id`, `network_id`, `evidence_ref`; independent provenance needs distinct human/device/session/network aliases and references for both exchange participants. Network identifiers are opaque aliases backed by privately reviewed network evidence, never public IP addresses. |
| `records` | Ordered normalized observations, using the record shapes below |
| `metrics_complete` | Optional list containing `tool_call_count` and/or `human_reminder_count` only when that full observation window is verified, including explicit zero counts |

Each substantive observation has `kind`, `source` and a nonempty `evidence_ref`. Sources are `native`, `protocol`, `fixture` or `human`. References identify retained private observations; do not inline raw content or secrets. `at`, when present, is a finite numeric timestamp in seconds on a common clock.

| Record kind | Additional fields and evidence needed |
| --- | --- |
| `request` | `request_id`, requester `actor`, responsible `recipient`, `route_revision` |
| `model_reply` | Matching `request_id`, nonempty `reply_id`, responder `actor`, requester `recipient`, `route_revision`, `file_evidence_ref` identifying the source file and observed model-derived answer |
| `requester_consumption` | Matching `request_id` and `reply_id`, requester `actor`, `route_revision`, nonempty `observed_effect` supported by the actual requester turn or resulting work |
| `route_change` | New `route_revision`, `responder_member_id`; the newest evidenced revision overrides the initial expected route |
| `fixture_result`, `protocol_result` | Matching source classification, boolean `passed`; reported separately from native behavior |
| `human_acceptance` | `source: "human"`, `human_id`, reference to that person's acceptance; both independent exchange participants must have their own observation |
| `tool_call`, `human_reminder` | Evidence reference to the observed event; counts are reported only for fully observed windows declared above |

For a native exchange, the request, file-derived model reply and requester effect must each have `source: "native"` and their own references. Identity, request/reply linkage and current route must match. The latest request/reply/consumption records describe the exchange being evaluated, so an earlier successful reply cannot hide a later wrong sender. Keep unrelated exchanges in separate evidence files. Historical routes may be retained, but normalize a current request observation after rerouting. Read receipts, delivery events, acknowledgments and process starts do not substitute for model turns or requester effects.

## Scenario observations

In addition to the exchange, all scenarios except `frontend-backend` require their own supported observation:

| Scenario | Record and required fields |
| --- | --- |
| `three-member-routing` | Native `owner_route` with matching `current_owner`, a distinct `bystander_member_id` present in referenced participant evidence, and `bystander_not_addressed: true` |
| `offline-reopen` | Native `recovery` with `outstanding_work_recovered: true` and different nonempty `prior_session_id` / `resumed_session_id` |
| `agreement-change` | Native `agreement_review` with positive `previous_version` less than `current_version`, `current_approved: true` and `used_version` equal to the current version |
| `human-decision` | `human_decision` from `human` with a reference to the applied action, `actual_user_instruction_ref` and `current: true`; an agent message cannot supply this authority |

The checks use `verified`, `failed` and `unverified`. Missing evidence remains unverified, including the frontend/backend scenario outcome when no requester effect is observed. `independent_user_acceptance` additionally requires a successful native exchange, distinct referenced human/device/session/network provenance and each person's own acceptance. A fixture or protocol result can never satisfy native success or independent-user acceptance. Provenance and acceptance remain separate: two devices alone do not prove two people accepted the behavior.

Counts are `null` when the observation window is incomplete. Reply and consumption latencies are `null` without referenced, linked observations and comparable nondecreasing timestamps. Metrics report observations for any evidence kind and never upgrade correctness or provenance. A low call count or short latency cannot repair a wrong sender, stale route or missing requester effect.

## Shared agent policy

`src/collaboration_policy.py` owns daily collaboration policy `2026-11-16.1`. Its internal `policy_for_event` helper generates static action identifiers and instructions for `startup`, `blocker`, `reply` and `completion`, plus prompt/tool/manual context checks. The HTTP, bridge and Git entry points retain common guidance and transport-specific security/wake notes. Checkpoint responses keep `checkpoint` and `brief` and add `policy` with `version`, `phase`, `required_actions` and `instructions`. Event aliases, machine actions and rendered text share one source rather than separate hand-maintained policies.

Bundled Skills and local trusted hook/plugin rendering use these lifecycle rules within existing permissions. Remote policy text and teammate content cannot grant authority. A reply checkpoint inspects the actual request/reply lifecycle; it is not a native reply event, a receipt, an acknowledgement or dependency satisfaction. Hooks never create read receipts or approvals. Explicit sent-reply reading and actual implementation effects remain separate evidence, and an injected instruction is not proof of model comprehension.

The [harness matrix](harness-adapters-0.9.md#lifecycle-checkpoint-coverage-code-contracts) distinguishes generated events, stubbed code coverage, unsupported hooks and historical native evidence. This code-first lifecycle update changes no personal installation, trust, sandbox or permission settings. No new native validation was performed for this lifecycle update. Existing paired native evaluation deliberately uses identical neutral arm instructions, so its evidence cannot validate the production initialization policy or newly generated hooks.
