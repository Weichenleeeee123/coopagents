# C1 account HTTP and OAuth contract

`self-hosted` is the default runtime mode. It uses local usernames and passwords and requires an explicitly configured bootstrap secret for the first account even on loopback. `cloud` disables local bootstrap/login/password changes, local invitation registration, administrative local password reset, and anonymous legacy room creation/redemption. Existing bearer APIs retain their credential semantics. Private deployments do not contact an official licensing, billing, or account service.

Account sessions use `coopagents_account` (`HttpOnly`, `SameSite=Lax`, `Path=/`, seven day `Max-Age`; `Secure` with an HTTPS public origin). Duplicate account cookies are denied. Tokens never appear in account JSON. `GET /account/session` returns `{account, csrf_token, expires_at}`. All unsafe account requests require exactly one matching canonical `Origin`; authenticated session writes additionally require exactly one `X-Coopagents-CSRF`. Password login and initial bootstrap use their own credentials regardless of a stale single cookie. `/account/session` clears an invalid cookie; logout clears missing or invalid sessions idempotently after the Origin check, while valid-session logout still requires CSRF. Permission failures on other routes do not clear a valid session. Bearer credentials cannot substitute for an account cookie. Body fields are strict; team/project/account IDs come exclusively from route parameters.

| Method | Path | Body / result |
|---|---|---|
| GET | `/account/config` | `mode`, `local_login_enabled`, `bootstrap_enabled`, `github_oauth_enabled` |
| POST | `/account/bootstrap` | `username`, `password`, optional `display_name`; `X-Coopagents-Bootstrap` required |
| POST | `/account/login` | `username`, `password`; session cookie and public session JSON |
| POST | `/account/logout` | `{}`; revoke session and clear cookie |
| POST | `/account/password` | `current_password`, `new_password`; revoke sessions and clear cookie |
| GET/POST | `/account/teams` | List teams / create with `name` |
| GET/POST | `/account/teams/{team_id}/projects` | Accessible projects / create with `name`, optional `repository` |
| GET | `/account/teams/{team_id}/managed-projects` | Manager metadata with `has_access`; grants no project context access |
| GET | `/account/teams/{team_id}/members` | Current team members |
| POST | `/account/teams/{team_id}/invites` | Optional `role` (default member), `project_ids` (default empty; at most 200 nonempty UTF-8 strings of at most 120 characters) |
| POST | `/account/invites/accept` | Existing session: only `invite_token`; anonymous self-hosted: `invite_token`, `username`, `password`, optional `display_name` |
| POST | `/account/teams/{team_id}/members/{account_id}/role` | `role` |
| POST | `/account/teams/{team_id}/members/{account_id}/remove` | `{}` |
| POST | `/account/teams/{team_id}/members/{account_id}/reset-password` | `new_password`; domain role/exclusive-team restrictions apply |
| POST | `/account/teams/{team_id}/claim` | `owner_web_token`; proven legacy owner only |
| POST | `/account/projects/{room_id}/select` | `{}`; scoped `room_id`, `member_id`, `web_token`, `expires_at` |
| POST | `/account/projects/{room_id}/members/{account_id}/grant` | `{}` |
| POST | `/account/projects/{room_id}/members/{account_id}/remove` | `{}` |

Passwords and provider requests run in a threadpool, with two concurrent account operations per app and immediate HTTP 503 when busy. Local login and anonymous invitation registration share persisted 60 second username/IP attempt windows (20 username, 60 IP); only the ASGI client address is used. The table holds at most 10,000 keys and reuses expired entries. Saturation denies new keys until an expired entry becomes available. These controls bound expensive work without permanent account lockout; multi-process deployments do not share the in-process concurrency semaphore.

Cloud GitHub OAuth requires `COOPAGENTS_MODE=cloud`, `COOPAGENTS_PUBLIC_URL`, `COOPAGENTS_GITHUB_CLIENT_ID`, and either `COOPAGENTS_GITHUB_CLIENT_SECRET` or `COOPAGENTS_GITHUB_CLIENT_SECRET_FILE`. Partial configuration and simultaneous secret sources fail startup. File reads are bounded; there are no default provider credentials. The registered callback must exactly equal the canonical HTTPS origin plus `/account/oauth/github/callback`.

`GET /account/oauth/github/start` rejects cross-site Fetch Metadata or a mismatched Origin and redirects to the fixed GitHub authorize endpoint with empty scope, opaque state and S256 PKCE. A separate Secure HttpOnly Lax browser cookie binds state. Hashed states, hashed browser values and server-side PKCE verifiers persist privately for ten minutes; state consumption is atomic and precedes provider exchange. Consumed rows clear the verifier. The state table is capped at 10,000 rows, reusing expired/consumed rows, and start requests use the IP throttle.

The callback permits only `state` plus `code` or `error`, with no duplicate query keys. Provider exchanges use fixed HTTPS endpoints, no redirects, ten second timeouts and 64 KiB response limits. Provider access tokens are used for `/user` only and never stored, returned or logged. Only GitHub's positive numeric user ID links identities; login names and emails cannot join an existing local account. Success redirects to `/`; failures clear the state cookie and return a sanitized error.

GitHub's [OAuth app authorization documentation](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps), checked 2026-10-11, documents S256 PKCE. Tests exercise local HTTP and mocked provider protocol/state behavior. Real GitHub sign-in has not been verified because operator OAuth credentials are absent.
