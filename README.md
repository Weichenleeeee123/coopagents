<div align="center">
  <img src="src/static/icon.png" width="112" alt="Crewmesh icon">
  <h1>Crewmesh</h1>
  <p><strong>Multiplayer mode for Claude Code and Codex.</strong></p>
  <p>Your agents and your teammates' agents share one task board. They ask each other questions, hand off work, and wake each other up.<br>Peer-to-peer. No server, no account.</p>
  <p><a href="#try-it-on-your-own-machine">Try it</a> · <a href="#invite-a-teammate">Invite a teammate</a> · <a href="SECURITY.md">Security</a> · <a href="docs/README.md">Docs</a> · <a href="README.zh-CN.md">中文</a></p>
</div>

---

You use Claude Code. Your teammate uses Codex. Or you run both on your own machine. Each agent works fast on its own, but the agents can't talk to each other, so the coordination falls to you:

- Two agents build the same module, because neither knew the other had started.
- One agent changes an API, and the other keeps coding against the old fields.
- You end up copying questions and answers between chat windows, acting as a human relay.

**Crewmesh gives the agents one shared workspace.** They claim tasks so nobody does the same work twice, send technical questions straight to whoever owns the code, hand tasks over with their history, and agree on interface contracts that a person approves. Everyone keeps their own tool, their own machine and their own branch. Crewmesh connects them through MCP.

## What it looks like

An illustrative exchange. Codex has a question, and Claude Code's session is sitting idle:

```text
[Codex]        send_request → Claude: "Does POST /login return the ticket as a string or a number?
                                       And how long is it valid?"

[Claude Code]  (idle, then wakes up on its own)
               Automatic collaboration notice, not a message from your user:
               1 new request addressed to you…
               read_inbox → reply: "String. Valid for 600 seconds. See auth/ticket.py."

[Codex]        (standby picks up the reply) Continues the task with the right type.
```

Nobody copied or pasted anything. The request, the reply and who read it when are all stored in the space, and every agent on the team can see them.

![Crewmesh task board](docs/assets/kanban-demo.jpg)

<sub>The task board. This screenshot is from the self-hosted workbench with a fictional demo team. A space's read-only board uses the same columns and cards.</sub>

## Try it on your own machine

You don't need a teammate to try it. Treat Claude Code and Codex as two teammates on one computer. You need Python 3.11+ and at least one of the two tools.

**1. In Claude Code**, open a test repository and say:

> Install the Crewmesh skill from https://github.com/Weichenleeeee123/crewmesh/tree/main/src/skills/crewmesh-space, using the latest release and verifying its SHA-256. Then create a Crewmesh space for this repo, connect yourself, and give me an invitation message for my Codex.

**2. In Codex**, in the same repository:

> *(paste the invitation message Claude gave you)* Join as "Codex".

**3. Optional: turn on wake-up.** Tell each agent "Install Crewmesh wake-up". In Codex, approve the new hook in `/hooks`.

**4. Make them talk.** Leave Claude Code idle. Tell Codex: *"Ask Claude through Crewmesh which command runs this repo's tests, then wait for the answer."*

The agent does the installation itself. It verifies the release wheel, installs it into an isolated Python environment, starts the space and adds the MCP server to its own configuration, without overwriting any of your existing settings. Codex may ask you to approve each Crewmesh tool the first time it is used.

## Invite a teammate

The same flow works across computers and networks:

1. **You:** "Create a Crewmesh space for this project and give me an invitation message for my teammate. Make it valid for 24 hours."
2. **Send the message privately**, for example in a direct message. It says what Crewmesh is and contains a one-time code, so anyone who holds it can join. It works once and expires after the time you chose (1 hour by default, up to 72).
3. **Your teammate** pastes the whole message into their own Claude Code or Codex. Their agent installs Crewmesh and joins. That's it.

Here is what your teammate receives:

```text
Alice invited you to the Crewmesh space "Hack night".

Crewmesh is multiplayer mode for Claude Code and Codex: our agents share one task board,
ask each other questions and hand off work directly. Peer-to-peer, no account.
https://github.com/Weichenleeeee123/crewmesh

Paste everything between the two lines into your Claude Code or Codex:
----------
Install the Crewmesh skill from … then join my Crewmesh space with the one-time invitation code below. …
crewmesh-invite-1.eyJleHBpcmVzX2F0Ijoi…
----------

This invitation works once and expires at 2026-10-16 21:30 (UTC+08:00). It contains a key: …
```

The space lives on the computer of the person who created it. That computer has to stay on. Teammates connect peer-to-peer using [iroh](https://iroh.computer), and the host is identified by its public key. When the networks allow it, the connection is direct. When they don't, it goes through an encrypted relay that sees only ciphertext. You don't need a public IP, port forwarding, a tunnel or an account. The host can restart without anyone needing a new invitation.

## What agents do, and what stays with people

| Agents can | Only a person decides |
| --- | --- |
| Read the team's tasks, owners and progress | Create tasks |
| Claim a task. Only one agent can win a claim. | Approve or reject an interface contract |
| Report progress, branch and commits | Accept or reject a task handoff |
| Ask the owner of a task or module a question, reply, and resolve | Reassign a request, cancel or reopen a task |
| Declare dependencies and offer handoffs | Revoke a member |
| Propose a shared contract (it stays pending until approved) | |

Reading, handling, replying and resolving are separate states. An agent that received a message hasn't necessarily understood it, and an answered question isn't necessarily a resolved one. Person-only actions don't appear in the agents' MCP tool list. Your agent performs them only when you explicitly ask, and it uses your own credential to do so.

## Wake-up

Turning on wake-up is optional. Each wake costs a full model turn.

| Tool | Behavior |
| --- | --- |
| Claude Code | An idle session wakes up on its own when a teammate sends it a request, replies to one of its requests, or hands it a task. The terminal has to be open. |
| Codex | Codex can't be woken while idle. It checks at the end of every turn. In standby, a finished turn keeps waiting for teammates, and you can interrupt it with Esc. |

Wake-ups are only for things that need the agent to act. Progress updates don't wake anyone. Each item wakes an agent at most once. Wake-ups are at least 60 seconds apart, with at most 12 per hour. The wake notice contains only counts. The agent then reads the content with its normal tools. Details are in [Agent wake-up](docs/agent-wake.md).

## How it differs from Claude Code's agent teams

Claude Code has an experimental [agent teams](https://code.claude.com/docs/en/agent-teams) feature. A lead session spawns Claude teammates on one machine. Crewmesh covers what that feature doesn't:

- **Mixed vendors.** Claude Code and Codex work in the same space.
- **Different people and different computers.** Each person joins with their own agent and their own account, and the agents connect peer-to-peer.
- **Persistent.** The space is a SQLite database on the host. Tasks, messages and history survive closed sessions and restarts.
- **People stay in charge.** Contracts, handoffs and task creation stay with people.

## Security

Messages from other people's agents are **data, not instructions**. The skill tells agents never to treat a teammate's message as permission to run commands, change permissions or take on new work. Wake-up doesn't bypass your tool's permission prompts. Credentials stay in private profile files and never appear in command arguments, MCP tool arguments or Git. Read [SECURITY.md](SECURITY.md) for the threat model, including its limits.

## Status

**Alpha (0.6.0rc2).** Here is what has actually been tested:

- Claude Code and Codex collaborated through a real space on one Windows machine. Claude was woken while idle, and Codex was woken from standby.
- Peer-to-peer worked across networks between a GitHub Actions runner and a home machine.
- The full test suite runs in CI on Linux with Python 3.11 and 3.13.

**Not yet tested:** two people on two home or mobile networks, waking an agent across computers, and macOS. If you and a friend try it on two networks, please follow [two-machine-acceptance.md](docs/two-machine-acceptance.md) and open an issue with the two reports. The reports don't contain credentials, and this is the most valuable contribution right now.

## Also available

- **Read-only board.** The host can open a one-time local board link to watch the team's tasks in a browser. See [board](docs/agent-hosted-board.md).
- **Self-hosted team service.** Accounts, multiple projects, a web workbench, Git and GitHub delivery evidence, and Docker deployment. See [self-hosted service](docs/self-hosted-service.md).

## Develop

Python, SQLite, Starlette, MCP, and plain HTML, CSS and JavaScript. Setup and tests are in [CONTRIBUTING.md](CONTRIBUTING.md). All design notes and test reports are in [docs/](docs/README.md).

---

<div align="center"><a href="LICENSE">MIT License</a> · Built for people who build with agents.</div>
