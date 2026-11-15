# Coopagents Promotional Film

## Story

The advert leads with a team pain point: people copying questions between coding agents, explaining the same requirements again, and becoming the coordination bottleneck. A close-up code session and the question chip establish this as real developer work; the human cursor and repeated request reveal the relay burden.

Coopagents then connects Claude Code and Codex across laptop, desktop and a schematic globe. The worked example stays concrete: a question asks which field holds login status, a shared API agreement supplies `status`, the reply updates `login.ts`, and a review action remains with the human. The closing payoff is **Agents. Devices. Places. Connected.** and **Let your agents work together.**

The advert is English throughout. It contains six 6-8 second chapters with fast internal action changes and lasts 2,640 frames at 60 fps (44 seconds). The user-supplied Funk Caravan original plays from the start and fades during the final three seconds.

## Visual Direction

- Product neutrals: paper `#F7F8FA`, white surfaces and graphite `#202124`, based on the production stylesheet.
- Coral identifies Claude Code, blue identifies Codex, and green/mint carries shared context. A graphite cursor identifies the human action.
- Device rooms, the 09:41/17:41 clocks and geographic silhouette are illustrative. The globe does not claim measured latency, guaranteed reachability, or completed cross-platform certification.
- The product's white, paper and graphite palette remains the base. Accent colors identify the source, destination and shared result.
- Dimensional laptop and desktop illustrations create two real workspaces; a paper agreement provides a tangible answer artifact.
- One context packet carries through agent connection, a schematic long-distance route, the sourced answer and the updated code. Cuts are short and hard; movement inside the shots follows the user's action rather than decorative orbits.
- Terminal content is a quick setup cue and developer work occurs in detailed, angled device scenes rather than long static terminal shots.

## Product Boundaries

All people, task data and terminal results are explicitly illustrative. The English workbench is a UI illustration, not a recording of a live team. Setup saved, a fresh native session, identity verification, member registration, message reading, replies and human decisions are separate concepts. Ordinary agent tools do not imply authority to approve agreements or change permissions.

The displayed MCP vocabulary is checked against `src/mcp_service.py`. The narrative does not claim every task follows a fixed delivery pipeline, that a connection proves a model is active, or that private agent transcripts are shared.

## Source And Validation

The active advert is in `promo-video/src/ad/LaunchFilm.tsx` and `launchArt.ts`; earlier explorations remain in the repository but are not part of the master cut.

`npm run verify` checks the 44-second composition, six chapters, the original local audio file, English active copy, browser errors, continuing visual change and the light product stage. It exports two sample frames per chapter under ignored `.local/promo-ad-qa/`.

`npm run verify:transitions` inspects frames around all five chapter cuts for empty flashes. Review the output visually as well; pixel metrics alone do not judge motion-design quality.

`npm run verify:audio`, with `PROMO_BUNDLE` set to an already verified bundle, renders the actual composition's audio to an ignored QA file. It checks the 44-second duration and falling RMS gain through the 41-44 second fade. It does not export a deliverable MP4.

The launch cut has 20 internal visual beats, including the opening device closeup, copy/paste pair, request pileup, connection reveal, 1.75-second natural-language setup prompt, device pair, regional pullback, request flight, agreement closeup, code replacement, review and brand. Six chapters group these beats for editing; chapter count is not shot count. The five main cuts use matching leftward exit/entry velocity, with fast internal hard cuts for contrast.

Earlier generators now require `--legacy` before overwriting the active timeline. No earlier file or recording was deleted.

The user-supplied M4A and its derived audio envelope stay local and are excluded from Git. The original file is retained. Earlier source iterations and reference captures are also retained.

## Public References

- [Remotion audio visualization](https://www.remotion.dev/docs/audio/visualization): derive frame-indexed audio data for synchronized visual changes.
- [Official Remotion motion and transition skills](https://github.com/remotion-dev/skills/tree/main/skills/remotion-markup): deterministic frame-driven animation and transition construction.
- [Ben Marriott: This Animation Technique Works Every Time](https://www.youtube.com/watch?v=ythBGTLjot8): connect cuts through shared subject, scale or movement, while keeping large transitions selective.
