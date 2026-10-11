# Git integration implementation plan

> For agentic workers: use `subagent-driven-development` for isolated implementation and independent specification/code reviews. Never delete files. Work exclusively in `.local/worktrees/git-evidence`; preserve the commercial checkout.

**Goal:** Give existing agents repository context and let the webpage show local Git observations and verified GitHub delivery evidence.

**Architecture:** A project-scoped repository store reuses existing identity and transaction boundaries. An opt-in local stdio MCP adapter reads Git through bounded subprocess calls and forwards authenticated checkpoint operations. A separately configured GitHub App reads only granted repositories, queues signed events and reconciles PR/check state. The existing kanban consumes those records without replacing task ownership or human decisions.

**Stack:** Python 3.11+, SQLite, Starlette, official MCP SDK, Git executable, GitHub REST API, existing plain JavaScript UI.

## Shared interfaces and boundaries

- `RepositoryStore(identity)`: `bind_repository(web_token, repository)`, `get_binding(token)`, `observe(agent_token, task_id, observation)`, `snapshot(token)`. Repository URLs normalize HTTPS/SSH GitHub remotes to `github.com/owner/repo`; credentials, query strings and local filesystem paths are rejected.
- Observation object: `request_key`, `workspace_id`, `repository`, `branch`, `head`, `paths`, `captured_at`. SHA is empty for an unborn branch; branch is empty for detached HEAD. `paths` contains repo-relative tracked paths. The server stamps receipt time, bounds freshness and preserves request idempotency.
- `GitWorkspace(path)`: `inspect(include_untracked=False)` returns `repository`, `branch`, `head`, `paths`, `captured_at`, plus local-only workspace diagnostics. `load_project(path)` reads `.crewmesh/project.json` and validates data. No shell, hooks, source contents or credential-bearing URL transmission.
- Local adapter command: `python -m crewmesh.git_adapter --repository PATH --service URL --project PROJECT_ID`. Agent token comes from `CREWMESH_AGENT_TOKEN`, never arguments or versioned files. `repo_checkpoint(task_id)` reads Git, validates project/repository and reports observation, then returns team/inbox context. Forward the existing agent operations through the same trusted service endpoint.
- `service.repositories` supplies `git` snapshot data with `binding`, `workspaces`, `overlaps`, `deliveries`, `events`. Existing HTTP/MCP operations remain supported.
- GitHub binding requires proof of repository access via a separately configured GitHub App authorization flow; an arbitrary installation ID is insufficient. Credentials and App private key stay outside Git. Remote updates retain complete repository identity, PR number and head SHA.

## G1: local repository integration

- [x] Add `src/git_workspace.py`, `tests/test_git_workspace.py`: normalize remotes; real Git tests for two clones, linked worktree, detached and unborn HEAD, staged/unstaged rename paths, ignored/untracked files, no origin and credential sanitization. Retain all fixture directories under `.local/test-evidence/`.
- [x] Run `python -m unittest discover -s tests -p test_git_workspace.py -v`; demonstrate the new module's absence before implementation, then pass all behavior tests.
- [x] Add `src/repositories.py`, `tests/test_repositories.py`: authenticate room owner for binding and claimed task owner for observations; reject cross-room/foreign-owner writes; append idempotent observations, stale/out-of-order filtering, and exact-path overlap evidence. Rebinding with existing evidence is rejected rather than silently rewriting provenance.
- [x] Integrate binding, observation and repository reads through `src/api.py`, `src/mcp_service.py`. Add `tests/test_git_http.py` for real HTTP permissions, strict schemas and snapshot fields.
- [x] Add `src/git_adapter.py`, tests and `docs/git-local-setup.md`: explicit trusted service origin, project check, environment credential, no redirect credential forwarding, readonly local inspection and stdio MCP checkpoint/forwarding. Preview configuration and preserve existing agent rules/configuration.
- [x] Verify focused tests, then the full Python suite; commit G1 code/tests/documentation with exact paths.

Example domain acceptance:

```python
binding = store.bind_repository(owner['web_token'], 'git@github.com:acme/demo.git')
assert binding['repository'] == 'github.com/acme/demo'
store.observe(member['agent_token'], claimed_task['id'], observation)
assert store.snapshot(owner['web_token'])['workspaces'][0]['source'] == 'local_git'
```

## G2: GitHub delivery evidence

- [x] Add focused modules `src/github_app.py`, `src/github_sync.py`, `src/git_routes.py` and tests: App JWT, installation/user authorization, HTTPS API origin, bounded response parsing and safe errors.
- [x] Add one-use short-lived authorization state bound to the requesting project manager; callback verifies authorized repository access before saving installation/repository ID. Existing account GitHub OAuth login is unchanged.
- [x] Add signed webhook route and persistent inbox: HMAC validation, delivery-ID deduplication with payload integrity, allowed event filtering and bounded payloads. Durable acceptance precedes remote reconciliation; retry pending deliveries after failures/restart.
- [x] Reconcile current PR/check/push state with API results; never derive final state from an old webhook alone. Check heads and repository/fork identity; closed-unmerged differs from merged. Poll/manual refresh provides compensation for missed events; installation revocation removes verified current access.
- [x] Add explicit task/branch/PR association for task owner or manager; leave unknown PRs unassociated. Store provenance and server observation time; redact all remote credentials.
- [x] Test forged signature, duplicate/mismatched deliveries, retries, stale head checks, fork PR, changed branch HEAD, closed PR, revoked access and cross-project isolation. Record real network/App installation separately from offline protocol tests.
- [x] Commit G2 implementation and operational instructions after focused and integration checks.

## G3: kanban and checkpoints

- [x] Add `src/static/git.js` with safe DOM-only rendering and minimal hooks in existing UI: repository binding/setup; per-card branch/PR/check/freshness; task detail workspaces, delivery evidence and timeline.
- [x] Prefer verified associated remote delivery states for the delivery columns; preserve explicit blocked state and human decisions. Existing agent-only projects retain original behavior. A merged related PR records delivery, not task acceptance.
- [x] Show actual-path overlap separately from declared scope overlaps; ignore expired local observations in active risk prompts.
- [x] Add JavaScript regression coverage for stale data, untrusted text/URLs, blocked state, PR head change, project switching and missing Git binding. Verify keyboard-accessible controls and unchanged task detail behavior.
- [x] Exercise two real local members/clones with independent tokens through HTTP and stdio MCP checkpoints, shared contract updates and PR/check simulation. Save evidence in `.local/`; document actual GitHub/native-tool acceptance limitations explicitly.
- [x] Run full Python and existing JavaScript regressions; perform independent spec review and code-quality review, repair findings, then stage commit G3.

## Integration and reporting

- [x] Recheck the commercial branch's committed HTTP/MCP/account changes. Merge through Git rather than overwriting its worktree; never include its uncommitted files.
- [x] Update the project documentation index/README only after reconciling shared edits. Publish an isolated feature branch/PR if the shared checkout still has in-flight commercial edits.
- [x] `docs/git-integration-report.md` records commits, tested behaviors, actual commands/results and remaining environment-dependent acceptance. Do not label simulated GitHub callbacks as a live App installation.
