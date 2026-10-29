# 0.8 Git Delivery and Project Activity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only GitHub Release evidence, explicit task-to-release associations, and a bounded project activity feed derived only from structured Coopagents records.

**Architecture:** Extend the existing `GitHubApp` read-only provider and `GitHubSync` snapshot rather than adding another GitHub client or event store. Store release associations in a separate additive table so existing branch/PR and commit records remain intact; build activity as a bounded read model from already-authorized project snapshots. Both the authenticated hosted GUI and loopback-only board render the same Git and activity data. Agent-private conversations, prompts, assistant responses, hidden reasoning, tool arguments/results, and transcript files are never read or stored.

**Tech Stack:** Python 3.11+, SQLite, Starlette, official GitHub REST App installation tokens, plain JavaScript, Node regression scripts, unittest.

---

## Validation Environment

Use the persistent D-drive interpreter below so this worktree does not install dependencies onto the nearly full C drive:

```powershell
& 'D:\coop-e2e\tools\Scripts\python.exe' -m venv 'D:\coop-e2e\git-delivery-08-venv'
& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m pip install -c 'C:\Users\Weichen Li\.codex\worktrees\git-delivery-08\wo-zhe\deploy\constraints.txt' -e 'C:\Users\Weichen Li\.codex\worktrees\git-delivery-08\wo-zhe[service,space]'
& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -c "import importlib.metadata as m,coopagents; print(m.version('coopagents'), coopagents.__file__)"
```

Expected version is `0.7.4`, and the import path must point into the `git-delivery-08` worktree. Unless a command explicitly writes build output to D:, tests retain their normal `.local/` evidence in the worktree and must not clean it.

## File Map

- `src/github_app.py`: bounded read-only GitHub release discovery and explicit release lookup.
- `src/github_sync.py`: additive `github_release_refs`, release normalization, evidence/snapshot filtering, release webhook invalidation.
- `src/coordination.py`: expose release association and the activity read model through the common service.
- `src/git_routes.py`: strict HTTP schema for release linking.
- `src/git_adapter.py`: expose the same `release_id` field through the local Git MCP adapter.
- `src/task_lifecycle.py`: retain and retire release associations with existing task ownership epochs.
- `src/project_activity.py`: new pure bounded activity projection from authorized structured snapshot records.
- `src/api.py`: expose the activity read to the hosted GUI.
- `src/space_board.py`: activity is returned by its existing shared service snapshot; no remote board management route is added.
- `src/static/git.js`: display releases and allow an authorized task owner/manager to associate a discovered release.
- `src/static/project_activity.js`: new safe-DOM renderer for structured project activity.
- `src/static/index.html`, `src/static/app.js`, `src/static/board.html`, `src/static/space_board.js`, `src/static/styles.css`: mount the shared activity renderer in hosted and local read-only views.
- `tests/test_github_app.py`, `tests/test_github_sync.py`, `tests/test_git_routes.py`: provider, persistence, authorization, webhook and snapshot behavior.
- `tests/test_project_activity.py`: source allowlist, ordering, bounds and transcript exclusion.
- `tests/git_ui_regression.js`, `tests/project_activity_ui_regression.js`: release rendering/link payload and safe activity rendering.
- `.github/workflows/ci.yml`: run the activity UI regression in CI.
- `docs/git-github-setup.md`, `docs/git-integration-report.md`: document Release event subscription, read-only behavior, evidence and limits after verification.

## Task 1: Read-Only GitHub Release Provider

**Files:**
- Modify: `tests/test_github_app.py`
- Modify: `src/github_app.py`

- [ ] **Step 1: Add a failing test for bounded recent release discovery**

Add an HTTP mock test returning one published release from `GET /repos/acme/demo/releases`. Assert `repository_state` returns only the allowlisted fields `id`, `tag_name`, `name`, `draft`, `prerelease`, `created_at`, `published_at`, and a URL constructed under `https://github.com/acme/demo/releases/tag/<quoted-tag>`. Do not return the provider's arbitrary `html_url`, body text, upload URL, or asset download URL.

```python
def test_release_discovery_returns_bounded_safe_metadata(self):
    def handler(request):
        if request.url.path == '/app/installations/22':
            return httpx.Response(200, json={'id': 22, 'app_id': 123})
        if request.url.path.endswith('/access_tokens'):
            return httpx.Response(201, json=self.token_response())
        if request.url.path == '/repositories/11':
            return httpx.Response(200, json={'id': 11, 'full_name': 'acme/demo'})
        if request.url.path == '/repos/acme/demo/releases':
            self.assertEqual(request.url.params['per_page'], '20')
            return httpx.Response(200, json=[{'id': 42, 'tag_name': 'v1.2.3', 'name': '1.2.3',
                'draft': False, 'prerelease': False, 'created_at': '2026-01-01T00:00:00Z',
                'published_at': '2026-01-02T00:00:00Z', 'html_url': 'https://evil.example/x',
                'body': 'untrusted release notes'}])
        if request.url.path == '/repos/acme/demo/pulls':
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)
    state = self.app(handler).repository_state(22, 11, 'acme/demo')
    release = state['releases'][0]
    self.assertEqual(release['release_id'], 42)
    self.assertEqual(release['url'], 'https://github.com/acme/demo/releases/tag/v1.2.3')
    self.assertNotIn('body', release)
    self.assertNotIn('evil.example', json.dumps(release))
```

- [ ] **Step 2: Run the test and confirm the missing release field fails**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_app.py -k release_discovery_returns_bounded_safe_metadata -v`

Expected: FAIL because the current provider response has no `releases` field.

- [ ] **Step 3: Implement bounded release discovery and normalization**

Add `RELEASE_DISCOVERY_LIMIT = 20`. Extend `repository_state(..., release_ids=())`; count release IDs against the existing 100-reference operation limit. Fetch one bounded page from `/repos/{owner}/{repo}/releases?per_page=20&page=1`, and explicit IDs from `/releases/{id}` even when they are outside the discovery page. Validate positive integer ID equality, bounded nonempty tag/name strings, exact booleans, timestamp types, and at most 20 assets. Return `release_discovery: {limit, truncated}` and `unavailable_release_ids`. Normalize only the fields in Step 1 plus asset `{name,size,digest}` metadata; build links from the already-verified repository name and a URL-quoted tag.

```python
def _release_url(full_name, tag):
    return f"https://github.com/{full_name}/releases/tag/{quote(tag, safe='')}"
```

- [ ] **Step 4: Run provider release tests**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_app.py -v`

Expected: all GitHub App tests pass, including the new bounded release case.

- [ ] **Step 5: Commit provider support**

```powershell
git add src/github_app.py tests/test_github_app.py
git commit -m "feat: read bounded GitHub release metadata"
```

## Task 2: Explicit Task-to-Release Associations

**Files:**
- Modify: `tests/test_github_sync.py`
- Modify: `src/github_sync.py`

- [ ] **Step 1: Add a failing test for explicit release association**

Extend `FakeProvider.current` with one normalized release. Test an agent that owns the claimed task can link `release_id=42`; assert the saved row contains room/task/release IDs, linking member, timestamp, and ownership epoch. Repeat is idempotent. An agent without visibility to the task and a different room must be rejected.

```python
def test_release_link_is_task_scoped_and_idempotent(self):
    self.connect()
    self.app.current['releases'] = [{'release_id': 42, 'tag_name': 'v1.2.3', 'name': '1.2.3',
        'draft': False, 'prerelease': False, 'created_at': '2026-01-01T00:00:00Z',
        'published_at': '2026-01-02T00:00:00Z', 'assets': [], 'url': 'https://github.com/acme/demo/releases/tag/v1.2.3'}]
    first = self.sync.associate(self.member['agent_token'], self.task['id'], release_id=42)
    second = self.sync.associate(self.member['agent_token'], self.task['id'], release_id=42)
    self.assertEqual(first['id'], second['id'])
    self.assertEqual(first['release_id'], 42)
    with self.assertRaises(NotFound):
        self.sync.associate(self.other['agent_token'], self.task['id'], release_id=42)
```

- [ ] **Step 2: Run the test and confirm it fails before implementation**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_sync.py -k release_link_is_task_scoped_and_idempotent -v`

Expected: FAIL because `associate` does not yet accept `release_id`.

- [ ] **Step 3: Add an additive release-reference table**

Create `github_release_refs` in `GitHubSync.__init__` with `id`, `room_id`, `task_id`, `release_id`, `linked_by`, `linked_at`, `ownership_epoch`, unique `(room_id, task_id, release_id)`, and the existing composite task/room foreign key. Do not rewrite or rename existing branch/PR or commit tables.

- [ ] **Step 4: Extend association validation and the shared reference cap**

Extend `associate(..., release_id=None, ...)`. Require exactly one of branch, PR number, commit SHA, or release ID. Validate `release_id` with `positive_id`, use an idempotent lookup/insert, increment the GitHub connection revision on a new association, and include release refs in `MAX_REFS` accounting.

```python
references = sum(value is not None for value in (bool(branch), pr_number, bool(commit_sha), release_id))
if references != 1:
    raise ValidationError('Specify exactly one branch, PR, commit or release')
```

- [ ] **Step 5: Verify the focused sync tests**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_sync.py -k release_link -v`

Expected: release ownership, duplicate idempotency, and cross-room denial pass.

- [ ] **Step 6: Commit release association persistence**

```powershell
git add src/github_sync.py tests/test_github_sync.py
git commit -m "feat: link GitHub releases to tasks"
```

## Task 3: Release Evidence, Webhook Invalidation, and Lifecycle Retention

**Files:**
- Modify: `tests/test_github_sync.py`
- Modify: `tests/test_github_app.py`
- Modify: `tests/test_git_routes.py`
- Modify: `src/github_sync.py`
- Modify: `src/github_app.py`
- Modify: `src/task_lifecycle.py`

- [ ] **Step 1: Add failing tests for linked release evidence and release webhook acceptance**

After refresh, assert the linked release appears in `snapshot()['deliveries']` with `source='github_verified'`, `release_id`, `tag_name`, published/draft/prerelease state, repository identity, sync time, and the safe constructed URL. Assert a missing linked release is `unavailable` without revoking other delivery evidence. Sign a release webhook with the existing test HMAC and assert it is queued; a forged signature remains rejected.

- [ ] **Step 2: Run the focused tests and verify red**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_sync.py -k release_evidence -v`

Expected: FAIL because release refs and the release webhook event are not represented in current evidence.

- [ ] **Step 3: Normalize releases into delivery evidence**

Add `releases` and `unavailable_release_ids` validation to `GitHubSync._evidence`. Merge only linked releases into delivery rows; do not infer release membership from branch names, commit messages, unverified notes, or dates. Preserve the connection revision guard and total `MAX_EVIDENCE_BYTES` limit.

- [ ] **Step 4: Include release references in reconciliation and snapshots**

Load `github_release_refs` in `_reconcile`, pass sorted unique release IDs to `repository_state`, and filter snapshot rows against active release refs, task ownership epoch, task cancellation, connection status, association time, and stale evidence exactly as existing Git/commit deliveries are filtered.

- [ ] **Step 5: Accept the signed release webhook as an invalidation event**

Add only the GitHub `release` event to `EVENTS`. Reuse the existing signature verification, size bounds, repository/installation identity checks, durable inbox, retry, and reconciliation path. Do not store the webhook body or release notes.

- [ ] **Step 6: Preserve release references in lifecycle history**

Add `github_release_refs` to `task_lifecycle.context_for` and `retire_execution`. Ownership change must detach active associations as the existing Git refs are detached, while lifecycle history retains the bounded reference metadata. Update tests to prove a handoff preserves prior history but does not make stale release evidence current for the new owner epoch.

- [ ] **Step 7: Verify provider, sync, webhook, and lifecycle tests**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_app.py -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_sync.py -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_task_lifecycle.py -v`

Expected: all selected tests pass; existing branch/PR/commit and revoked-install behavior is unchanged.

- [ ] **Step 8: Commit evidence and lifecycle behavior**

```powershell
git add src/github_app.py src/github_sync.py src/task_lifecycle.py tests/test_github_app.py tests/test_github_sync.py tests/test_git_routes.py
git commit -m "feat: reconcile release evidence and preserve task history"
```

## Task 4: Expose Release Linking Through HTTP and Agent MCP

**Files:**
- Modify: `tests/test_git_routes.py`
- Modify: `tests/test_github_sync.py`
- Modify: `src/git_routes.py`
- Modify: `src/coordination.py`
- Modify: `src/git_adapter.py`
- Modify: `src/mcp_service.py`

- [ ] **Step 1: Add failing HTTP and MCP schema tests**

Verify `/api/git/github/link` accepts `release_id` only as a positive integer, rejects booleans, unknown keys, and mixed release+PR arguments, and the authenticated MCP `link_delivery` schema exposes optional `release_id` without adding any management permission.

- [ ] **Step 2: Run focused tests and verify red**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_git_routes.py -v`

Expected: the request containing `release_id` is rejected by the current strict schema.

- [ ] **Step 3: Extend the common operation schema and route**

Add `'release_id': (int, False, None)` to the common `link_delivery` operation and HTTP body schema. Preserve the existing agent task-owner check and manager-only web authorization performed by `GitHubSync.associate`.

- [ ] **Step 4: Extend the local Git adapter and tool description**

Add optional integer `release_id` to the adapter's `link_delivery` request schema and document that a release is linked by ID from the verified project release list. Do not let the adapter create or publish a release. Keep tool inputs limited to schema-approved scalar identifiers.

- [ ] **Step 5: Verify route, MCP forwarding, and auth tests**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_git_routes.py -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_git_adapter.py -v`

Expected: valid association reaches the same domain method; invalid schemas and unauthorized member/task cases are rejected.

- [ ] **Step 6: Commit the API contract**

```powershell
git add src/coordination.py src/git_routes.py src/git_adapter.py src/mcp_service.py tests/test_git_routes.py tests/test_github_sync.py
git commit -m "feat: expose task release linking to web and agents"
```

## Task 5: Bounded Structured Project Activity Read Model

**Files:**
- Create: `src/project_activity.py`
- Create: `tests/test_project_activity.py`
- Modify: `src/coordination.py`

- [ ] **Step 1: Add failing tests for approved activity sources and transcript exclusion**

Build a fixture with a task lifecycle event, explicit `report_progress`, request/reply receipt states, contract decision, local Git observation, and a verified release delivery. Assert each feed item contains only `id`, `type`, `occurred_at`, `actor_member_id`, `task_id`, `source`, `summary`, and safe object references. Assert raw request body, arbitrary tool arguments, fake `prompt`, `assistant_response`, `transcript_path`, and `tool_result` fields never appear even if present in the input snapshot.

```python
def test_activity_uses_only_allowlisted_structured_facts():
    snapshot = {'progress': [{'task_id': 1, 'member_id': 'm', 'state': 'working',
        'summary': 'Tests pass', 'evidence': 'ci run 12', 'updated_at': '2026-01-01T00:00:00Z',
        'prompt': 'PRIVATE-PROMPT'}], 'private_transcript': 'DO-NOT-EXPORT'}
    feed = project_activity(snapshot)
    encoded = json.dumps(feed)
    assert 'Tests pass' in encoded
    assert 'PRIVATE-PROMPT' not in encoded
    assert 'DO-NOT-EXPORT' not in encoded
```

- [ ] **Step 2: Run the new activity test and verify red**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_project_activity.py -v`

Expected: FAIL because `project_activity` does not exist.

- [ ] **Step 3: Implement a pure allowlisted event projection**

Implement `project_activity(snapshot, limit=100)` as a pure function. It consumes only the explicit source collections listed in this task, maps each source with hand-written field allowlists, emits no bodies or arbitrary nested payloads, sorts by timestamp descending then stable source/id, caps the output at 100, and returns a `truncated` flag. Progress text is included only from the explicit `report_progress` record. Team request/reply bodies remain accessible solely through the existing explicit collaboration tools/UI, not duplicated into activity.

- [ ] **Step 4: Add activity to the shared authorized service snapshot**

In `CoordinationService.snapshot`, build the existing authorized snapshot first, then attach `activity` from that already-filtered result. Do not query private files, harness session logs, chat history, webhooks' raw bodies, or transcript paths. Keep one implementation so hosted API, authenticated MCP snapshot, and loopback-only board receive identical activity semantics.

- [ ] **Step 5: Verify activity ordering, bounds, and privacy tests**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_project_activity.py -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_space_board.py -v`

Expected: ordered page is at most 100, `truncated` is correct, secrets/transcripts are absent, and the board snapshot remains read-only without writing message receipts.

- [ ] **Step 6: Commit the read model**

```powershell
git add src/project_activity.py src/coordination.py tests/test_project_activity.py
git commit -m "feat: expose bounded structured project activity"
```

## Task 6: Shared Git and Activity UI

**Files:**
- Modify: `src/static/git.js`
- Create: `src/static/project_activity.js`
- Modify: `src/static/index.html`
- Modify: `src/static/app.js`
- Modify: `src/static/board.html`
- Modify: `src/static/space_board.js`
- Modify: `src/space_board.py`
- Modify: `src/api.py`
- Modify: `src/static/styles.css`
- Modify: `tests/git_ui_regression.js`
- Create: `tests/project_activity_ui_regression.js`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add failing Git UI tests for release metadata and linking**

Extend `tests/git_ui_regression.js` with a verified release delivery containing `release_id`, `tag_name`, `state`, and a safe release URL. Assert the detail shows the tag, published/draft/prerelease state and source freshness. Assert the task link form sends `release_id` as a number and never includes release notes, asset contents, or arbitrary provider URL.

- [ ] **Step 2: Add failing activity UI tests**

Create `tests/project_activity_ui_regression.js` using the repository's existing minimal DOM stubs. Assert event summary and source render as text nodes, chronological ordering is stable, missing timestamps are labeled unknown, and prompt/transcript/tool payload fields are not rendered.

- [ ] **Step 3: Implement release rendering and explicit association**

Extend shared `Git.renderDetails` and `renderPanel` to show bounded discovered releases and explicit task release links. Add an accessible numeric release picker/list that sends only `{task_id, release_id}` to the existing link route. Build release links from validated GitHub repository/tag data or accept only the already-sanitized server URL. Do not make releases imply task acceptance.

- [ ] **Step 4: Implement the shared activity renderer**

Create a renderer that accepts the allowlisted `snapshot.activity` shape, builds all content with `textContent`, labels actor/time/source, links only safe task and Git object URLs, and displays the truncation state. Never render arbitrary raw event JSON or text fields not defined by the read model.

- [ ] **Step 5: Mount the renderer in hosted and local views**

Add the activity section to the authenticated hosted workspace and the host loopback board. Add the script to the HTTP asset allowlist and the board static allowlist. Both surfaces use the same renderer and same snapshot; the local board remains read-only and no public management route is added.

- [ ] **Step 6: Verify JavaScript regressions**

Run: `node tests/git_ui_regression.js`

Run: `node tests/project_activity_ui_regression.js`

Run: `node tests/board_ui_regression.js`

Run: `node tests/web_session_regression.js src/static/app.js`

Expected: release links, activity privacy, project switching, and existing Git checks pass with no unsafe HTML nodes.

- [ ] **Step 7: Commit shared UI**

```powershell
git add src/static/git.js src/static/project_activity.js src/static/index.html src/static/app.js src/static/board.html src/static/space_board.js src/space_board.py src/api.py src/static/styles.css tests/git_ui_regression.js tests/project_activity_ui_regression.js .github/workflows/ci.yml
git commit -m "feat: show release delivery and project activity"
```

## Task 7: Documentation and End-to-End Regression

**Files:**
- Modify: `docs/git-github-setup.md`
- Modify: `docs/git-integration-report.md`
- Modify: `docs/product-1.0-design.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Document the release read scope**

Document the GitHub `release` webhook subscription, the Contents-read-only requirement, how to find and explicitly link a discovered release ID to a task, allowed release metadata, stale/unavailable states, and that no release is created or published by Coopagents.

- [ ] **Step 2: Document the activity privacy contract**

Document which structured collaboration/Git facts appear in the feed, the 100-event bound, how truncated/stale evidence is labeled, and the hard prohibition on reading or storing harness transcripts, private prompts, tool arguments/results, and raw webhook bodies.

- [ ] **Step 3: Run the full Python, browser, and package checks**

Run: `$env:CODEX_THREAD_ID=''; $env:CODEX_SESSION_ID=''; $env:CLAUDECODE=''; & 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v`

Run: `node --check src/static/project_activity.js`

Run: `node tests/project_activity_ui_regression.js`

Run: `node tests/git_ui_regression.js`

Run: `node tests/board_ui_regression.js`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m build --outdir 'D:\coop-e2e\git-delivery-08-build\dist'`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m twine check 'D:\coop-e2e\git-delivery-08-build\dist\*'`

Expected: every command exits 0. Keep generated databases and logs under `.local/`; do not delete prior evidence.

- [ ] **Step 4: Commit documentation and final checks**

```powershell
git add docs/git-github-setup.md docs/git-integration-report.md docs/product-1.0-design.md docs/README.md
git commit -m "docs: record 0.8 Git delivery and activity behavior"
git diff --check
```

## Completion Criteria

- A task can be explicitly linked to a verified GitHub Release through both the web route and agent `link_delivery`; authorization, room isolation, ownership epoch, idempotency, and reference caps remain enforced.
- Release evidence is read-only, bounded, sanitized, tied to the configured repository ID, and updated by signed `release` webhooks plus existing reconciliation.
- Hosted GUI and local read-only board show the same Release and activity records.
- Activity is a read-only projection of structured project records. No prompt, private assistant response, hidden reasoning, raw tool payload/result, transcript path, or raw webhook body is queried or displayed.
- Existing branch/commit/PR behavior and task delivery/acceptance semantics are unchanged.
- Focused tests, full Python/experiment suites, web regressions, package build and `twine check` pass.
