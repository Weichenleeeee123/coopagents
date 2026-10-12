# Room invalidation stream, protocol 1

Both hosted and local service compositions use `events_route(service, base_url=...,
public_url=...)` from `crewmesh.realtime`. Register it before the MCP mount.
The collaboration core remains standard-library-only; the service dependency
includes `websockets==17.2` for Uvicorn's WebSocket transport.

Connect to `/api/events` with WebSocket. Query parameters are rejected, including
token parameters. Send exactly one JSON text frame within five seconds:

```json
{"token":"opaque web or agent credential","after_id":0}
```

The encoded frame must be at most 4096 bytes. No extra keys, negative, boolean,
string or out-of-range cursors are accepted. Credentials retain the existing
web/agent domain permissions. WebSocket provides notifications only; perform
business operations and fetch authorized state through HTTP/MCP. Credentials
are never echoed. After authentication, no additional client frames are accepted.
Native clients may omit Origin. Browsers must present the configured exact HTTP
origin; duplicate Host/Origin, mismatched hosts/origins and `Sec-Fetch-Site:
cross-site` are rejected. Without a configured origin only the actual loopback
host and server port are allowed. Public deployments use the configured public
origin. Configure the listener's transport frame limit as well to bound buffering
before the ASGI application receives a frame.
The hosted launcher sets a 4096-byte transport limit, four-frame receive queue and 15-second ping interval
and timeout; local launchers should use these settings too.

Server frames:

| type | fields | Meaning |
| --- | --- | --- |
| `ready` | `protocol: 1`, `room_id`, `high_water` | Authentication accepted; replay follows. |
| `events` | `events`, `cursor`, `high_water`, `has_more`, `reset: null` | Bounded page; persist cursor after applying invalidations. |
| `heartbeat` | `cursor` | Idle keepalive, every 15 seconds by default. |
| `reset` | `reason`, `cursor` | Fetch an authorized snapshot and resume at this cursor. Reasons: `future_cursor`, `expired_cursor`. |

Each event contains only `id`, `room_id`, `topic`, `entity_id`, `action`
(`insert`, `update`, `delete`) and server-generated UTC `created_at`.
Topics include tasks, sessions, progress, messages, contracts, lifecycle,
dependencies, collaboration, git, room and identity. Multiple invalidations may
describe one transaction, and idempotent SQL updates may produce duplicates;
clients should coalesce refreshes. No message bodies, task descriptions, local
paths, request keys, credential/token hashes, OAuth data or diagnostic proofs
are included. Event identity IDs refer to members/rooms, never credential hashes.

IDs are monotonic **within a room**, starting at 1. Another room's writes create
no gaps in this room. Replay is durable across process restart. Database triggers
write events and stream counters inside the business transaction, so rollback
cannot expose committed events. An event is an invalidation, not a historical
copy of domain data. `EventStore.read(token, after_id=0, limit=100)` authenticates
each read inside the same SQLite snapshot as its page; maximum page size is 200.
No event pruning is performed. The retained-stream floor is initially zero;
future authorized retention tooling must advance it atomically before removing
history, and then old cursors receive `expired_cursor`. A future cursor receives
a reset to the room's current high-water mark, with no events from other rooms.

Trigger installation occurs after domain store initialization and never backfills
historical data. Hosted account/project invalidations are added after account and
workspace stores initialize. New domain tables must add an explicit safe entity
mapping to `EventStore.install_triggers()` and invoke installation after creating
their schema. Schema mismatches fail at initialization.

Per process/route defaults are 128 concurrent sockets including pending auth,
and four authenticated sockets per room/member/credential kind. Credentials are
revalidated before each page and every idle poll (0.5 seconds by default), including
account session, team and project revocation. One bounded page is held at a time;
send timeout is five seconds, preventing a slow reader from building an unbounded
application queue. Transport ping/pong is handled by Uvicorn's WebSocket backend,
with application heartbeats as an additional idle signal.

Close codes: `4400` malformed or unsupported frame/cursor, `4401` rejected or
revoked credential, `4403` host/origin/query rejection, `4408` first-frame/send
timeout, `4429` connection quota. Before acceptance ASGI servers may expose
boundary/quota rejection as HTTP 403 rather than a WebSocket close frame.
Budgets are per process; deployments using several workers should additionally
apply edge connection limits. Reconnect with the last applied cursor; snapshot
only when the server requests reset or the client starts from existing domain
state predating installation of the stream.

To recover without missing concurrent changes, capture the `reset.cursor`
watermark **before** fetching the snapshot, then apply the snapshot and persist
that captured cursor. Process subsequent stream frames in order after the
refresh. A concurrent write can appear in both the snapshot and a later event;
coalescing invalidations handles this safely. Never replace the captured cursor
with a later high-water value after refreshing, and never advance your persisted
cursor merely because a `ready` frame announces a high-water mark.
