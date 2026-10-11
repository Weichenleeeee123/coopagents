# C1 Account and Workspace Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement sequential tasks, with independent specification and quality reviews. Never delete files; retain test evidence under ignored `.local/`. Work in the user's existing repository on `feat/crewmesh-integration`.

**Goal:** Deliver the approved open source account, team and multi-project foundation without changing existing agent workflows.

**Architecture:** Add account and team tables to the existing SQLite database. Account sessions authorize team control operations; project operations continue to use scoped project credentials. The web interface obtains personal project access only after server-side membership checks. Self-hosted authentication remains entirely local; cloud GitHub OAuth requires explicit deployment configuration.

**Tech Stack:** Python standard library, SQLite, Starlette, vanilla JavaScript, existing MCP service and Compose/Caddy deployment.

## Task 1: Account and team domain

Files: create `src/accounts.py`, `src/workspaces.py`, `tests/test_accounts.py`, `tests/test_workspaces.py`; adjust `src/identity.py` only for transactional revocation/disabled-member enforcement if necessary.

- [x] Write retained-database unittest cases before implementation. Verify password hashing, normalized unique usernames, failed logins, session expiration/logout/reset, two-team isolation, invite expiry and single consumption, project-specific membership, administrator restrictions and last-owner protection.
- [x] Implement `AccountStore(identity)` with local bootstrap/register-through-invite, login, session lookup/logout, administrator-assisted password reset. Store only salted scrypt hashes and hashed opaque session/CSRF credentials. Sessions expire after seven days. Password length is 12–256 characters; usernames are normalized and bounded. No implicit privileged account lookup by name.
- [x] Implement `WorkspaceStore(accounts)` with team creation/listing, member listing/invitation, role changes/removal, project creation/listing and owner-token-based legacy claim. Cloud authenticated accounts may create teams; self-hosted new accounts require bootstrap or an invitation. Invitations select explicit project scopes and expire in 24 hours. Every write rechecks actor permission inside its transaction.
- [x] Project membership maps account IDs to existing member IDs. New projects grant access only to their creator until explicitly granted. Legacy claim binds only the proven owner; existing legacy collaborators keep their existing credentials but gain no account permissions automatically. Team removal revokes all mapped project credentials and pending invitations created by that member; demotion invalidates prior admin invitations. Preserve historical rows.
- [x] Run `python -m unittest discover -s tests -p 'test_accounts.py' -v` and corresponding workspace tests; expected all pass. Review spec then quality; commit `feat: add local accounts and isolated team workspaces`.

## Task 2: HTTP sessions and configured OAuth

Files: create `src/account_api.py`, `src/oauth.py`, `tests/test_account_api.py`, `tests/test_oauth.py`; modify `src/api.py`, `src/server.py`, `src/config.py`.

- [x] Test cookie-based authentication, unsafe requests without matching Origin/CSRF, forged team IDs, project-token/agent-token escalation, legacy paths, unconfigured OAuth, one-use state and callback failure before implementation.
- [x] Mount `/account/*` routes for configuration/session/bootstrap/login/logout/teams/invites/projects/roles/removal/password reset. Keep existing `/api/*` unchanged. Exchange authorized project selection for personal expiring web credentials without exposing account cookies to project/MCP callers. HTTP errors never return passwords, cookies or provider tokens.
- [x] Use HttpOnly SameSite=Lax account cookies, Secure on public HTTPS; require matching Origin and session-bound CSRF header on authenticated writes. Bootstrap has explicit secret authorization even locally; configuration reports setup availability without exposing the secret. Cookie and bearer authorization must never be interchangeable.
- [x] Implement cloud-only GitHub OAuth using standard-library HTTPS calls, client secret from environment/file, canonical callback URL and one-use state bound to browser cookie; expire state after ten minutes. Exchange code server-side, fetch GitHub numeric user ID, link only by that ID. Never merge by email/name. Validate fixed provider endpoints; no attacker supplied redirect URI. Callback query allowance is restricted to its expected fields.
- [x] Add `CREWMESH_MODE=self-hosted|cloud`; self-hosted defaults local auth and no official network/license dependency. Invalid or partial OAuth configuration fails clearly. Keep provider credentials out of logs and ordinary responses. GitHub OAuth remote authentication cannot be marked verified without actual app configuration.
- [x] Run account HTTP/OAuth and all existing HTTP/MCP tests; review spec then quality; commit `feat: expose account sessions and configured GitHub login`.

## Task 3: Account and workspace UI

Files: modify `src/static/index.html`, `src/static/app.js`, `src/static/styles.css`; create `src/static/accounts.js`, `tests/account_ui_regression.js`.

- [x] Add real local login/bootstrap/invite acceptance and configured GitHub entry. Preserve explicit legacy credential access. Restore account sessions by fetching the server; never put passwords or account cookies in browser storage.
- [x] Add team/project switcher, create project/team, owner-proof migration, member invitation with explicit project scopes, role changes/removal and password reset controls allowed by server role. No placeholder billing UI or paid core locks.
- [x] Project selection feeds the existing safe session lifecycle; leaving or changing accounts clears project data and invalidates pending responses. Keep Kanban automatic columns and details. Show errors and empty states, support keyboard controls and small viewports; render names using textContent.
- [x] Run `node --check src/static/accounts.js`, existing web regressions and meaningful new session/CSRF/switching tests. Exercise actual web page with real isolated database and browser where available. Review spec then quality; commit `feat: add account and multi-project workspace interface`.

## Task 4: Deployment, migration and acceptance

Files: update root `compose.yaml`, `.env.example`, `README.md`, `docs/deployment.md`, `docs/app-running.md`; create `src/account_recovery.py`, recovery tests and `docs/commercial-c1-report.md`; update CI with new UI checks.

- [x] Document local bootstrap, invite-only signup, team/project permissions, legacy owner claim, password recovery, cloud provider configuration and cookie/proxy requirements. Self-hosted Compose defaults must remain usable without any official service.
- [x] Run the full Python suite, existing experiment regression, JS checks, package build/install and Docker/TLS smoke appropriate to changed configuration. Retain all outputs/evidence and never clean files/containers/volumes by deletion.
- [x] Independently review complete change for tenant isolation, session security and migration compatibility. Fix findings and rerun affected checks.
- [x] Record verified results and unresolved external validations. C1 does not include subscriptions/payment, real GitHub login without provider setup, high availability or a successful native Codex collaboration loop.
- [x] Commit and push completed stages to the already authorized public repository (`61a323b` packages deployment/recovery; final evidence recorded separately). Do not overwrite v0.2.0 release assets or claim cloud deployment.

## Acceptance status

Tasks 1–4 are implemented, reviewed and committed. Fresh full-suite/build/install/browser results and final CI TLS acceptance are recorded in [C1 report](commercial-c1-report.md). Real GitHub login requires provider credentials; official deployment and subscriptions remain deferred. Local Docker Engine is unavailable; the expanded TLS acceptance passed in GitHub CI. No deletion/cleanup is permitted.

## Execution decisions

The user approved implementation on 2026-10-11. Continue without additional workflow approval. The actual deployment target and payment provider remain deferred. Maintain flat `src/`, existing data, MIT licensing, and stage commits. Test databases must be created in unique `.local/` directories without automatic cleanup.
