# C1 domain interfaces

The account and workspace stores share the existing SQLite database. New tables are additive. All permission changes and invitation redemption run under `BEGIN IMMEDIATE`; rows are retained when membership or credentials are revoked.

`AccountStore(identity)` provides `bootstrap` (also `bootstrap_account`), `local_setup_available`, `login`, `authenticate`, `session_info`, `logout`, and `change_password`. Bootstrap creates only the first account. Local usernames use NFKC normalization and case folding. Passwords contain 12–256 characters and use scrypt with independent salts (`n=16384`, `r=8`, `p=1`). Login checks passwords outside the database writer lock and rechecks the verified hash before creating a session.

Login returns `session_token`, `csrf_token`, `expires_at`, and a public `account` object containing `id`, `username`, and `display_name`. Account sessions expire after seven days. The database contains only session token hashes. The CSRF value is the SHA-256 digest of `coopagents-csrf:` plus the opaque session token; `session_info` allows the HTTP adapter to recover it on reload without returning the session token. HTTP must validate Origin and the CSRF credential on writes. `create_session(account_id)` and `oauth_account('github', numeric_provider_id, display_name)` are trusted adapter hooks, never public arbitrary-ID login operations. Provider IDs are authoritative; display names never link existing accounts.

`WorkspaceStore(accounts)` provides:

- Team operations: `create_team`, `list_teams`, `list_members`, `change_role`, `remove_member`, and `reset_password`.
- Project operations: `create_project`, `list_projects`, `list_managed_projects`, `project_credential`, `grant_project`, `remove_project_member`, and `claim_legacy_project`.
- Invitation operations: `create_invite(session, team_id, role='member', project_ids=())` and `accept_invite(invite_token, session_token=None, username=None, password=None, display_name=None)`.

Team roles are `owner`, `admin`, and `member`. Only owners change roles or invite privileged members. Admins manage ordinary members; members may leave themselves. The last owner cannot leave or be demoted. Team membership never implicitly grants project access. Manager-only project metadata lists include `has_access`; they do not authorize project context access.

Project credentials are issued only after a current account session and both team and explicit project memberships are checked. Their expiry is capped by the issuing session, and every use checks that session again. Logout or any password reset therefore invalidates session-issued web credentials. Agent credentials remain independent of browser sessions. Removing a team or project membership revokes all mapped web and agent credentials and marks mappings inactive. Regranting access never restores revoked credentials.

Invitations last 24 hours, use hashed opaque tokens, carry explicit project scopes, and are consumed atomically. Redemption rechecks the issuer's current authority. Changing an issuer's role or removing them invalidates pending invitations. New local account creation and invitation redemption commit together; failed redemption cannot leave a new account behind.

Administrative password reset requires a local account that belongs exclusively to the administered team. Owners may reset admins or ordinary members; admins may reset only ordinary members. Resetting oneself or another owner is denied. A user's own password change requires their current password. An authorized reset revokes all account sessions globally; the service must provide its explicit recovery policy separately.

Legacy room claims require a current owner web token and an unbound room. Only that proven owner is mapped to the claiming account. Existing collaborators retain their original credentials without receiving account permissions. Claimed rooms reject legacy room invitations, invite redemption, and `add_member`; team membership operations supply new access. Existing unbound rooms retain their original behavior.

Tests retain unique databases in ignored `.local/c1-tests/`. No tests or store operations remove files.
