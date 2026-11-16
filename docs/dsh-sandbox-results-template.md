# DSH Sandbox Results

Use one row per attempted run, including startup failures, authentication failures, timeouts, budget stops, and incomplete runs. Fix the planned sample size and arm order before execution. Do not omit failed attempts.

## Run definition

| Field | Value |
| --- | --- |
| Run cohort / scenario seed | |
| Source commit | |
| DSH and image versions | |
| Model configuration fingerprint | |
| Planned attempts per arm | |
| Arm order method | |
| Hidden-test suite version/hash | |

## Outcomes

Report each binary outcome as `successes / all attempted runs`, with a two-sided Wilson 95% interval. Failed or unobserved outcomes count as failures; they remain in the denominator.

| Arm | Attempts | Correct current route | Verified answer use | Hidden-test success | Native success | Evidence classification |
| --- | ---: | --- | --- | --- | --- | --- |
| control | | | | | | |
| coopagents | | | | | | |

| Arm | Cost total (USD) | Input tokens | Output tokens | Requests | Missing measurements |
| --- | ---: | ---: | ---: | ---: | --- |
| control | | | | | |
| coopagents | | | | | |

Keep cost and usage as `null` when provider telemetry is missing. Do not estimate cost from token counts. State the measurement source and metric basis for every reported value.

## Failure and safety outcomes

| Arm | Startup/auth/tool-load failures | Timeouts/budget stops | Stale-route rejections | Unauthorized human-gate attempts | Hidden-test categories |
| --- | --- | --- | --- | --- | --- |
| control | | | | | |
| coopagents | | | | | |

Hidden-test evidence may include only pass/fail, a bounded category, and an output or patch hash. Never include expected values, oracle markers, hidden-test output, source snippets, prompts, or raw provider responses. Preserve per-attempt records privately and publish only approved aggregates and hashes.

## Interpretation

- Metric basis and evidence sources:
- Missing or incomplete measurements:
- Material protocol deviations:
- Limits on causal interpretation:
- Independent-user acceptance: **not established by this harness report**.

Harness-only or fixture evidence is not native success. Label native observations as unverified unless independently authenticated; do not claim independent-user acceptance from harness evidence.
