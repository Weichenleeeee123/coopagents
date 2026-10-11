# C2 billing domain contract

The billing domain is implemented in `src/billing.py`; provider transport belongs to the next Stripe adapter. The domain uses only the Python standard library and the existing workspace SQLite database. It does not contact Stripe, expose a request-controlled paid setter, persist provider payloads, or need a Stripe account. C3 remains deferred.

## Construction and configuration

```python
BillingCatalog(free_members: int, free_projects: int, team_members: int,
               team_projects: int, team_monthly_price_id: str, provider_mode: str)
BillingStore(workspaces: WorkspaceStore, mode: str = 'self-hosted',
             catalog: BillingCatalog | None = None)
```

All four limits are explicit positive integers (booleans are rejected), at most 1,000,000,000. Team limits must cover Free limits. The monthly Price identifier must be nonempty; provider mode is exactly `test` or `live`. Deployment mode is exactly `self-hosted` or `cloud`. Only cloud with a configured catalog enables billing and quotas. Self-hosted and unconfigured cloud are unlimited and never report paid status. Existing billing team bindings prohibit changing the database's provider mode. A deterministic SHA-256 catalog ID records the nonsensitive catalog configuration.

## Account-authorized methods

```python
summary(session_token: str, team_id: str) -> dict
require_owner(session_token: str, team_id: str) -> dict
```

`summary` resolves a current account session and requires current active team membership. It returns `team_id`, `mode`, `enabled`, `plan` (`unlimited`, `free`, or `team`), `paid`, `limits`, `usage`, `can_manage`, `over_limit`, `status`, `paid_until`, `cancel_at_period_end`, `risk_hold`, and `last_sync`. Limits and usage each contain `members` and `projects`; unlimited limits are `None`. Only owners also receive `billing` with customer/subscription identifiers, provider mode, and a classified last error. `require_owner` resolves the same live membership and returns the authenticated account only for the current owner role. Role changes and removal take effect immediately; cross-team access fails with `AccessDenied`.

All methods below are **trusted server-internal methods**. The adapter must authorize the owner before owner-triggered transport or mutation. It must never deserialize request bodies into claims or snapshots, accept customer IDs chosen by the browser, or expose these methods directly as account APIs.

## Durable customer and checkout operations

```python
customer_state(team_id: str) -> dict
bind_customer(team_id: str, customer_id: str, *, provider_mode: str) -> dict
team_for_customer(customer_id: str, *, provider_mode: str) -> str | None
reserve_checkout(team_id: str, *, lease_seconds: int = 60,
                 refresh: bool = False) -> CheckoutReservation
update_checkout(reservation: CheckoutReservation, *, status: str,
                checkout_id: str, checkout_url: str | None = None,
                expires_at: int | None = None,
                subscription_id: str | None = None) -> bool
```

`customer_state` lazily inserts a team billing binding and returns `team_id`, `provider_mode`, `customer_id`, `customer_key`, and `created_at`. The adapter uses the persisted `customer_key` for remote creation retries. It is stable across threads, store reconstruction, and fresh processes. A bound customer cannot change, and `(provider_mode, customer_id)` is unique.

`CheckoutReservation` is a frozen dataclass with fields `attempt_id`, `team_id`, `customer_id`, `idempotency_key`, `created_at`, `status`, `claimed`, `lease_token`, `lease_until`, `checkout_id`, `checkout_url`, `expires_at`, and `subscription_id`. Integer times are UTC Unix seconds. Lease duration is 1–3600 seconds. Only `claimed=True` grants authority to perform the next provider operation; another request can reuse a known open URL without creating a new session.

At most one `pending`, `open`, or `complete` checkout exists per team. Reclaiming an expired local lease retains its attempt and idempotency key, even when a remote create outcome is uncertain. `refresh=True` requests a lease to retrieve the same known session; it does not create a new attempt. A fresh attempt becomes available only after the adapter confirms remote expiry and writes `expired`. Local time passing or a network failure is insufficient. The adapter must reconcile uncertain remote creates and respect the provider's idempotency retention window; reusing a persisted key is not proof the provider still remembers it. Do not blindly create again when that window has elapsed.

`update_checkout` accepts `open`, `complete`, or `expired`; `open` requires an HTTPS URL and expiry. Provider IDs cannot change after binding; checkout IDs are globally unique, stronger than mode uniqueness because a billing database has one configured provider mode. A checkout cannot record a subscription already bound to another team. Complete cannot move backwards. Stale/unclaimed/expired lease writes return `False`; binding violations raise `Conflict`. Complete by itself gives no entitlement. Applying a canonical snapshot confirms a complete checkout only when its stored subscription ID matches the snapshot. When that snapshot arrives first, a subsequent complete update instead writes `confirmed` immediately if the verified current snapshot has the same team/customer/mode/subscription. This resolves both arrival orders transactionally, including races, without changing paid status. An existing nonterminal subscription blocks starting another checkout; `reserve_checkout(refresh=True)` may still claim an existing unresolved attempt to retrieve its remote state and finish reconciliation, but cannot create a new attempt.

## Verified snapshots and reconciliation

```python
SubscriptionSnapshot(customer_id: str, subscription_id: str | None,
                     price_id: str | None, provider_mode: str, status: str,
                     current_invoice_id: str | None,
                     paid_invoice_id: str | None, paid_period_end: int | None,
                     cancel_at_period_end: bool, risk_hold: bool)
current_snapshot(team_id: str) -> SubscriptionSnapshot | None
list_bound_teams(*, limit: int = 100,
                 after_team_id: str | None = None) -> list[dict]
start_sync(team_id: str, *, job: EventJob | None = None,
           lease_seconds: int = 120) -> SyncClaim
apply_snapshot(claim: SyncClaim, snapshot: SubscriptionSnapshot) -> bool
fail_sync(claim: SyncClaim, error_code: str, *, retry_delay: int = 60) -> bool
```

`SubscriptionSnapshot` is frozen. Supported statuses are `none`, `incomplete`, `incomplete_expired`, `trialing`, `active`, `past_due`, `canceled`, `unpaid`, and `paused`. Only `none` has no subscription ID; it must not carry price/invoice/paid-period fields. All flags must be actual booleans. The adapter constructs a snapshot only after retrieving and verifying canonical provider relationships, configured monthly Price, current invoice, paid service-period end, mode, and current invoice refund/dispute risk. Provider event bodies and browser success redirects are not entitlement evidence. An unrecognized price or unpaid/nonactive status may be persisted as a valid snapshot but grants Free.

Team entitlement requires an active snapshot with matching persisted customer and subscription bindings, configured mode and Price, a current invoice whose ID matches the verified paid invoice, a future `paid_period_end`, and no risk hold. `cancel_at_period_end=True` retains Team until paid time expires. Expiry is checked during each summary/capacity operation without needing a new event. Downgrades preserve all existing members, projects, credentials and context; they block new capacity consumption when current usage reaches/exceeds the new Free limit.

`current_snapshot` reads the latest verified state without creating bindings or changing entitlement. Unknown team IDs fail with `AccessDenied`. `list_bound_teams` returns bounded keyset pages sorted by `team_id`, containing `team_id`, `customer_id`, `provider_mode`, `last_sync`, and `last_error`. Limit is 1–1000. Only bound customers in the configured mode are returned; use the last team's ID as the next cursor. This inventory does not grant a public account discovery API.

`SyncClaim` fields are `team_id`, `customer_id`, `provider_mode`, `generation`, `lease_token`, `lease_until`, and optional `job`. Each `start_sync` increments the persistent team generation and supersedes previous claims. Provider retrieval must follow claim acquisition so a newer claim does not apply an older pre-fetched state. `apply_snapshot` validates generation/token/sync lease and the event lease, if present. Stale work returns `False` and cannot change the snapshot or mark an event processed. Customer/mode/cross-team subscription violations raise an error and roll back. A different subscription can replace only `none`, `canceled`, or `incomplete_expired` current state; reconcile the old nonterminal subscription first. Historical subscription bindings remain reserved for their original team.

`fail_sync` accepts only current live claims. It stores a classified error, releases the current sync lease, atomically retries the associated event if present, and preserves the previous verified snapshot and last successful sync time. Superseded/expired failures return `False`. A later successful snapshot clears the error. `retry_delay` is 0–604800 seconds. Error and reason arguments must be short safe identifier codes chosen by the adapter, never raw exception strings, request bodies, tokens, or provider error payloads.

## Authenticated event queue

```python
ingest_event(event_id: str, *, event_type: str, object_id: str,
             provider_mode: str, customer_id: str | None = None,
             subscription_id: str | None = None) -> bool
claim_job(*, lease_seconds: int = 120) -> EventJob | None
retry_job(job: EventJob, error_code: str, *, retry_delay: int = 60) -> bool
ignore_job(job: EventJob, reason: str) -> bool
event_state(event_id: str) -> dict | None
```

Only call `ingest_event` after authenticating the provider signature and checking mode. It retains minimal identifiers and returns `True` for a new pending job, `False` for an identical duplicate, and raises `Conflict` if an event ID is reused with different identifiers. `EventJob` fields are `event_id`, `event_type`, `object_id`, `provider_mode`, `customer_id`, `subscription_id`, `attempts`, `lease_token`, and `lease_until`. The queue claims due pending jobs or recovers expired processing jobs atomically; attempts increase on every claim. Events transition `pending → processing → processed` only after a valid canonical snapshot is applied. Authenticated unsupported events may become `ignored`, which does not mean successful synchronization.

`retry_job` is for failures before obtaining a sync claim. It updates only the event retry/error and its audit; it cannot change the team's last error or overwrite a newer successful synchronization, even when the event retains an earlier team association. After `start_sync`, use generation-guarded `fail_sync`, the only failure method that writes the team's error. An event whose customer is not yet bound must remain retryable in the adapter; a webhook can arrive before local customer binding completes. `start_sync` checks event/customer/subscription/team coherence. Event times do not order snapshots: current canonical retrieval plus generation checks handles delayed and out-of-order delivery. `event_state` returns `event_id`, `state`, `attempts`, `next_attempt`, `last_error`, `received_at`, `processed_at`, and `team_id` for internal diagnostics.

## SQLite schema and workspace hooks

Construction uses additive `CREATE TABLE/INDEX IF NOT EXISTS` statements in the existing database. It preserves C1 teams/projects and can be repeated. There is no drop/delete migration.

| Table | Key and persisted state |
| --- | --- |
| `billing_catalogs` | SHA-256 `id` primary key; JSON `configuration`, `created_at` |
| `billing_teams` | `team_id` primary key/FK; `provider_mode`, nullable customer, unique `customer_key`, `created_at`, generation, sync token/until, last sync/error, catalog FK; unique mode/customer |
| `billing_subscription_bindings` | Primary key mode/subscription; team FK; preserves all historical team bindings |
| `billing_subscriptions` | Team primary key/FK; snapshot fields, `synced_at`, generation; unique mode/subscription |
| `billing_checkouts` | Attempt primary key; team FK, customer, unique idempotency key, creation time, status, lease fields, unique checkout ID, URL, remote expiry, subscription ID; partial unique unresolved-team index |
| `billing_events` | Event primary key; minimal type/object/mode/customer/subscription IDs, state, received time, attempts, retry time, lease fields, classified error, processed time, nullable team FK; pending-job index |
| `billing_audit` | Integer primary key; optional team/event IDs, action, classified result, generation, creation time; no raw bodies |

Billing construction installs `workspaces.capacity_check = billing.check_capacity`. The hook signature is `check_capacity(c: sqlite3.Connection, team_id: str, resource: str) -> None`, with resource exactly `members` or `projects`. `WorkspaceStore` retains a no-op default for complete self-hosted use without billing construction. Each service process must attach its configured BillingStore before exposing workspace mutations.

`create_project` calls the hook after manager authorization and before room/member/project inserts. `claim_legacy_project` calls it after checking the unbound legacy owner's credential and before binding. `accept_invite` calls it after resolving/creating the account and checking that an active membership does not already exist, before creating or reactivating membership. All hooks run inside the caller's existing `BEGIN IMMEDIATE`, on its connection. Active owners/admins/members each consume a slot; pending invitations do not. A capacity rejection rolls back a newly created account, invitation consumption, project state, and grants together. Independent workers racing for the final slot have one winner.

## Validation evidence

Focused domain tests retain unique databases under ignored `.local/c2-domain-tests/`; workspace tests retain their C1 databases. Coverage includes member/project final-slot races, invitation/account rollback, reactivation and legacy claims, current authorization, downgrade and unlimited behavior, provider bindings, checkout uncertain-create recovery, authenticated-event dedup/retry, generation/lease rejection, bounded maintenance reads, manual/event failure preservation, and fresh-process recovery. There is no claimed external Stripe payment evidence in this stage.

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_billing.py -v
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_workspaces.py -v
```
