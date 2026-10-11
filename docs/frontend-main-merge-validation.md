# Frontend merge into main — 2026-10-11

Integrated the approved monochrome industrial frontend (`314cde8`) with main's collaboration, task lifecycle and dependency work (`421af5d`). All files and existing branches are retained.

## Conflict resolution

- Keep the four account views, task summary, square controls, monochrome palette and three-column desktop task board.
- Load collaboration, lifecycle and dependency modules and preserve their panels, task actions, ownership history, safe polling and project isolation.
- Include cancelled task filtering and reset all task filters together. Extend the toolbar wrapping for narrow screens.
- Preserve both sets of session regression assertions and all documentation index entries.
- Count unresolved dependency requests only for their current route, consistent with the overview.

## Verification

- Full product suite: 412 tests passed (`python -m unittest discover -s tests -v`).
- Agent integration experiment suite: 21 tests passed.
- All seven frontend regression scripts passed; all seven frontend JavaScript files passed syntax checks.
- Browser checks against a fresh synthetic local database: task board, overview and repository at widths 1440, 1280, 768, 390 and 320 without document overflow.
- All-state view has six columns; cancelled view has one. Task detail mounts both lifecycle and dependency sections, including at 320px without dialog overflow.
- Repository collaboration diagnostics and private agent setup both mount successfully.
- Existing account and billing browser flows passed before the final billing return navigation; that first harness used an obsolete QA port. A corrected merge-specific browser check passed independently.
- No unresolved Git conflict markers or whitespace errors.

Browser evidence and synthetic data are retained outside Git under `.local/main-merge-qa-20261011/`. These checks do not claim production deployment, live OAuth/Stripe verification or native cross-machine agent acceptance.
