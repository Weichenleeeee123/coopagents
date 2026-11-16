# DSH Sandbox Implementation Status

Date: 2026-11-17. Implementation branch: `codex/team-workflow-implementation`.

This status separates provider-independent implementation from evidence that requires an Alibaba Cloud account, a rotated model credential, real DSH sessions, or independent users. Passing unit tests do not close native/cloud gates.

## Implemented Locally

| Area | Implementation | Evidence |
| --- | --- | --- |
| Run identity and gates | Validates three distinct role/member/VM/NAT aliases, model fingerprint, fixed paired arms, timeout and budget; links scenario transitions to evidence and actual operator decisions. | `test_dsh_sandbox_manifest.py`, `test_dsh_sandbox_scenario_state.py` |
| Model API boundary | TLS-only complete Chat Completions proxy, fixed model, distinct short-lived VM tokens, bounded request/response and budget, redirect refusal, no body logging, null usage preservation. | `test_dsh_sandbox_proxy.py`, `test_dsh_sandbox_provider_probe.py` |
| Native provider probe | Synthetic tool-call/stream response classifier and opt-in CLI requiring key-rotation attestation; never sends a request unless explicitly enabled. | `test_dsh_sandbox_provider_probe.py` |
| Coopagents member gateway | Loopback-only MCP server with a fixed member identity, actual `Bridge.remote()` adapter and the member P2P link; rejects identity/credential overrides. | `test_dsh_sandbox_mcp_gateway.py` |
| Agent workspaces and Git | Seeded frontend/backend/integration fixtures, backend-only answer marker, role-specific goals and independent Git object databases; private Git pre-receive guard restricts each member to its own branch and rejects delete/non-fast-forward updates. | `test_dsh_sandbox_fixture.py`, `test_dsh_sandbox_private_git.py` |
| Image and cloud contracts | Agent/control-plane image/bootstrap contracts; Alibaba VPC/VSwitch/NAT/EIP/ECS, profile egress, control-plane private ingress, snapshots and validator-shaped three-agent inventory output. Terraform provider source was checked at v1.243.0 and unsupported fields corrected. | `test_dsh_sandbox_images.py`, `test_dsh_sandbox_alicloud.py`, `test_dsh_sandbox_provider_contract.py` |
| Local scenario control | Adapter-injected paired arms, seeded workspaces, bounded transitions, explicit operator gate, hard stops, unique retained artifacts and harness-only labeling. | `test_dsh_sandbox_runner.py` |
| Native DSH execution | Isolated per-role profile/workspace, fixed provider/model configuration, Coopagents MCP only in the treatment arm, bounded process execution, path-only `run-config`, returned-session continuation and private trace retention. Both native and cloud execution require explicit opt-ins. | `test_dsh_sandbox_dsh_runner.py`, `test_dsh_sandbox_cloud.py` |
| Alibaba Cloud execution adapter | Read-only run-tag/instance preflight, exact member VM lifecycle operations, fixed Cloud Assistant command and invocation polling. Unsupported scenario changes return `await_observation`; they cannot create business messages or approvals. | `test_dsh_sandbox_cloud.py` |
| Blind scoring | Hash-only hidden-test projection, all-attempt denominators, Wilson intervals, null missing usage/cost, no fixture-to-native promotion. | `test_dsh_sandbox_scoring.py` |
| Control plane | Private-IP TLS listener for the bounded model proxy, runtime credential loading and usage-only append ledger. Private Git SSH remains a separate service. | `test_dsh_sandbox_control_plane.py` |

Local verification on 2026-11-17: `python -m unittest discover -s tests -p 'test_dsh_sandbox*.py' -v` passed 109 tests. This covers fake cloud/DSH processes and static provider contracts only; it does not call Alibaba Cloud or the model API.

## External Acceptance Still Open

| Gate | Required evidence | Current state |
| --- | --- | --- |
| G0: model and DSH | Rotate the key pasted in chat; inject replacement in the secret manager; run the synthetic provider probe and one DSH native tool call through the local member gateway on a disposable VM. | Not run; no provider request was made. Native `run-config` is implemented and fake-process tested, but the installed DSH version and endpoint/tool-call compatibility remain unverified live. |
| G1: image and VM isolation | Resolve reviewed OS/DSH/package digests; build agent/control images; verify OS users, credential scope, isolated homes/workspaces and role-only Git access on disposable VMs. | Bootstrap/image contracts exist; no image builder or verified lockfile has been supplied, and actual image/VM isolation is unverified. |
| G2: independent cloud NAT | Review account quota/budget, establish private routes to proxy/Git, create three agent VPC/NAT egresses plus control plane, prove actual egress and selected direct/relay/blocked runtime paths. | Terraform template and opt-in cloud adapter are implemented, but no account inspection, plan/apply or resource operation occurred. The module does not create private inter-VPC routes; these must be implemented or separately provided before the private proxy/Git are reachable. `terraform validate` has not passed. |
| G3: real collaboration | Run the nine-scene role workflow with actual DSH sessions, member identities, requests/replies, offline/new-session recovery, handoff, agreement review and real operator decisions. | Scenario tests use fake adapters and remain `harness_only`; no live cloud/DSH result exists. |
| G4: paired evidence | Predeclare repetitions and cost limits; run matching control/Coopagents arms; retain every failure; publish blinded category/hash results and measured usage/latency/cost. | Scorer and report schema are implemented; no experiment data exists. |
| G5: independent users | Two separate people on separate devices/accounts and household/mobile networks complete the approved workflow. | Later gate; not inferred from cloud NAT tests or same-operator runs. |

The user-provided API key is intentionally absent from source, configuration, logs and run artifacts and must be rotated before use. No Terraform apply, model call, SSH reachability probe, or cloud resource operation occurred. The DSH sandbox code layer is implemented and its provider-independent regressions pass; the cloud/native experiment itself is not accepted until G0–G4 evidence exists. G5 remains an independent-user acceptance gate.
