# Agent-hosted space runtime

The runtime hosts the existing Crewmesh collaboration core without an account
service. Every person receives a separate web credential and agent credential.
MCP exposes the same agent operations as the hosted service. Web management uses
the person's web credential and an exact Origin header; domain roles continue
to decide which person may perform each operation.

From the repository's installed Python environment:

```powershell
python -m crewmesh.space_runtime create --name "Team" --owner "Alice" --state-dir .local/spaces/team
python -m crewmesh.space_runtime status --profile .local/spaces/team/profile.json
python -m crewmesh.space_runtime invite --profile .local/spaces/team/profile.json
python -m crewmesh.space_runtime join --invitation-file C:\private\invitation.json --name "Bob" --state-dir .local/spaces/bob
python -m crewmesh.space_runtime stop --profile .local/spaces/team/profile.json
python -m crewmesh.space_runtime start --profile .local/spaces/team/profile.json
```

Peer-to-peer mode (`--network p2p`) is the default. The host keeps a private
iroh endpoint key in `host.json`; its public endpoint id goes into invitations
and member profiles and stays the same across restarts. Each member's link
binds the host's loopback port number on the member's computer and carries
every TCP connection as one QUIC stream to the host, which forwards it to its
public loopback port. HTTP Host and Origin therefore match local access, and
the shared boundary, MCP and WebSocket checks are unchanged. Connections are
encrypted end to end and authenticated by the host key; iroh connects directly
when the networks allow and otherwise relays through n0's public relays, which
see only encrypted bytes. The owner's control `/status` reports the endpoint id
and whether it is online; a member's `status` reports a direct or relayed path.
If another program already uses the space's port on a member computer, the
link refuses to start rather than pick another port. Details and measurements:
[p2p report](agent-hosted-p2p-report.md).

Quick mode is the fallback and requires an explicitly verified cloudflared
executable. The adapter checks its version output, uses automatic transport
selection, and waits for a registered tunnel connection. Installation and
executable provenance verification belong to the calling setup workflow. The
runtime never downloads software. External mode accepts an operator's stable
HTTPS origin with `--network external --public-url https://space.example.com`;
the operator forwards that origin to the loopback service. `--network local`
is an explicit local-only development option.

Ordinary command output contains the origin, room and member identifiers,
private profile path, and status. `invite` writes a private invitation file;
`invite --share` explicitly prints the sensitive invitation descriptor for
sharing. A descriptor contains `schema_version`, `origin`, `room_id`,
`invite_token`, and `expires_at`. Invitations are single-use, expire after one
hour by default (`--hours`, at most 72), and can be revoked. Join checks the expected room inside the same domain
transaction that consumes the invitation. Send the invitation file through a
trusted private channel.

`invite --message en|zh` additionally returns `message`, a text to paste into a private chat: a short
pitch, the project and Skill links, a prompt for the invitee's own agent and a one-time code
`crewmesh-invite-1.<base64url>` carrying the same descriptor as the file. The invitee's agent passes the
whole message or the code on standard input, never as an argument:

```powershell
python -m crewmesh.space_runtime invite --profile .local/spaces/team/profile.json --message en --hours 24
Get-Content C:\private\message.txt | python -m crewmesh.space_runtime join --invitation-code-stdin --name "Bob" --state-dir .local/spaces/bob
```

```powershell
python -m crewmesh.space_runtime revoke-invitation --profile .local/spaces/team/profile.json --invitation-file .local/spaces/team/invitation-EXAMPLE.json
python -m crewmesh.space_runtime revoke-member --profile .local/spaces/team/profile.json --member-id MEMBER_ID
```

The owner controls invitation and member revocation. Revoking a member revokes
both personal credential kinds; the owner cannot revoke their own membership.
The owner profile contains `control_origin` and `control_token` in addition to
the version, public origin, room, member and two personal credentials. Joined
profiles contain no control credential. State stays outside a checkout or in
its ignored `.local` directory. Paths containing traversal, symlinks or Windows
junctions are refused. Profiles are private to the current account (POSIX 0600,
Windows ACL with inheritance removed), and profile updates retain private
historical versions. Database files, logs, profiles and lock files are preserved.

The supervisor runs hidden on Windows and receives only the profile path in
its arguments. An OS lock permits one runtime per host state. Its public and
control servers bind distinct loopback ports. The control service accepts an
opaque bearer token only from a loopback client with the expected Host and
Origin. Stop asks that control service to shut down gracefully; it does not
kill a PID read from state. Stop waits until the worker releases its ownership
lock after shutdown, allowing immediate restart. The worker shuts down only
its own tunnel child.

The public surface includes health, identity, snapshots, inbox, mapped
collaboration operations, `/api/operations/{operation}`, `/mcp`, `/api/events`,
and scoped `/api/join`. Generic operations refuse room creation and joining.
The public join exchange returns only the joining member's personal
credentials. Room bootstrap and host lifecycle are private; there is no remote
host-control route. HTTP bodies, Host and Origin use the shared bounded
transport boundary. Join attempts are bounded per client and the limiter has a
fixed maximum number of entries. Credentials never appear in query strings.
Clients reject redirects when sending credentials. Remote origins require
HTTPS; explicit loopback HTTP is supported.

Quick tunnel addresses change on restart. The owner profile is updated after
the new tunnel registers. Previously shared invitation addresses must be
reissued using the new origin, and other members reconnect using the new
address supplied by the owner:

```powershell
python -m crewmesh.space_runtime reconnect --profile .local/spaces/bob/profile.json --origin https://NEW.trycloudflare.com --room-id ROOM_ID
```

Reconnect verifies the expected room before sending the personal credential,
then verifies the existing member before updating the profile. It preserves
member identity and ownership. Stable external origins retain their address
across restarts. The room database and existing
personal identities survive restart. Status reports `unreachable` when the
saved endpoint cannot authenticate or the owner control endpoint is absent;
a stored profile alone does not prove that a runtime is running.

Both services use WebSocket frame/queue limits of 4096 bytes/four frames and
15-second ping/pong deadlines. HTTP access logging is disabled. Tests preserve
unique `.local/runtime-tests` evidence and cover actual two-port lifecycle,
personal joining, HTTP and SDK MCP, WebSocket invalidations, role denial,
duplicate task claims, revocation and database persistence across restart.

## L0/L1 验证记录（2026-10-12）

11 项运行与私有配置测试通过，覆盖真实独立监督进程、个人邀请加入、HTTP/MCP/WebSocket、撤销、原数据库重启、停止后立即重启、Windows Python 3.11 兼容的 junction 拒绝，以及托管 agent-only 配置。共享 HTTP 与身份的 4 项补充回归通过。设计及质量审查通过。

本机通过真实临时公网入口完成 HTTPS 健康检查、独立成员加入、WSS 和官方 SDK MCP 身份读取；创建返回的 HTTPS 地址与保存的配置一致。仅为单机公网往返，不代替另一电脑、另一网络协作验收。证据保留于忽略目录 `.local/runtime-public/8020dcb023c24f9aaef1a25008bc5d84/`，自己的服务与隧道已停止。
