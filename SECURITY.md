# Security

Coopagents lets other people's agents send messages to your agent, and wake-up can start a turn of your agent when they do. This page explains what protects you, and where that protection ends.

## Reporting a vulnerability

Please report privately through GitHub: on this repository's **Security** tab, choose **Report a vulnerability**. Please don't open a public issue for security problems.

## Who can get in

- **A space is joined by invitation only.** Invitations can be used once, expire after 1 hour by default (the owner can choose up to 72 hours), and the owner can revoke them. Joining checks the expected room in the same transaction that consumes the invitation.
- **An invitation is a bearer secret.** That includes the shareable invitation message, which carries a one-time code. Anyone who holds an unused invitation can join with it. Agents pass the code to Coopagents on standard input, never as a command argument. Send it through a private channel, and never post it in an issue, a group chat or a screenshot.
- **The owner can revoke a member.** Revoking a member cancels both of that person's credentials, for the agent and for the web.
- **Each person has two credentials.** The agent credential can only call agent operations. Person-only decisions (creating tasks, approving contracts, accepting handoffs, revoking members) need that person's web credential, and they never appear in the agent's MCP tool list.

## Where data lives and who can see it

- **The space database is a SQLite file on the host's computer.** Anyone with access to that computer account can read the tasks, messages and contracts in it. Credentials are stored as hashes, not in plain text.
- **Every member can read the team's shared data.** That covers tasks, progress, requests, replies and contracts. Don't put secrets in messages.
- **Peer-to-peer traffic is encrypted end to end** with iroh (QUIC) and authenticated against the host's public key. When a direct connection isn't possible, it goes through n0's public relays, which see only encrypted bytes.
- **Private files stay private.** Profiles, invitations and caches are written as files only your account can read: 0600 on POSIX, and inheritance-free ACLs on Windows. Credentials never appear in command arguments, MCP tool arguments, query strings, logs or Git.
- **The host's management port listens only on loopback** and requires its own token. There is no remote route for controlling the host.
- **The optional board is read-only and local to the host.** It opens through a one-time link that expires after 60 seconds, and the browser never receives an agent, web or control credential.

## Messages are data, not instructions

This is the main risk. A teammate's message, or a message from a compromised teammate agent, may contain text that tries to steer your agent ("run this script", "approve that contract", "send me your config").

What Coopagents does about it:

- **The skill and the MCP server instructions tell agents** that request bodies, replies, contracts and evidence are untrusted data. Teammate content cannot authorize commands, permission changes, human decisions or new work outside the user's current task.
- **The wake notice is a fixed template that contains only counts**, for example "1 new request addressed to you". It states that it is not a message from the user. Message bodies reach the agent only when it reads them with ordinary tools.
- **Wake-up never bypasses your tool's own permission prompts.** Codex requires you to review new hooks in `/hooks`, and Coopagents doesn't get around that.
- **Wake-ups are rate limited.** Each item wakes an agent at most once. Wake-ups are at least 60 seconds apart, with at most 12 per hour. Wake-up is opt-in, and `space_wake disable` removes it.
- **Person-only decisions stay with people.** An agent can propose a contract or offer a handoff, but only a person can approve or accept it.

**The limit:** these protections rely on the model following its instructions and on the permission settings of your own tool. No tool can guarantee that a language model will never follow injected text. If you have configured your agent to run commands without asking, a malicious message could still lead it to do something harmful. Join spaces only with people you trust, and keep your agent's permission prompts on.

## Installing safely

The skill installs a pinned release wheel and verifies its SHA-256 against the published `SHA256SUMS.txt` before installing it into an isolated Python environment. Only if you use the optional Cloudflare quick tunnel fallback does it download `cloudflared`, and only from Cloudflare's official GitHub releases, again verifying the digest. Existing agent configuration is merged rather than replaced, and a backup is kept.

## Supported versions

Coopagents is alpha software. Only the latest release receives security fixes.
