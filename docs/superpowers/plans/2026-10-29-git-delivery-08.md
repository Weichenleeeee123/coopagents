# 0.8 Git Delivery and Project Activity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only GitHub Release evidence, explicit task-to-release associations, and a bounded project activity feed made only from structured Coopagents records.

**Architecture:** Extend the existing `GitHubApp` and `GitHubSync` read-only integration. Keep release associations in a separate additive table so existing branch/PR and commit rows remain intact. Derive activity from the already-authorized service snapshot without persisting a second copy of event data. The authenticated hosted GUI and loopback-only board use the same snapshot and renderer. Agent-private conversations, prompts, assistant responses, hidden reasoning, tool arguments/results, and transcript files are never read, stored, or rendered.

**Tech Stack:** Python 3.11+, SQLite, Starlette, GitHub App REST API with read-only installation token, plain JavaScript, Node regression scripts, unittest.

---

## Worktree and Validation Environment

Worktree branch: `feat/git-delivery-08`, rooted at `C:\Users\Weichen Li\.codex\worktrees\git-delivery-08\wo-zhe`.

Use a persistent D-drive venv to avoid filling C:. From the worktree root, create it once and install the pinned service/space dependencies:

```powershell
& 'D:\coop-e2e\tools\Scripts\python.exe' -m venv 'D:\coop-e2e\git-delivery-08-venv'
& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m pip install -c "$((Get-Location).Path)\deploy\constraints.txt" -e "$((Get-Location).Path)[service,space]" build twine
& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -c "import importlib.metadata as m,coopagents; print(m.version('coopagents')); print(coopagents.__file__)"
```

Expected: version `0.7.4`; the import path points into the `git-delivery-08` worktree. Tests retain their normal `.local/` evidence in this worktree. Never remove or clean old evidence.

## File Map

- `src/github_app.py`: bounded read-only release discovery and explicit release lookup.
- `src/github_sync.py`: additive `github_release_refs`, release normalization/evidence, release webhook invalidation, snapshot filtering.
- `src/coordination.py`: common `link_delivery.release_id` and bounded activity snapshot.
- `src/git_routes.py`: strict web schema for release associations.
- `src/git_adapter.py`, `src/mcp_service.py`: local adapter schema and user-facing agent instructions.
- `src/task_lifecycle.py`: archive and retire release refs alongside existing branch/commit/PR refs.
- `src/project_activity.py`: pure allowlisted activity projection.
- `src/api.py`: expose shared activity read to the hosted GUI and serve the new asset.
- `src/static/git.js`: render release evidence and explicitly link a discovered release to a task.
- `src/static/project_activity.js`: safe-DOM renderer for bounded project activity.
- `src/static/index.html`, `src/static/app.js`, `src/static/board.html`, `src/static/space_board.js`, `src/space_board.py`, `src/static/styles.css`: mount the same activity view in hosted and loopback-only board surfaces.
- `tests/test_github_app.py`, `tests/test_github_sync.py`, `tests/test_git_routes.py`, `tests/test_task_lifecycle.py`: provider, authorization, persistence, webhook and ownership epoch behavior.
- `tests/test_project_activity.py`: allowlisted event fields, ordering, truncation and transcript exclusion.
- `tests/git_ui_regression.js`, `tests/project_activity_ui_regression.js`: release linking and activity privacy/safe DOM.
- `.github/workflows/ci.yml`: run the new UI regression.
- `docs/git-github-setup.md`, `docs/git-integration-report.md`, `docs/product-1.0-design.md`, `docs/README.md`: release subscription, observed behavior, evidence and phase status.

## Task 1: GitHub Release Read API

**Files:**
- Modify: `tests/test_github_app.py`
- Modify: `src/github_app.py`

- [ ] **Step 1: Write failing discovery and identity tests**

Use the existing `httpx.MockTransport` helper. Return one release from `/repos/acme/demo/releases`; assert page size is 20 and the normalized release contains safe fields only. Include malicious `html_url`, release body, and asset download URL in the fake response and assert none are returned. Add a second test for a requested release ID fetched outside the first page and a 404 ID reported as unavailable.

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
                'body': 'private-notes', 'assets': [{'name': 'app.zip', 'size': 17,
                    'digest': 'sha256:abc', 'browser_download_url': 'https://evil.example/file'}]}])
        if request.url.path == '/repos/acme/demo/pulls':
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)
    state = self.app(handler).repository_state(22, 11, 'acme/demo')
    release = state['releases'][0]
    self.assertEqual(release['release_id'], 42)
    self.assertEqual(release['url'], 'https://github.com/acme/demo/releases/tag/v1.2.3')
    self.assertEqual(release['assets'], [{'name': 'app.zip', 'size': 17, 'digest': 'sha256:abc'}])
    self.assertNotIn('private-notes', json.dumps(state))
    self.assertNotIn('evil.example', json.dumps(state))
```

- [ ] **Step 2: Run the tests and verify the current provider fails them**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_app.py -k release_discovery -v`

Expected: FAIL because the current provider does not return a `releases` field.

- [ ] **Step 3: Implement bounded release discovery**

Add `RELEASE_DISCOVERY_LIMIT = 20` and `RELEASE_ASSET_LIMIT = 20`. Extend `repository_state(..., release_ids=())`; count release IDs against the existing 100-reference operation budget. Fetch one page with `bounded_page(path + '/releases', token, limit=RELEASE_DISCOVERY_LIMIT)`. Fetch explicitly linked IDs through `/releases/{id}` even outside discovery. Validate matching positive ID, nonempty tag/name bounded to 250 characters, exact boolean `draft` and `prerelease`, nullable bounded timestamps, and a list of release assets. Return at most 20 asset records with `{name,size,digest}` plus `assets_truncated`. Return release fields `release_id`, `tag_name`, `name`, `draft`, `prerelease`, `created_at`, `published_at`, `target_commitish`, `assets`, and a URL constructed from the verified repository name plus URL-quoted tag. Never return body text, arbitrary provider URLs or credentials. Return `release_discovery: {limit, truncated}` and `unavailable_release_ids`.

- [ ] **Step 4: Verify all provider tests**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_app.py -v`

Expected: all provider tests pass, including bounded release discovery, explicit lookup, unavailable ID, response cap, redirects and repository identity checks.

- [ ] **Step 5: Commit the provider layer**

```powershell
git add src/github_app.py tests/test_github_app.py
git commit -m "feat: read bounded GitHub release metadata"
```

## Task 2: Explicit Task-to-Release Relations

**Files:**
- Modify: `tests/test_github_sync.py`
- Modify: `src/github_sync.py`

- [ ] **Step 1: Write a failing task-scoped association test**

Extend `FakeProvider.current` with a normalized release. Test that the claimed task owner can link release ID 42, repeating the same request is idempotent, and a different project cannot link that task.

```python
def test_release_link_is_task_scoped_and_idempotent(self):
    self.connect()
    self.app.current['releases'] = [{'release_id': 42, 'tag_name': 'v1.2.3', 'name': '1.2.3',
        'draft': False, 'prerelease': False, 'created_at': '2026-01-01T00:00:00Z',
        'published_at': '2026-01-02T00:00:00Z', 'assets': [],
        'url': 'https://github.com/acme/demo/releases/tag/v1.2.3'}]
    first = self.sync.associate(self.member['agent_token'], self.task['id'], release_id=42)
    second = self.sync.associate(self.member['agent_token'], self.task['id'], release_id=42)
    self.assertEqual(first['id'], second['id'])
    self.assertEqual(first['release_id'], 42)
    with self.assertRaises(NotFound):
        self.sync.associate(self.other['agent_token'], self.task['id'], release_id=42)
```

- [ ] **Step 2: Run the test and verify it fails for the missing release field**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_sync.py -k release_link_is_task_scoped_and_idempotent -v`

Expected: FAIL because `associate` does not accept `release_id`.

- [ ] **Step 3: Add an additive reference table**

Create `github_release_refs` in `GitHubSync.__init__` with `id`, `room_id`, `task_id`, `release_id`, `linked_by`, `linked_at`, `ownership_epoch`, unique `(room_id, task_id, release_id)`, and the existing composite task/room foreign key. Preserve `github_refs` and `github_commit_refs` without rewrite or row copying.

- [ ] **Step 4: Extend association validation and the project reference cap**

Extend `associate(..., release_id=None, ...)`. Exactly one reference kind must be present among nonempty branch, PR number, commit SHA and release ID. Validate release ID with `positive_id`; add release lookup/insert, idempotency, connection revision increment, and count `github_release_refs` in the existing `MAX_REFS` total.

```python
reference_count = sum((bool(branch), pr_number is not None, bool(commit_sha), release_id is not None))
if reference_count != 1:
    raise ValidationError('Specify exactly one branch, PR, commit or release')
if release_id is not None:
    positive_id(release_id)
```

- [ ] **Step 5: Verify release relation authorization and idempotency**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_sync.py -k release_link -v`

Expected: owner and current task agent succeed; duplicate link returns the original row; cross-room, nonowner-task, boolean ID, and cap-overflow requests fail.

- [ ] **Step 6: Commit the domain table and association**

```powershell
git add src/github_sync.py tests/test_github_sync.py
git commit -m "feat: link GitHub releases to tasks"
```

## Task 3: Release Evidence, Signed Events, and Task History

**Files:**
- Modify: `tests/test_github_sync.py`
- Modify: `tests/test_github_app.py`
- Modify: `tests/test_git_routes.py`
- Modify: `src/github_sync.py`
- Modify: `src/task_lifecycle.py`

- [ ] **Step 1: Add failing release snapshot and webhook tests**

Assert refresh projects a linked release into `deliveries` with release ID, tag, draft/prerelease/published state, safe URL, repository ID, source, sync time, asset truncation state and stale flag. A missing release becomes `unavailable` and does not revoke branch/PR evidence. A valid signed `release` webhook is queued; an invalid signature remains rejected; webhook body text is not persisted.

- [ ] **Step 2: Run and verify the new release evidence test fails**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_sync.py -k release_evidence -v`

Expected: FAIL because release references are not included in reconciliation, evidence or event allowlisting.

- [ ] **Step 3: Normalize only linked releases into task delivery evidence**

Extend `_evidence` to validate `state['releases']`, discovery bounds and unavailable IDs. For each `github_release_refs` row, emit one `source='github_verified'` delivery with the stable reference ID and `ownership_epoch`. Draft, prerelease and published remain distinct states. Use the provider-safe URL from `GitHubApp`; do not infer task links from release body, tag text, commit message or proximity.

- [ ] **Step 4: Reconcile linked releases and filter active snapshot rows**

Load the release-reference table in `_reconcile`, pass sorted unique release IDs to `repository_state`, and include its JSON in the existing evidence-size check. In `snapshot`, retain a release delivery only if its reference exists, its task is visible and not cancelled, its ownership epoch matches, and sync evidence is not older than the link. Preserve revision guards and stale evidence semantics.

- [ ] **Step 5: Add signed release-event invalidation**

Add only `release` to the existing `EVENTS` allowlist. Reuse the same signature, byte limit, delivery-id idempotency, installation/repository validation, retry and reconciliation path. Do not store webhook bodies or release notes.

- [ ] **Step 6: Preserve association history across task ownership changes**

Add `github_release_refs` to `task_lifecycle.context_for` and `retire_execution`. Preserve the old relation in lifecycle history and detach it from the current execution epoch exactly as branch and commit refs are handled. Add a regression proving an old owner epoch cannot surface as current release evidence.

- [ ] **Step 7: Verify provider, sync and lifecycle suites**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_app.py -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_github_sync.py -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_task_lifecycle.py -v`

Expected: selected suites pass and existing PR/branch/commit behavior is unchanged.

- [ ] **Step 8: Commit evidence and lifecycle behavior**

```powershell
git add src/github_sync.py src/task_lifecycle.py tests/test_github_sync.py tests/test_github_app.py tests/test_git_routes.py
git commit -m "feat: reconcile GitHub release evidence"
```

## Task 4: HTTP and MCP Contract

**Files:**
- Modify: `tests/test_git_routes.py`
- Modify: `tests/test_github_sync.py`
- Modify: `src/git_routes.py`
- Modify: `src/coordination.py`
- Modify: `src/git_adapter.py`
- Modify: `src/mcp_service.py`

- [ ] **Step 1: Add failing strict-schema tests**

Verify `/api/git/github/link` accepts a positive integer `release_id`, rejects boolean IDs, unknown fields and mixed release+PR fields, and the MCP `link_delivery` schema exposes the same optional integer without widening authorization.

- [ ] **Step 2: Run and verify the request is rejected by the current schema**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_git_routes.py -v`

Expected: the valid release request currently receives HTTP 400.

- [ ] **Step 3: Extend the shared operation and HTTP schema**

Add `release_id: (int, False, None)` to `link_delivery` in `CoordinationService` and the exact HTTP body schema. Leave route roles unchanged; the domain `associate` remains responsible for current task ownership, manager permission, repository authorization and reference cap.

- [ ] **Step 4: Extend the local adapter schema and description**

Add optional `release_id` to `git_adapter`'s `link_delivery` schema. Update `mcp_service.py` to explain that agents may associate a discovered Release ID with a task; the operation does not create or publish releases. Preserve the “exactly one reference kind” rule.

- [ ] **Step 5: Verify web/MCP contract**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_git_routes.py -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_git_adapter.py -v`

Expected: valid release association reaches the common domain operation; invalid fields and unauthorized principals fail.

- [ ] **Step 6: Commit the public contract**

```powershell
git add src/coordination.py src/git_routes.py src/git_adapter.py src/mcp_service.py tests/test_git_routes.py tests/test_github_sync.py
git commit -m "feat: expose task release linking to agents and web"
```

## Task 5: Bounded Activity Projection

**Files:**
- Create: `src/project_activity.py`
- Create: `tests/test_project_activity.py`
- Modify: `src/coordination.py`

- [ ] **Step 1: Add a failing privacy/ordering test**

Use fixtures for lifecycle event, explicit progress report, session registration, request/reply status, contract decision, Git observation and verified release. Assert the output is timestamp ordered, bounded, uses only the declared fields and drops arbitrary transcript/prompt/tool payload properties.

```python
import json
import unittest
from coopagents.project_activity import project_activity

class ProjectActivityTests(unittest.TestCase):
    def test_explicit_progress_is_visible_but_transcript_fields_are_not(self):
        snapshot = {'progress': [{'task_id': 1, 'member_id': 'm', 'state': 'working',
            'summary': 'Tests pass', 'evidence': 'CI run 12', 'updated_at': '2026-01-01T00:00:00Z',
            'prompt': 'PRIVATE-PROMPT'}], 'transcript': 'PRIVATE-TRANSCRIPT'}
        output = json.dumps(project_activity(snapshot))
        self.assertIn('Tests pass', output)
        self.assertNotIn('PRIVATE-PROMPT', output)
        self.assertNotIn('PRIVATE-TRANSCRIPT', output)
```

- [ ] **Step 2: Verify red**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_project_activity.py -v`

Expected: FAIL because the projection module does not exist.

- [ ] **Step 3: Implement a pure allowlisted projection**

Define `project_activity(snapshot, limit=100)`. Convert each approved source into `{id,type,occurred_at,actor_member_id,task_id,source,summary,reference}` using hand-written field mapping. Sort newest first with stable tie-breaks; cap at 100 and return `truncated`. Allowed source values are `lifecycle`, explicit `agent_report` progress, session registration metadata, collaboration request/reply/read/processed/resolved status, contract events, local Git observations and verified GitHub deliveries. Never copy message bodies, contract bodies, arbitrary nested source dictionaries, webhook payloads, prompt/response fields or transcript paths. Only the explicit progress summary/evidence fields may appear as agent-authored text.

- [ ] **Step 4: Attach activity to the common authorized snapshot**

After `CoordinationService.snapshot` has assembled all existing role-filtered reads, compute `result['activity'] = project_activity(result)`. Do not add a persistent duplicate activity table or a new privilege. Existing service, MCP and board callers then receive the same bounded data.

- [ ] **Step 5: Verify read-only board and privacy**

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_project_activity.py -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -p test_space_board.py -v`

Expected: no inbox receipts are written by snapshots; activity is bounded and transcript values are absent.

- [ ] **Step 6: Commit the read model**

```powershell
git add src/project_activity.py src/coordination.py tests/test_project_activity.py
git commit -m "feat: add bounded structured project activity"
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

- [ ] **Step 1: Add failing release UI tests**

Extend `tests/git_ui_regression.js` with release delivery fields. Assert task detail displays tag and draft/prerelease/published status, uses only a safe GitHub release URL, shows sync source/time, and the link form sends numeric `release_id` without release notes or asset bodies.

- [ ] **Step 2: Add failing activity UI tests**

Use the existing minimal DOM test harness style. Assert event text is rendered with text nodes, newest-first order is stable, truncation is shown, and arbitrary `prompt`, `assistant_response`, `tool_input`, `tool_result` and transcript properties are ignored.

- [ ] **Step 3: Render discovered releases and associate explicitly**

Extend shared `Git.renderDetails` to display verified Release metadata. Add a release selector using numeric IDs from the bounded discovered list; its submit payload contains only `{task_id, release_id}`. Render provider strings using `textContent`; link only the server-constructed GitHub release URL. A published release remains delivery evidence and never sets task state to accepted.

- [ ] **Step 4: Implement shared activity renderer**

Create `ProjectActivity.render(root, activity)` that accepts only the declared event properties, creates nodes with `document.createElement`, writes all text through `textContent`, and displays the projection's truncation indicator. It must not use `innerHTML` or read any browser/session transcript source.

- [ ] **Step 5: Mount the same activity view in both deployment modes**

Add the hosted panel to `index.html` and call it from the existing snapshot render in `app.js`. Add the renderer asset to `api.py`'s explicit allowlist. Add the activity section and script to `board.html`, add it to `space_board.py`'s existing static allowlist, and render from the common board snapshot in `space_board.js`. Preserve the local board's narrow read-only route set.

- [ ] **Step 6: Run UI regressions**

Run: `node tests/git_ui_regression.js`

Run: `node tests/project_activity_ui_regression.js`

Run: `node tests/board_ui_regression.js`

Run: `node tests/web_session_regression.js src/static/app.js`

Expected: all pass; no unsafe DOM node is created from GitHub/provider/activity text.

- [ ] **Step 7: Commit shared UI**

```powershell
git add src/static/git.js src/static/project_activity.js src/static/index.html src/static/app.js src/static/board.html src/static/space_board.js src/space_board.py src/api.py src/static/styles.css tests/git_ui_regression.js tests/project_activity_ui_regression.js .github/workflows/ci.yml
git commit -m "feat: show GitHub releases and project activity"
```

## Task 7: Documentation and Release Checks

**Files:**
- Modify: `docs/git-github-setup.md`
- Modify: `docs/git-integration-report.md`
- Modify: `docs/product-1.0-design.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Document the GitHub Release read model**

Document the `release` webhook subscription, that Contents-read access is used, how to associate a discovered release ID, the 20-release discovery/asset metadata bounds, stale/unavailable statuses, and that Coopagents never creates or publishes releases.

- [ ] **Step 2: Document project activity privacy**

Document the allowlisted structured sources, timestamp/source/stale fields, 100-item cap, and the invariant that private harness transcripts, prompts, responses, hidden reasoning, tool inputs/results and raw webhook bodies are never read, stored or rendered.

- [ ] **Step 3: Run complete verification from the worktree**

Run: `$env:CODEX_THREAD_ID=''; $env:CODEX_SESSION_ID=''; $env:CLAUDECODE=''; & 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s tests -v`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v`

Run: `node --check src/static/project_activity.js`

Run: `node tests/project_activity_ui_regression.js`

Run: `node tests/git_ui_regression.js`

Run: `node tests/board_ui_regression.js`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m build --outdir 'D:\coop-e2e\git-delivery-08-build\dist'`

Run: `& 'D:\coop-e2e\git-delivery-08-venv\Scripts\python.exe' -m twine check 'D:\coop-e2e\git-delivery-08-build\dist\*'`

Expected: all commands exit 0. Docker validation is recorded only if a Docker Engine is available; local unit/JS tests are not described as live GitHub App acceptance.

- [ ] **Step 4: Commit docs and verify the final tree**

```powershell
git add docs/git-github-setup.md docs/git-integration-report.md docs/product-1.0-design.md docs/README.md
git commit -m "docs: record 0.8 Git delivery and activity"
git diff --check
```

## Completion Criteria

- A task can be linked to exactly one discovered Release ID via web or agent `link_delivery`; all existing role, task owner, idempotency, cap and ownership epoch checks remain enforced.
- Release data is read-only, size-bounded, tied to the configured repository ID, and only GitHub-authenticated evidence is labeled verified.
- Signed `release` webhook events enter the same durable bounded inbox and trigger reconciliation without persisting raw bodies.
- Hosted GUI and loopback-only local board show the same Release and bounded activity projection.
- Activity comes only from structured project records; no private transcript material is queried or persisted.
- Existing branch/PR/commit behavior and task acceptance semantics are unchanged.
- Focused and full Python suites, experiment suites, browser regressions, build and twine checks pass.
