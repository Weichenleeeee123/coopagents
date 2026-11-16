# Sandbox image build inputs

These are local image/bootstrap contracts, not a cloud builder or a ready-to-run
golden image. No image/base/package version was verified in this checkout. Every
`REQUIRED_INPUT` must be resolved in a private build lock before building, and the
builder must reject unresolved values or a non-`sha256:<64 lowercase hex>` digest.
Record the exact base reference/digest, every package version/artifact digest,
source commit, resulting image digest and build-tool version in the retained build
inventory. Overrides require a newly reviewed lock; never resolve a floating tag.
No provider IDs, endpoint values or credentials belong in these files.

The builder supplies a minimal Linux/systemd base with no SSH/RDP daemon, password
login, cloud login/RAM credential, cloud-init credential output, or host mounts.
Account tools, Python, Git, Node (agent only), CA certificates and systemd versions
must all be locked and verified. Bootstrap performs no installation/network access.
It creates accounts/directories without replacing existing file contents. Run it in
the disposable image VM, never on the workstation. No script enables services.

Run agent bootstrap with non-sensitive `RUN_ID` and `AGENT_ALIAS` aliases. Start
DSH as `dsh` through the private controller with HOME, DSH_HOME and XDG_CACHE_HOME
set to that VM/run's isolated profile and cache. Never share a writable profile or
clone between VMs. A new run requires a fresh VM disk; rerunning bootstrap preserves
existing profile files and does not reset identity or merge YAML. The profile row
contains only the loopback gateway. Model settings and this VM's short-lived proxy
credential use a separately verified runtime DSH injection contract; that contract
remains a G0 blocker until native DSH acceptance. No provider credential is sent to
an agent.

The gateway service runs the existing `bridge_client.py`, whose HTTP listener is
hard-coded to loopback. Install the unit from the pinned build artifact. Its member
profile arrives through systemd's runtime credential channel, readable only by the
gateway account; no bootstrap credential file is created. Require a compatible
systemd build supporting ImportCredential, load it from the private provisioning
channel, and verify credential expiry/revocation at the owner service. Never pass
credential contents in command lines, environment templates or journal output.
The initial service network policy permits only loopback: a private, reviewed
runtime drop-in must allow the member bridge's exact peer/relay destinations before
activation. The DSH user cannot read the gateway home. The owner agent VM also
requires separately reviewed P2P owner service/data placement and must remain online
during peer-outage scenes.

Control-plane bootstrap prepares four separate locked service accounts. Actual
proxy/coordinator/private-Git/evidence service entrypoints, private binds, isolation
units, branch ACLs and artifact hashes are required deployment inputs; no speculative
entrypoint is started. Provider secret injection is runtime-only to the proxy.
The control plane has no DSH package/home/member profile and cannot serve participant
Coopagents business traffic. External provisioning credentials never enter either
image. Network rules and outbound-only provider management remain in the reviewed
Alibaba Cloud module; these manifests create no ingress path.

Static validation does not establish a successful Linux image build, systemd
credential compatibility, native DSH configuration, proxy/Git reachability or NAT
behavior. Those gates remain required before snapshotting or creating agent VMs.
