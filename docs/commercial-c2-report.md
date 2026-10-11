# C2 implementation and acceptance

Date: 2026-10-11 (Asia/Taipei). Status: implementation in progress; this is not a release or deployment acceptance claim. The user approved overseas team subscriptions using Stripe, complete MIT source and unrestricted self-hosting. C3 public deployment and operations remain deferred.

## Stage evidence

| Stage | Current evidence | Status |
| --- | --- | --- |
| Billing domain and transactional capacity | 32 billing tests, 17 workspace regression tests; independent specification and quality reviews passed | Complete |
| Stripe transport and durable synchronization | Official API references recorded in `c2-stripe-reference.md` | Implementation pending |
| HTTP, worker and maintenance command | Planned account authorization and exact signed callback route | Implementation pending |
| Billing interface | Planned English team billing section with account lifecycle guards | Implementation pending |
| Candidate packaging and full acceptance | Existing C1 evidence does not replace C2 checks | Pending |

The domain regression suite covers final-slot concurrency, invitation/account rollback, legacy project capacity, current team authorization, downgrade preservation, stable customer/checkout keys, provider bindings, duplicate events, lease and generation guards, and fresh-process recovery. An independent review reproduced a late event lookup failure overwriting a newer successful team's error status; `retry_job` now records only event/audit errors, while generation-checked `fail_sync` owns team errors. The added regression passes. A second review found checkout completion arriving after a canonical subscription snapshot could leave an unresolved attempt. Recovery now handles either arrival order and concurrent writes without granting paid rights from checkout confirmation alone; all 32 domain tests pass.

All isolated SQLite databases remain under ignored `.local/c2-domain-tests/` or the existing workspace test evidence directory. No real payment bodies, credentials or machine configuration are committed.

## External verification boundaries

The user currently has no Stripe test account available. No real Stripe sandbox Checkout, charge, Portal, refund, dispute or externally delivered webhook is claimed. Transport fixtures and signed local callback tests will verify application behavior; eventual merchant credentials are required for separate provider acceptance.

No C3 deployment or live charge is performed in this phase. Existing native Codex MCP cancellation and complete native agent-loop limitations remain subject to their earlier reports; a billing implementation does not resolve them.

Approved scope: [design](commercial-c2-design.md), [plan](commercial-c2-plan.md). Domain interfaces: [contract](c2-domain.md).
