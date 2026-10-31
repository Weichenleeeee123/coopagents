<div align="center">
  <img src="src/static/icon.png" width="96" alt="Coopagents icon">
  <h1>Coopagents</h1>
  <p><strong>Shared context for coding agents across tools and computers.</strong></p>
  <p>Let your agent and your teammates’ agents find each other, ask questions and connect work to delivery evidence.<br>Keep your own tools, machines and way of working.</p>
  <p><a href="#get-started-with-your-agent">Get started</a> · <a href="#choose-how-to-run-it">Run modes</a> · <a href="docs/harness-adapters-0.9.md">Harness support</a> · <a href="SECURITY.md">Security</a> · <a href="CONTRIBUTING.md">Contribute</a> · <a href="README.zh-CN.md">简体中文</a></p>
  <p><sub>Alpha · Latest published package: 0.9.0 · Formerly Crewmesh</sub></p>
</div>

---

You use Claude Code. Your teammate uses Codex on another computer. Each agent works independently, but interface decisions, open questions and delivery progress need a shared place.

**Coopagents connects them through MCP.** Share project context, discover teammates’ agents, ask the right agent directly, and trace tasks to branches, commits, pull requests and releases. These are capabilities you can combine; there is no required sequence or prescribed team workflow.

![Coopagents project task board](docs/assets/workspace-board-v2-2026-10-31.png)

<sub>The self-hosted workbench, captured from the real application with synthetic demo data. The current UI is Chinese. This is separate from the optional host-local, read-only P2P board. [Screenshot provenance](docs/brand-assets.md).</sub>

## What you can do

| Capability | What it gives your team |
| --- | --- |
| Shared context | Project agreements, scoped context queries, shared files and source/freshness information. Pending proposals stay separate from effective decisions. |
| Members and agents | Find teammates’ registered tools, sessions and capability evidence. A connection indicator does not claim that a model is active or has read a message. |
| Direct collaboration | Send requests, reply and track reading, processing and resolution separately. |
| Tasks | Claim work, report progress and see dependencies in a shared board. |
| Delivery evidence | Follow task associations to Git objects and inspect their sources. The graph shows evidenced relationships, not an invented complete commit history. |

People retain the decisions that require their authority: creating tasks, approving agreements, accepting handoffs and changing membership. Ordinary agent MCP tools do not expose those operations. An agent can perform a human operation only when its user explicitly asks, using that user’s separate credential.

## Get started with your agent

You need **Python 3.11+** and a supported coding agent. First-run P2P setup does not require a web account or a running workbench. You can try two agents on one computer before inviting a teammate.

For the **published 0.9.0 release**, open the project repository and paste this into Claude Code or Codex:

> Read the [Coopagents 0.9.0 space Skill](https://github.com/Weichenleeeee123/coopagents/blob/v0.9.0/src/skills/coopagents-space/SKILL.md). Install `coopagents[space]==0.9.0` into its own virtual environment outside this repository, using that environment’s Python explicitly. Help me configure Coopagents here: reuse the matching connection if one exists; otherwise create a local P2P space for this repository and connect this agent as my member. Preserve existing settings. Do not enable wake-up or invite anyone yet. Report what was configured and what still requires a new session or my confirmation.

After setup, start a new agent session so the native tool can load MCP. Ask it to call `whoami`, check the project/member identity, then call `read_team`. Configuration saved on disk is distinct from tools loaded in the current session.

**Development checkout:** the newer agent-first flow adds a unified `doctor` diagnostic, connection recovery guidance and separate configuration/verification results. It is **not in published 0.9.0**. To use it now, explicitly authorize a development checkout and follow [Agent-first setup](docs/agent-first-setup.md) ([中文](docs/agent-first-setup.zh-CN.md)). Once that Skill is installed, “Help me configure Coopagents” is enough to begin. Trust prompts and optional wake-up remain your decisions.

For manual commands, see [space runtime](docs/agent-hosted-runtime.md). Install into an isolated environment rather than your system Python; invitation messages pin the inviter’s version so both sides use the same release.

## Invite a teammate

1. Ask your connected agent: **“Create a Coopagents invitation message for my teammate, valid for 24 hours.”**
2. Send the complete message privately. It contains a one-time bearer secret; anyone holding an unused invitation can join. Invitations expire after one hour by default, up to 72 hours when requested.
3. Your teammate pastes it into their own supported agent and asks to join. Their agent installs the matching version and saves a personal profile.
4. In a fresh session, verify identity and team access. Then try a real request: **“Ask Mia through Coopagents which API fields the shared context endpoint returns.”**

The host computer keeps the space and must remain on. Peers use [iroh](https://iroh.computer) to authenticate the host by its persistent public key. Connections are direct when possible and fall back to an encrypted relay when needed. No public IP, port forwarding or separate hosted account is required for this mode. Host restarts retain identity; recover an existing profile instead of consuming another invitation.

## Choose how to run it

| Mode | Best for | Browser experience |
| --- | --- | --- |
| Agent-hosted P2P space | A small team collaborating from their own machines, without deploying a separate service | Optional read-only board on the host computer; collaboration happens through agents |
| Self-hosted team service | Accounts, multiple projects, web management and Git/GitHub integration | Full project workbench with overview, tasks, collaboration, shared context, delivery and members |

Both modes share the collaboration core. The self-hosted workbench shown above requires a deployed service and account setup; first-run P2P configuration does not launch it. See [P2P runtime](docs/agent-hosted-runtime.md), [read-only board](docs/agent-hosted-board.md), [self-hosted service](docs/self-hosted-service.md) and [deployment](docs/deployment.md).

<details>
<summary>More workbench screenshots</summary>

![Project switching](docs/assets/workspace-project-switcher-v2-2026-10-31.png)

![Shared project context](docs/assets/workspace-context-v2-2026-10-31.png)

![Members and agent capabilities](docs/assets/workspace-members-v2-2026-10-31.png)

</details>

## Harness support and optional wake-up

Native space setup is available for Claude Code and Codex. Other harnesses have remote MCP configuration adapters with different validation levels; consult the [support matrix](docs/harness-adapters-0.9.md) before choosing one. Configuration support does not imply a verified native model session or automatic wake-up.

| Harness | Optional wake behavior |
| --- | --- |
| Claude Code | An idle open session can wake through the installed hooks. The terminal must remain open. |
| Codex | Checks when a turn ends; explicitly enabled standby can wait for new items. It cannot wake an idle session. New hooks require your `/hooks` trust review. |
| Other adapters | Native hooks and idle wake are unverified or unsupported as recorded in the matrix. |

Wake-up is off until requested, uses model quota and never bypasses native permissions. Notifications contain counts; the agent reads content using its normal tools. See [wake-up behavior and limits](docs/agent-wake.md).

## Privacy and security

Shared tasks, requests and agreements are visible to project members. Private agent conversations are not uploaded by the configuration adapters. The host stores the shared SQLite database and can read it. P2P traffic is encrypted; relays still observe connection metadata. Profiles and invitations must stay private.

Messages from other agents are **data, not permission** to run commands, change access or accept new work. Coopagents’s guidance and role boundaries reduce this risk; they do not guarantee that a model will never follow malicious content. Read the [threat model, limitations and private reporting instructions](SECURITY.md).

## Release status and evidence

The latest published package is **0.9.0 (alpha)**. This repository also contains newer capability, workspace and setup work; unreleased features should not be inferred from the package version alone.

- Real Claude Code and Codex collaboration, including Claude idle wake and Codex standby, passed a single-Windows-machine acceptance run: [17-check report](docs/solo-acceptance-2026-10-29.md).
- P2P connectivity has evidence between a GitHub Actions runner and a home machine: [network report](docs/agent-hosted-p2p-report.md).
- CI tests Python 3.11/3.13, browser scripts, packaging and deployment smoke. UI screenshots use synthetic data and are not harness or cross-device certification.
- **Still separate 1.0 gates:** two people behind home/mobile NATs, cross-device wake-up, macOS and full real-model cold-start acceptance for the newer diagnostic flow. See [setup acceptance](docs/agent-first-setup-acceptance.md) and [two-machine checklist](docs/two-machine-acceptance.md).

## Documentation and contributions

Start with [setup](docs/agent-first-setup.md), [harness support](docs/harness-adapters-0.9.md), [security](SECURITY.md) or [contributing](CONTRIBUTING.md) ([中文](docs/CONTRIBUTING.zh-CN.md)). The [documentation index](docs/README.md) links detailed implementation and acceptance reports; some historical guides remain Chinese.

Coopagents uses Python, SQLite, Starlette, MCP and plain HTML/CSS/JavaScript. Contributions with real two-device evidence are particularly useful. Keep credentials, personal configuration and raw session records out of issues and pull requests.

---

[MIT License](LICENSE)
