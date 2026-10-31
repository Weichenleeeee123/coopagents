# Complete the approved workspace migration and refresh release documentation

The approved design remains `docs/prototypes/project-workspace/`. This work completes that migration; it does not introduce a new design direction. Earlier navigation/function acceptance did not establish visual parity.

## Stages

1. Align the real workbench shell and all project pages with the prototype: white content, light sidebar, icon navigation, breadcrumbs, restrained typography, clear page ownership, polished project switching and right-side details. Preserve existing API calls, account/session boundaries, permissions and the read-only board. Tasks open in board view; the harness matrix stays in documentation.
2. Repair delivery filtering and layout using only evidenced relationships. Hidden objects must not produce stray SVG paths; empty lanes must disappear. Run existing JavaScript regressions and add focused coverage for the identified failures.
3. Compare actual desktop and mobile browser pages with the approved prototype. Exercise project switching, six pages, settings, task details, delivery filters and a genuine backend mutation. Record screenshots and limitations; do not infer visual completion from structural tests.
4. Refresh English-default CONTRIBUTING and equivalent Chinese guidance. Simplify bilingual READMEs around product positioning, agent-first onboarding, shared context, member discovery and delivery evidence. Separate published 0.9.0 from unreleased setup diagnostics, P2P from the self-hosted workbench, and connection from wake-up.
5. Capture fresh production UI screenshots with synthetic data, document provenance, validate links and commit documentation/assets separately from implementation. Retain earlier assets and private test evidence; never delete files.

## Acceptance

- Compare the production page against the prototype, not only against prior production screenshots.
- Verify desktop and 390px mobile layout, keyboard access and details dismissal, real reads/writes, project isolation and browser console output.
- Report remaining gaps explicitly. Screenshots demonstrate the UI, not cross-computer or harness certification.
- Keep credentials, local configuration, databases and raw execution records out of Git.
- Stage commits locally; pushing and merging are outside this request.
