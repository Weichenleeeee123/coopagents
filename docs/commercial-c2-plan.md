# C2 Subscription Implementation Plan

> Use subagent-driven-development sequentially: one implementer, then independent specification and quality reviews per stage. Never delete files. Retain isolated test databases under ignored `.local/`. The user approved implementation on 2026-10-11; C3 stays deferred.

**Goal:** Ship configurable cloud team subscriptions with a Stripe adapter, persistent event recovery, accurate quota enforcement and account billing UI, preserving unrestricted self-hosting.

**Architecture:** A billing domain shares SQLite transactions with workspace writes. A separate Stripe adapter handles bounded HTTPS and signed events; a coordinator reconciles canonical provider state without holding database write locks. Account routes and billing UI expose only team-authorized data. No provider credentials or real prices are assumed.

**Stack:** Existing Python/SQLite/Starlette/vanilla JavaScript; fixed Stripe REST API version, standard-library HTTPS and HMAC verification.

## 1. Subscription domain and workspace capacity

Create `src/billing.py`, `tests/test_billing.py`, `docs/c2-domain.md`; modify `src/workspaces.py` narrowly.

- [x] Write retained-database behavioral tests first: member/project capacity, concurrent final-slot claims, invite rollback, migration capacity, owner-only billing, cross-team denial, downgrade preservation and unrestricted self-hosting.
- [x] Add `BillingStore(workspaces, mode='self-hosted', catalog=None)` and additive tables for team customer/subscription bindings, checkout attempts, event jobs and synchronization revisions. Catalog supplies explicit positive integer Free/Team member/project limits and a Team monthly price ID; no embedded commercial prices.
- [x] Add a workspace capacity callback, defaulting to no restriction, invoked inside the existing writer transaction before `create_project`, `claim_legacy_project` and membership creation/reactivation in `accept_invite`. Count active team accounts and bound projects. Reject capacity with a typed conflict and preserve invites/accounts on rollback.
- [x] Expose authorized `summary(session, team_id)` and `require_owner(session, team_id)`; separate internal trusted binding/checkout/event/snapshot methods. No public setter may grant paid state from an account request. Document exact domain interfaces for the next stage.
- [x] Persist provider customer IDs uniquely with team and mode; one current subscription and one unresolved checkout per team. Durable jobs use unique event IDs, leased claims, generation-checked results and bounded retry metadata. Never mark a job processed before applying a valid snapshot.
- [x] Normalize snapshots to current subscription ID, customer ID, price, mode, status, latest invoice, paid period end, cancellation and risk hold. Team entitlement requires matching configured price, active status, paid current invoice, unexpired period and no current risk hold; otherwise Free. Self-hosted and unconfigured cloud show disabled billing/unrestricted capacity without claiming paid state.
- [x] Run `python -m unittest discover -s tests -p 'test_billing.py' -v` and workspace regression; spec review then quality review; root commits domain stage.

Concrete behavioral pattern (using retained fixture owner/team):

```python
before = workspaces.list_projects(owner_session, team_id)
with self.assertRaises(Conflict):
    workspaces.create_project(owner_session, team_id, 'beyond capacity')
self.assertEqual(before, workspaces.list_projects(owner_session, team_id))
```

## 2. Stripe adapter and durable synchronization

Create `src/stripe_billing.py`, `src/billing_service.py`, `src/billing_config.py`, `tests/test_stripe_billing.py`, `tests/test_billing_service.py`, `docs/c2-stripe.md`.

Implementation refinement: keep canonical subscription/payment verification in `src/stripe_snapshot.py`, persistent outbound request coordination in `src/billing_operations.py`, and shared canonical checkout recovery/expiry in `src/billing_checkout.py`. These focused modules remain in flat `src/` and implement this stage's existing scope; they add no payment provider or public debug surface. Independent review requires complete current-period invoice-line evidence and provider-side expiry of obsolete open checkout sessions before treating their reconciliation as complete.

Provider compatibility refinement: fix Checkout to the verified Price's base currency, including when alternate currency options exist. Preserve Stripe-generated opaque URL fragments only for exact HTTPS `checkout.stripe.com` destinations; Portal validation remains separate. Server and browser validators must agree while retaining host, credential, port, control-character and length checks. The official response example and manual currency documentation are recorded in `docs/c2-stripe-reference.md`.

- [x] Write failing tests for raw-body signatures, timestamp tolerance, mode mismatch, duplicate/malformed signature headers, provider ID/mode binding, bounded responses/timeouts, no redirects and safe error messages. Test transport fixtures only; production contains no mock-payment adapter.
- [x] Validate explicit config: key/secret file sources mutually exclusive and bounded, catalog limits required when enabled, cloud only, expected mode `test|live`, expected monthly Price. Read provider Price server-side before enabling checkout and display its actual currency/amount/interval. Missing entire config disables billing; partial/invalid config fails.
- [x] Use fixed `https://api.stripe.com/v1/` endpoints with a documented pinned Stripe-Version. Provide customer create/retrieve, checkout create/retrieve/expire, portal creation, subscription/invoice/payment/risk lookup. All writes have persistent idempotency keys. Response size and time are bounded; errors omit raw provider payload and secrets.
- [x] Checkout uses quantity 1 monthly subscription, server-owned customer/team binding and canonical return URL with fragment, no client-supplied price/customer/redirect. Persist attempt before remote call, reuse unresolved attempts, reconcile completed/expired sessions before opening another. Recheck current owner before outbound account-authorized calls.
- [x] Verify signature against original bytes and a five-minute tolerance before parsing trusted events; validate mode. Persist only necessary event identifiers and reconcile work before returning success. Resolve event objects through trusted provider lookup and stored bindings, never by incoming team metadata alone.
- [x] Reconcile latest provider subscription/invoice and current invoice charge refunds/disputes. Full current-invoice refunds or unresolved disputes pause paid rights; partial/history refunds do not cancel current rights. Re-fetch current risk state so obsolete events cannot permanently freeze a new period. Use persisted generation/lease guards across concurrency/restart; transient failures remain retryable.
- [x] Run focused adapter/service tests, including duplicate and out-of-order events, stale result races, crash/restart retries, owner demotion, repeated checkout and provider failure. Review spec then quality; root commits stage.

Signature implementation contract:

```python
signed = str(timestamp).encode('ascii') + b'.' + raw_body
expected = hmac.new(secret.encode('ascii'), signed, hashlib.sha256).hexdigest()
valid = any(hmac.compare_digest(expected, candidate) for candidate in signatures)
```

Only valid signatures inside tolerance proceed to JSON and event persistence.

## 3. HTTP, background processing and recovery command

Create `src/billing_api.py`, `src/billing_admin.py`, `tests/test_billing_api.py`; modify `src/api.py`, `src/server.py` and configuration/lifespan integration.

- [ ] Add read `/account/teams/{team_id}/billing` and owner-only POST suffixes `/checkout`, `/portal`, `/sync`. Reuse strict account cookie parsing and Origin/CSRF rules; bearer-only requests cannot access billing. Return safe typed errors and preserve valid sessions on role denial.
- [ ] Mount exact `/billing/stripe/webhook` only when configured cloud billing is enabled. Require signature; no cookie/CSRF requirement for provider callbacks. Preserve existing Host/body/query boundary. Unknown or irrelevant valid events are safely acknowledged without granting rights.
- [ ] Start a bounded worker from app lifespan to retry durable event jobs and restore pending work after restart; synchronous provider I/O runs off event loop. Failed provider requests must not block unrelated project/MCP requests. Stop only owned worker on shutdown without deleting evidence.
- [ ] Add local maintenance command for bounded retry and reconciliation of stored teams; existing DB only, no fake subscription setters, no secrets in command args/output. Document exit statuses and recovery after provider outage.
- [ ] Test full HTTP cookie/CSRF/role/tenant matrix, disabled self-hosted routes, signed callback persistence, failed processing/retry and current C1 behavior. Review spec then quality; root commits stage.

Route behavior is verified by actual HTTP requests against unique retained databases, with test transport stubs scoped inside tests. Browser return requests never mutate entitlement.

## 4. Billing interface

Create `src/static/billing.js`, `tests/billing_ui_regression.js`; modify static index/accounts/styles, asset whitelist and web tests.

- [ ] Add English `Plan & billing` section inside team hub with current plan, actual usage/limits, verified Price, subscription status/paid-through, last-sync and safe errors. Show unrestricted self-hosted or unconfigured cloud truthfully; hide unavailable purchase controls.
- [ ] Only owner sees checkout/portal/sync controls. Use server-returned validated HTTPS destinations; no local success/paid setter. A return fragment displays awaiting confirmation and refreshes through authorized server state.
- [ ] Integrate account epoch and abort lifecycle: switching team/account clears billing and prevents delayed fetch/JSON or checkout URLs from the previous team redirecting the new context. Use `textContent`, accessible controls and wrapping at narrow widths.
- [ ] Run both existing JS regressions, new meaningful billing lifecycle tests and real browser QA for disabled/self-hosted and configured fixture states. Review spec then quality; root commits UI.

## 5. Packaging, operations docs and acceptance

Update `.env.example`, CI, deployment docs, README, changelog and indexes; create `docs/commercial-c2-report.md`. Keep flat `src/`; use candidate version `0.4.0rc1` after completed verification, preserving previous release assets.

- [ ] Document catalog/key/secret configuration, provider event registration, test/live boundaries, duplicate/retry recovery, quota rules and C3 pause. No made-up prices, successful payments, deployment or provider sandbox evidence.
- [ ] Run fresh full Python suite, experiment regressions, JS checks, build/install and container/TLS acceptance relevant to changed lifespan/routes. Inspect exact candidate CI results; retain all local evidence.
- [ ] Independently review full C2 authorization, event ordering, checkout idempotency and self-hosting behavior; fix all important findings and rerun affected checks.
- [ ] Commit and push stages; record verified counts/commits and missing real Stripe sandbox credentials if unavailable. Publish a clearly labeled candidate only when checks pass; never overwrite prior artifacts.

## Execution decisions

Continue in the user's existing clean project checkout/feature branch, as in C1, with serial implementers and independent reviewers. The root coordinator owns Git commits and public pushes. Provider credentials are optional for code implementation and required for claiming real sandbox success. Never read or expose unrelated local credentials. No C3 deployment or real charge is authorized by this plan.
