# 0.9 Project Assets and Activity Report

Status: Stages 1-4 and final 0.9 local/package acceptance are complete. The full release report is [release-0.9-report.md](release-0.9-report.md); native hook/wake claims remain conservative.

## Delivered

- Members explicitly upload one file at a time. Selecting a file does not upload it, and there is no workspace or repository scanning.
- Asset metadata is project-scoped and includes uploader, file name, media type, byte length, SHA-256, source kind, source reference and creation time. Source kinds include upload, project-relative path, commit, pull request and release.
- Project-relative paths reject absolute paths, drive-qualified paths, backslashes and `..` traversal. Commit/PR/Release references are explicit member-provided strings; they are not silently inferred or remotely verified.
- File bytes live beside SQLite in `<database filename>.assets/`. Defaults are 10 MiB per file, 100 MiB per project and 1 GiB per service. The supported single-file maximum is 10 MiB so HTTP and MCP limits stay aligned. Environment overrides are `COOPAGENTS_ASSET_MAX_FILE_BYTES`, `COOPAGENTS_ASSET_MAX_PROJECT_BYTES` and `COOPAGENTS_ASSET_MAX_TOTAL_BYTES`.
- Authenticated HTTP supports multipart upload, listing and attachment download. Downloads return `nosniff`, no-store, byte length and SHA-256 headers. MCP provides `list_assets` and `read_asset`; reads include bounded base64 bytes and the same digest.
- Paired database/asset backup and restore validate every referenced content digest and refuse existing destinations. SQLite-only backups intentionally do not include asset bytes.
- The service-wide quota counts registered asset bytes and all top-level `.blob` files, including retained unreferenced files from failed writes. No automatic cleanup is performed.
- The self-hosted workbench shows source/uploader/hash/size, supports refresh and download, and clears the previous project list on project change. Activity filters by type, source and task, labels stale/unavailable GitHub facts, and can open the related task.
- The default account-service web page now serves its existing `board.js` and `realtime_client.js` assets through the public static allowlist; a real browser had exposed their previous 401 responses.

## Verification

- Complete Python suite: 607 tests passed on Python 3.13.3 with the service and space extras installed; one Windows symlink-mode test is skipped.
- All 13 JavaScript regression scripts passed, including asset-panel explicit upload/project switching, activity filtering/task navigation, existing account and Git regressions.
- Live loopback browser flow created a local test account and two projects, uploaded and downloaded `README.md`, associated a second upload with `docs/README.md`, and confirmed the asset only appeared in its owning project. After fixing the static allowlist, page reload had zero console errors and the MCP real-time state showed online.
- At a 390px viewport, `document.documentElement.scrollWidth` and `document.body.scrollWidth` both remained 390px. Asset controls and activity filters were visible without horizontal overflow.
- The browser was local to `127.0.0.1`; its database and uploaded files remain in the ignored `.local/asset-ui-qa.sqlite3` and `.local/asset-ui-qa.sqlite3.assets/`. This does not establish multi-device behavior or a public deployment.

## Boundaries

- No full transcript, prompt, response, hidden reasoning or tool input/output is read, stored, uploaded or rendered. Activity still comes only from typed collaboration records and Git observations.
- Revoked membership is rejected by the shared credential resolver; cross-project listing/download is not found. Unit and real-HTTP regressions cover both. The browser walkthrough used one account and two projects, not two real members.
- The local P2P board remains read-only and received no remote asset-management routes.
- Asset references to Git objects are explicit metadata only. They do not prove the referenced commit, PR or release exists. Real GitHub App acceptance remains deferred to 1.0.
- Harness MCP adapters are covered in [harness-adapters-0.9.md](harness-adapters-0.9.md). Native hooks, ACP and idle wake remain unverified or unsupported as shown there.
- The final 0.9 package/deployment evidence is recorded in [release-0.9-report.md](release-0.9-report.md).
