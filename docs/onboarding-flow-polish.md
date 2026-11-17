# Onboarding diagnostics and release follow-up

This change addresses audit findings F-01, F-02, F-03, F-05, F-06 and F-08. F-04's checkpoint vocabulary is already fixed and is unchanged.

## Packaging investigation (F-06)

The backend is setuptools, not Hatch. `packages = ["coopagents"]` and `package-dir = {coopagents = "src"}` include all Python modules directly under `src/`, including `onboarding_doctor.py`. `space_runtime.main` already exposes the doctor subcommand. There is no doctor exclusion or missing entry point to fix in this checkout: published 0.9.0 predates those commits. Adding a second module/entry point would not fix that release gap.

The actual packaging omission was the maintained setup guide. The new `tool.setuptools.data-files` entry includes the English guide and its Chinese companion in both distributions, installing them at `<environment>/share/coopagents/`. The wheel must contain `coopagents/onboarding_doctor.py`, `coopagents/space_runtime.py`, and both guide files. The source distribution must contain the same sources and `docs/agent-first-setup*.md`.

## Remaining release step

No package was published, and no tag or remote Git state was changed. A maintainer must:

1. Choose a new, unused release version and update `project.version` in `pyproject.toml` as part of the existing release process. Do not replace an existing PyPI artifact. A pre-release alone will not reach fresh users who follow the default stable-version rule.
2. After the release checks pass, build from the release commit with `<python> -m build --outdir <new-artifact-directory>`. Verify the wheel and source distribution contents listed above, and smoke-test `python -m coopagents.space_runtime doctor --help` from an isolated wheel install.
3. Create the matching `v<version>` GitHub release with that wheel, source distribution and `SHA256SUMS.txt`. Publishing the GitHub release triggers `.github/workflows/publish.yml`, which verifies the asset hashes and publishes those exact files to PyPI through Trusted Publishing.
4. Verify installation of `coopagents[space]==<version>` from PyPI and the matching tag's Skill. Update the README release-status text only after publication is verified.

The release version/channel is the remaining maintainer decision. Published 0.9.0 cannot acquire doctor retroactively. This branch's version was not changed or represented as a newly published release.

## Evidence limits

- A UDP probe sends one byte to its own loopback socket. OS permission denial is observable; the responsible sandbox/firewall policy is not. A successful send does not prove Internet UDP or relay access.
- No home relay in the first 30 seconds is reported as starting. After that, relay availability remains unverified; a missing relay does not prove the relay service is down. A recovered live relay clears the offline diagnostic.
- Native login checks use only `codex login status` or Claude Code's JSON `auth status`; native output is not echoed. Provider-aware backend probing is unimplemented. No model turn or quota is used. The user must authorize and complete a real model turn separately.
- Repository binding is a separate manager operation. Doctor reads `/api/git` while its verified link remains open and never binds automatically, fetches, pushes, accepts tasks or merges.
