# Tool-free workflow evaluation

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

`src/collaboration_policy.py` owns daily collaboration policy `2026-11-16.1`; HTTP, bridge and Git servers append their transport-specific security and wake notes. Bundled Skills summarize the same startup/blocker/completion, current responsibility, ownership epoch, explicit sent-reply reading, independent-work and human-authority requirements. Merely injecting the policy changes no protocol registration and creates no read receipts.
