# DeepSeek Harness Network Sandbox Implementation Plan

> **For agentic workers:** Use task-focused implementation with TDD and one unified integration review after the complete first implementation round. Do not create or delete cloud resources until the operator stage is explicitly authorized. Never log or commit model, cloud or Coopagents credentials.

**Goal:** Build a disposable three-agent DeepSeek Harness test environment with isolated VMs, independent cloud NAT egress, one identical model API, an actual Coopagents collaboration service, and reproducible non-tool-directed development scenarios.

**Architecture:** Three independent agent VMs host front-end, back-end and integration DSH members; the designated front-end owner VM also hosts the P2P space so the service itself is behind NAT. A separate control-plane VM runs a private Git remote, scenario coordinator, bounded API proxy and one member-scoped MCP gateway per agent. All provider keys and cloud credentials remain only in a secret manager/control plane.

**Tech Stack:** Existing Python Coopagents package and authenticated MCP/HTTP APIs; DeepSeek Harness CLI; OpenAI-compatible Chat Completions API proxy; independent cloud VM/subnet/NAT resources selected from the operator's existing provider account; private Git service; existing workflow evaluator extended with real native evidence.

---

## Scope and implementation boundaries

This master plan contains three independently testable subprojects: (A) one disposable DSH/API compatibility VM and secure control-plane services, (B) per-agent VM provisioning and same-model role sessions, (C) comparative collaboration/NAT scenario execution and evidence. Each subproject must pass its own local acceptance before the next provisions additional resources.

The cloud provider is selected during Task 1 from an account the operator already controls; provisioning must not create billable resources without the later operator run command. The current user-supplied provider API key must be rotated before the first external API call. The plan references only environment variable names and secret-manager handles.

## Files and ownership

- Create `deploy/dsh-sandbox/provider_contract.md` defining instance, subnet, independent NAT, firewall, DNS, snapshot and destroy semantics without provider credentials.
- Create the selected provider implementation under `deploy/dsh-sandbox/iac/`, with VM images/cloud-init, firewall/NAT modules and output validator only after Task 1 selects the provider.
- Create `deploy/dsh-sandbox/images/agent/` and `images/control-plane/` pinned manifests; agent image creates the isolated OS users and DSH profile entrypoint.
- Create `experiments/agent-integration/dsh_sandbox/` for run manifest, API proxy, MCP gateway, scenario prompts, run coordinator, telemetry, redaction and scoring.
- Create fast provider-independent tests as `tests/test_dsh_sandbox_*.py`; put tests requiring actual DSH/cloud/network activity under `experiments/agent-integration/test_dsh_sandbox_*.py`.
- Modify `experiments/agent-integration/workflow_evaluation.py` only to accept actual native runner exports while preserving current fixture/protocol/native classifications and no-auto-upgrade rules.
- Update `docs/dsh-sandbox-runbook.md`, `docs/team-workflow-acceptance.md`, `docs/deepseek-harness-gaps.md` and `docs/README.md` after measured results.
- Write every environment, snapshot, log and evidence file under ignored `.local/dsh-sandbox-runs/<run-id>/`; never place secrets under `experiments/`, tracked `deploy/` or source trees.

## Stage A: Technical compatibility and control plane

### Task 1: Select and validate the cloud provider contract

**Files:** create `deploy/dsh-sandbox/provider_contract.md`, `tests/test_dsh_sandbox_provider_contract.py`, provider inventory input in ignored run manifest.

- [ ] Add passing unit tests for a provider output validator that rejects duplicate `egress_network_id`, public-eip duplicates when distinct egress is required, inbound SSH/RDP, public control endpoints, shared agent subnets and missing instance deallocation/snapshot metadata.
- [ ] Record the chosen existing cloud account/provider/region using secret-free identifiers and verify quota for four Linux VMs plus three independent egress/NAT paths; do not create resources in this task.
- [ ] Run `python -m unittest discover -s tests -p 'test_dsh_sandbox_provider_contract.py' -v`; expected all contract validation tests pass with synthetic provider inventory.
- [ ] Commit provider-neutral contract and tests only.

### Task 2: Verify exact model endpoint from one disposable DSH VM

**Files:** create `experiments/agent-integration/dsh_sandbox/provider_probe.py`, `tests/test_dsh_sandbox_provider_probe.py`, `experiments/agent-integration/test_dsh_sandbox_provider_probe_live.py`, and redacted `docs/dsh-sandbox-runbook.md` compatibility checklist.

- [ ] Define `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` as runtime-only inputs; parser diagnostics and structured logs must expose only variable names and safe response classification, never values/headers/body.
- [ ] Add tests for endpoint joining preserving a complete `/chat/completions` URL (never appending the suffix twice), TLS enforcement, redirect refusal, proxy auth/rate-limit handling and request body limits.
- [ ] Add a probe mode that sends one low-token synthetic tool-call request through the exact endpoint and verifies: response model identifier, content, tool call schema, stream termination, and usage fields when supplied. Never send source code, hidden oracle or credentials in prompt text.
- [ ] Before calling the provider, the operator rotates the chat-exposed key and puts its replacement into the private secret manager; inject it only into the probe proxy process, then clear the named runtime reference when the probe exits.
- [ ] In a disposable Linux VM install the pinned DSH CLI, configure the custom endpoint/model, verify one real native DSH turn and one actual tool call through a local fixture MCP server; record version/response classification/usage only.
- [ ] Stop here with an explicit compatibility blocker if DSH cannot load the custom endpoint or native tool calling. Do not switch to SDK/direct HTTP and report it as DSH acceptance.
- [ ] Run `python -m unittest discover -s tests -p 'test_dsh_sandbox_provider_probe.py' -v`, then invoke the separate live probe only in its disposable VM and retain sanitized evidence. No additional agent VMs yet.

### Task 3: Implement the control-plane API proxy and MCP gateways

**Files:** create `experiments/agent-integration/dsh_sandbox/api_proxy.py`, `mcp_gateway.py`, `control_plane.py`, `tests/test_dsh_sandbox_proxy.py`, `tests/test_dsh_sandbox_mcp_gateway.py`.

- [ ] Write tests before handlers: request/response byte limits, HTTPS upstream only, redirects refused, provider auth never forwarded to agent, provider error bodies redacted, request budgets/cost stops, no prompt/body persistence, exact URL forwarding and proxy usage parsing (unknown remains null).
- [ ] Implement a bounded reverse proxy accepting a distinct short-lived per-VM credential, mapping it to the fixed configured provider endpoint and one allowed model, rate-limiting requests, enforcing token/cost run budget, and returning upstream status/tool-call/chunking behavior unchanged where compatible.
- [ ] Implement one MCP gateway listener per Coopagents member identity. Gateway reads one member's agent credential from an owner-only secret path, injects it upstream, accepts no token/identity arguments from DSH, and exposes only that member's authenticated `/mcp` tools. Use a separate Unix service account and per-VM localhost socket/port; never reuse one member's token for another VM.
- [ ] Test gateway member isolation against a real local `CoordinationService`: frontend and backend gateways return different `whoami`, and no DSH request can supply another member's Authorization or owner credential.
- [ ] Ensure proxy/gateway records contain run id, VM alias, timestamp, operation/tool name, status, byte counts, usage and latency only; create tests that sentinel prompt/key strings never appear in files or exception output.
- [ ] Run focused proxy/MCP tests, HTTP/MCP auth regressions, and a single DSH call through both gateways before moving to cloud provisioning.
- [ ] Commit control-plane source/tests without credentials or run artifacts.

## Stage B: Isolated agent VMs and project fixture

### Task 4: Provision immutable agent/control images and network boundaries

**Files:** selected provider implementation in `deploy/dsh-sandbox/iac/`, image manifests/bootstrap files, `tests/test_dsh_sandbox_network_policy.py`, `tests/test_dsh_sandbox_image_manifest.py`.

- [ ] Add provider-module tests that require three unique NAT gateway/subnet IDs and egress identities for the three agents; permit only outbound DNS/NTP, provider proxy, Coopagents peer/relay ports and private Git; deny unsolicited inbound sessions and cross-agent east-west traffic.
- [ ] Build identical pinned Linux agent images with non-root DSH account, separate protected MCP gateway service account, fresh per-VM DSH_HOME, monotonic clock, no public SSH/RDP, no cloud credentials and no mounted host directories.
- [ ] Build a separate control-plane image for coordinator, model proxy, internal Git and evidence collector. Provider API credentials are injected only into the external provisioning controller, not that VM after creation.
- [ ] Create per-VM cloud-init that obtains per-member Coopagents credentials from a short-lived provisioning channel, writes them only to the member gateway's private path, then removes bootstrap material. Do not print cloud-init secret output.
- [ ] Require a designated owner agent VM to host the Coopagents P2P service/database/identity; keep this owner VM online during peer-outage scenes. The control plane must not fabricate membership, request or model-consumption events.
- [ ] Snapshot the clean image and produce three cloned agent VMs behind distinct NAT egress. Record provider-reported subnet/NAT IDs and verify egress identity from each VM.
- [ ] Do not provision until the operator runs the reviewed provider command. Tag resources with run id/expiry and create a retained inventory before starting DSH.
- [ ] Run image/network validators and `node --check` any generated bootstrap helpers; make compute deallocation require the exact current run id and produce an inventory/dry-run preview. Preserve persistent disks, VM snapshots and experiment evidence; deallocation must never delete them.

### Task 5: Create isolated synthetic Git repository and actor workspaces

**Files:** create `experiments/agent-integration/dsh_sandbox/fixture_repo.py`, `role_goals.py`, `tests/test_dsh_sandbox_fixture.py`.

- [ ] Generate a tiny deterministic Python/TypeScript project with frontend contract consumer, backend profile endpoint, integration test package and no real company code or secrets. Store per-run generation seed and tree hash.
- [ ] Keep answer markers in backend-only source; keep expected API values and hidden tests on control plane. Test that front-end and integration VM clones do not contain backend-only answer files or hidden test files.
- [ ] Create one private Git remote and one independent branch/clone per agent VM. Restrict write identity to its own branch; no GitHub origin, public PR, release or upstream push.
- [ ] Define separate role goals with observable work products and no Coopagents tool names/call sequence. Unit tests scan prompts for prohibited method names and verify files are stored separately per role.
- [ ] Build an initial empty-space state and a seeded task/agreement state using existing web/member operations and synthetic credentials; unit-test snapshot isolation and repeatable reset.
- [ ] Run fixture/unit tests and one agent VM read/write Git smoke before executing model scenarios.

## Stage C: Reproducible real collaboration and NAT evidence

### Task 6: Implement scenario coordinator and native DSH runner

**Files:** create `experiments/agent-integration/dsh_sandbox/runner.py`, `scenario_state.py`, `evidence.py`, `experiments/agent-integration/test_dsh_sandbox_runner.py`, `experiments/agent-integration/test_dsh_sandbox_scenarios.py`; extend `experiments/agent-integration/test_workflow_evaluation.py`.

- [ ] Define a run manifest with source commit, DSH/OS/agent image versions, model/proxy config hash, anonymized VM/NAT aliases, scenario seed, arm order, cost limit, timeout and role assignments. Reject missing identities, non-distinct NAT aliases or mismatched model config.
- [ ] Add fake-process tests for runner state transitions, bounded waits, DSH exit, VM unreachable, owner-host failure, API budget exhaustion, held human decision and terminal evidence status. A fake DSH unit test is a harness regression only, never a native acceptance run.
- [ ] Implement actual DSH launch over the chosen provider's private management/control channel. Each call uses its own VM/profile/workspace, role-only prompt, fixed timeout and usage budget. Capture stdout/stderr only after explicit redaction; never include API/MCP keys or full prompt/source text.
- [ ] Implement scenario transitions as external triggers plus observations: create tasks; wait for actual owner question/reply; pause responder VM; continue requester; restart responder with a fresh session; observe recovery; operator accepts handoff via real authorized web operation; approve v2 via the same; pause at human-decision gate; resume only after recorded operator decision; run hidden test outside agent VMs.
- [ ] Every observation must have source `native`, exact room/member/session/task/revision/reply ids and private evidence references. The evaluator must reject HTTP/MCP fixture-only rows as native success and must not infer answer use from read receipts.
- [ ] Add the Control arm using identical DSH/model settings with Coopagents MCP disabled; test operator manually passes only the same information that an agent could request and logs each relay event without changing the answer. Randomize arm order and use distinct synthetic values in replay runs.
- [ ] Run coordinator/evidence unit tests and a no-provider dry-run that creates only a local synthetic run manifest; then use the single permitted real API/DSH smoke budget to verify one treatment turn and one control turn.

### Task 7: Exercise cloud NAT paths and recovery

**Files:** create `experiments/agent-integration/dsh_sandbox/network_matrix.py`, `experiments/agent-integration/test_dsh_sandbox_network_matrix.py`, update runbook/results.

- [ ] Add deterministic matrix cases: direct UDP permitted, restrictive UDP/forced encrypted relay, full UDP block/unreachable negative control, client NAT mapping change, member VM stop/start with same profile, owner-host stop/start with same database/endpoint identity.
- [ ] Collect peer runtime selected-path evidence plus independent NAT inventory; never infer direct/relay from configuration or one side's claim. Label cloud source/destination network and egress aliases in private logs.
- [ ] For each disruption, verify business requests/replies retained server-side, change cursor resumes without gaps/duplicates, revoked credentials remain rejected, current owner route is re-read and stale session writes are rejected.
- [ ] Verify recovery when responder VM starts a new DSH session. Do not install or claim DSH idle wake; the documented DSH surface has no external wake contract.
- [ ] Stop each network run on max elapsed time, repeated failure budget or owner-host loss; preserve partial evidence and exact terminal state.
- [ ] Cloud NAT acceptance requires at least 3 runs for each selected path class. Use additional predeclared repetitions to compute response, cost and success intervals; don't stop when an arm first passes.
- [ ] Run only after an operator has reviewed the NAT/egress provisioning plan and budget.

### Task 8: Blind functional scoring, comparison and operator UX

**Files:** extend `experiments/agent-integration/workflow_evaluation.py` / tests; add `docs/dsh-sandbox-runbook.md`, `docs/dsh-sandbox-results-template.md`, index links.

- [ ] Hidden test runner executes on control plane against pushed private branches and emits only pass/fail/category and patch hash to the scorer; expected field values stay separate from role VM evidence.
- [ ] Add metrics for correct owner route, first useful reply time, human reminder/relay count, duplicate requests, requester answer effect, hidden tests, handoff/approval violations, direct/relay path, reconnect recovery and actual provider usage/cost. Null missing provider telemetry rather than estimating it.
- [ ] Add statistical report over all attempted runs, including failed DSH start, auth/tool-load failure, network timeout and cost stops; report numerator/denominator and confidence interval per arm.
- [ ] Add a local runbook that explains rotating/injecting the API key, provisioning review, endpoint compatibility gate, member gateway, scenario reset, hard stop, evidence redaction and accurate Gate G0-G5 terminology.
- [ ] Test scorer adversarial inputs, stale route, repeated/delayed event, missing cost, unauthorized approval, test-oracle leak marker and false model-consumption marker.
- [ ] Run full Python and Node suites; `git diff --check`; audit built wheel/sdist for no `.local`, profiles, secrets, cloud state or raw prompt fixtures.

## Experiment screenplay (fixed user-goal script)

Use three distinct roles and synthetic repo `sample-profile`:

- **Front agent / requester:** “Implement the profile form for this project. Confirm the current service contract and keep independent parts moving while another team member is busy.” It receives no backend answer and no method names.
- **Back agent / responder:** “Implement the profile endpoint with the repository requirements. Be prepared to explain fields based on your source.” A hidden file defines `display_name`, `avatar_url`, and a random per-run schema marker.
- **Integration agent / third owner:** “Add profile integration tests and help maintain consistency across the client and service implementation.” It must not receive a false assignment to front/back until the scenario explicitly transfers one.

The controller sequence is: clean start -> observe autonomous discovery -> let an actual backend answer be generated from its hidden file -> prove requester use in patch/hidden test -> stop backend VM and observe requester independent work -> start backend in new DSH session and measure recovery -> human accepts a back-to-integration handoff -> issue a stale old-route reply and verify rejection -> approve interface v2 through the web UI -> verify front agent reviews and updates actual use -> present one human-only decision and hold the conflicted operation until a designated person acts -> run hidden tests -> publish private branches to the sandbox Git remote. Control runs use the same role goals/model but the operator manually relays the necessary answer, with each relay counted.

No goal includes the words `ask_owner`, `read_replies`, `work_brief`, `checkpoint`, or MCP call instructions. Synthetic files contain no customer data or production secrets. A scenario report does not count a tester/operator as an independent second customer.

## Final exit criteria

This plan is implemented when all local/provider-independent tests pass, the three actual DSH sessions load their isolated Coopagents identities, the provider proxy safely handles the chosen unified endpoint, at least two distinct cloud NAT exits are proven, actual direct/relay outcomes are captured, and the blind role workflow has complete evidence including human gates and all failed runs. Exact run artifacts and hashes go into `.local`; only redacted aggregate results enter maintained docs. Home/mobile NAT and two-independent-user acceptance remains a later explicit test stage.

