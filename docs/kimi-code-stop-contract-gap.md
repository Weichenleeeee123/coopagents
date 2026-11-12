# Kimi Code Stop-hook stdout contract: gap note

Checked 2026-11-12 (official docs fetched fresh that day; latest Kimi Code
CLI release in the official changelog at check time: 2.5.3, 2026-11-10).
Kimi wake-up stays blocked: no documented Stop-specific stdout/JSON
contract exists. Nothing in this note is inferred from other agents.

## Pages checked

- https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html
- https://www.kimi.com/code/docs/kimi-code-cli/customization/hooks.html
  (Chinese, same substance)
- https://moonshotai.github.io/kimi-code/en/customization/hooks.html
  (identical to the English kimi.com page)
- https://github.com/moonshotai/kimi-code/blob/HEAD/docs/en/customization/hooks.md
  (docs source, same substance)

Negative checks on the English page and the docs source: `additionalContext`,
`updatedInput`, `systemMessage`, `stop_hook_active`, output size caps — zero
hits. `decision` appears only in prose ("Blocking decisions stay fail-open")
and in the single `permissionDecision` example below. `hookSpecificOutput`
appears exactly once (that example).

## What the docs do say

Stdin carries JSON with base fields `hook_event_name`, `session_id`,
`session_title`, `client_type`, `cwd` (snake_case). No Stop-specific stdin
fields are listed.

Return values are exit-code based:

| Exit | Meaning |
| --- | --- |
| `0` | Normal exit, allow; stdout content (if any) "may be appended to context" |
| `2` | Intentional block; stderr content is used as the blocking reason |
| Other non-zero / timeout / crash | Script error; default allow (fail-open) |

Only blockable events (`PreToolUse`, `Stop`, `UserPromptSubmit`) have return
values that affect the main flow; all other events are observation-only.
The Stop row is the entirety of what the docs say about Stop:

> Triggered when the model is about to end the turn; if blocked, a message
> can be appended to let the model continue.

The only JSON-stdout form documented anywhere on the page is a
permission-flavored example ("You can also return a JSON object via stdout
to block"):

```json
{"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "Please use rg instead of grep"}}
```

No scoping statement says which events this JSON form applies to, and no
other `hookSpecificOutput` fields, top-level fields, or Stop-specific JSON
shape is defined.

## The precise hole

The docs say blocking Stop lets "a message" be appended so the model
continues, but never say where that message comes from: exit-2 stderr (the
documented block reason), exit-0 stdout (documented only as "may be
appended to context"), or a JSON field. Combining the general rules
suggests exit 2 + stderr, but for Stop specifically that is inference from
general rules, not a documented Stop contract. Also undocumented: whether
Stop stdout on exit 0 is appended to context, whether the
`permissionDecision: deny` JSON blocks Stop, whether any loop guard exists
for repeated Stop blocks, whether Stop stdin carries fields beyond the base
five, and any output size cap.

One adjacent official hint is NOT a contract: changelog 2.2.0 (2026-10-14)
says "hook JSON output without a 'message' field is no longer added to the
conversation", scoped to `UserPromptSubmit` injection. It does not specify
whether `message` is top-level or nested, says nothing about Stop, and must
not be presented as a documented contract.

## Legacy-docs trap

The older docs site for the legacy Python CLI
(https://www.kimi-cli.com/en/customization/hooks.html, config path
`~/.kimi/config.toml`) DOES document Stop-specific behavior — a
`stop_hook_active` field, a one-re-trigger anti-loop rule, and a structured
Stop example. Those describe the old `kimi-cli` product, not the current
Kimi Code CLI (`~/.kimi-code/config.toml`). None of `stop_hook_active`,
the anti-loop rule, or `hookEventName` appears in any current hooks page.
Do not carry them over.

## What would close this gap

Either a live behavioral probe against an installed `kimi` binary (needs a
logged-in Kimi session; out of scope on this VM), or reading the hook-runner
source in MoonshotAI/kimi-code. Until one of those lands, any Kimi wake-up
design resting on Stop stdout JSON fields rests on undocumented behavior
and must not be built or claimed.
