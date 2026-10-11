# C2 implementation and acceptance

Date: 2026-10-11 (Asia/Taipei). Status: implementation in progress; this is not a release or deployment acceptance claim. The user approved overseas team subscriptions using Stripe, complete MIT source and unrestricted self-hosting. C3 public deployment and operations remain deferred.

## Stage evidence

| Stage | Current evidence | Status |
| --- | --- | --- |
| Billing domain and transactional capacity | 32 billing tests, 17 workspace regression tests; independent specification and quality reviews passed | Complete |
| Stripe transport and durable synchronization | 17 adapter/configuration, 55 coordinator and 34 domain tests; full 240-test application regression passed | Complete; independent specification and quality reviews passed |
| HTTP, worker and maintenance command | Planned account authorization and exact signed callback route | Implementation pending |
| Billing interface | Planned English team billing section with account lifecycle guards | Implementation pending |
| Candidate packaging and full acceptance | Existing C1 evidence does not replace C2 checks | Pending |

Domain source commit: `fe5b431`. [Its exact CI run](https://github.com/Weichenleeeee123/crewmesh/actions/runs/38121842217) passed both Python 3.11 and 3.13 with 166 application tests and 21 integration experiment tests each, JavaScript regressions, package builds, and the actual container/Caddy TLS smoke. This verifies the domain stage only; the final C2 candidate must run fresh checks after the remaining implementation.

The domain regression suite covers final-slot concurrency, invitation/account rollback, legacy project capacity, current team authorization, downgrade preservation, stable customer/checkout keys, provider bindings, duplicate events, lease and generation guards, and fresh-process recovery. An independent review reproduced a late event lookup failure overwriting a newer successful team's error status; `retry_job` now records only event/audit errors, while generation-checked `fail_sync` owns team errors. The added regression passes. A second review found checkout completion arriving after a canonical subscription snapshot could leave an unresolved attempt. Recovery now handles either arrival order and concurrent writes without granting paid rights from checkout confirmation alone; all 32 domain tests pass.

All isolated SQLite databases remain under ignored `.local/c2-domain-tests/` or the existing workspace test evidence directory. No real payment bodies, credentials or machine configuration are committed.

The Stripe stage uses transport fixtures with real retained SQLite ledgers. Independent review found transformed Prices that could bill zero, unrelated customerless charge events retrying indefinitely, old or foreign Price invoice evidence granting current rights, and competing open Checkout links remaining payable. Their fixes have failing-then-passing regressions: strict Price validation, canonical customerless-event classification, complete invoice lines tied to the current item and service period, and provider-side Checkout expiry with stable keys and completion-race recovery. The root independently ran all 234 application tests successfully; retained evidence is `.local/c2-task2-final-0967ab59-f171-4e9a-8cd6-8f871f8ac483.log`.

Quality re-review then reproduced a multi-currency Price charging in a currency rejected by the fixed-base-currency verifier. Checkout now explicitly pins the verified base currency and disables Adaptive Pricing; canonical sessions must match it before return, recovery or expiry. Official provider URLs with opaque Checkout fragments now survive storage and restart, while Portal URLs remain strict. Their regressions were observed failing first; specification re-review passed eight focused checks and additional canonical-currency recovery probes. The root reran the expanded application suite: 240 tests passed in `.local/c2-task2-currency-d8d3fbba-bb6c-4a88-9471-9fca1e785bb0.log`. Final independent quality re-review passed six focused currency/URL regressions and confirmed both earlier P1 fixes remain intact.

## External verification boundaries

The user currently has no Stripe test account available. No real Stripe sandbox Checkout, charge, Portal, refund, dispute or externally delivered webhook is claimed. Transport fixtures and signed local callback tests will verify application behavior; eventual merchant credentials are required for separate provider acceptance.

No C3 deployment or live charge is performed in this phase. Existing native Codex MCP cancellation and complete native agent-loop limitations remain subject to their earlier reports; a billing implementation does not resolve them.

Local Docker Engine is currently unavailable: the Docker client cannot open `dockerDesktopLinuxEngine`. The domain-stage container/TLS result above comes from the actual GitHub CI runner, not a local or mocked Docker run. The final candidate still requires its own exact CI verification.

Approved scope: [design](commercial-c2-design.md), [plan](commercial-c2-plan.md). Domain interfaces: [contract](c2-domain.md).
