# Coopagents Promo: Motion-Design Methodology

This memo records the research completed before the next visual revision. It is the
creative gate for the Coopagents promotional film, not a production script.

## Implementation status — November 1, 2026

The first 15-second craft study failed visual review: it still used sparse device boxes
and straight connecting lines, and a device overlapped the title. Its files are retained
but it is not registered in Studio. The resumed work replaces the master with a
44-second launch cut in `promo-video/src/ad/LaunchFilm.tsx` and `launchArt.ts`.
The new cut uses dimensional devices, concrete request/reply content, a paper agreement,
two workspace islands, a schematic regional pullback, a code edit and human review.
It keeps English copy, the supplied soundtrack and the light product palette.
The detailed production state and checks are in [the film guide](coopagents-promo-video.md).
The research notes below record the reasoning that led to this pass; they are not a new
approval request or an instruction to stop production.

## Research-backed workflow

### 1. Define one visual idea before building scenes

School of Motion's production guide starts with a concrete concept and action, then
uses a moodboard, storyboard, styleframes, animatic, production boards, animation and
sound polish. The stated reason for the intermediate steps is to expose composition and
timing problems while they are still cheap to change.

- [A Guide to Completing Your Motion Design Project](https://schoolofmotion.com/blog/guide-completing-motion-design-project)
- [What Are Animatics, and Why Are They Important?](https://schoolofmotion.com/blog/what-are-animatics-and-why-are-they-important)
- [5 Storyboard Checks That Catch Problems Before You Animate](https://schoolofmotion.com/blog/5-storyboard-checks-before-you-animate)

Application to Coopagents: stop treating the current canvas renderer as the design
process. First approve a small set of finished visual frames and a music-timed animatic;
then animate those frames.

### 2. Make every shot perform one verb

The storyboard checks recommend one clear story beat per panel and a specific verb for
the action. “Robot pushes,” “ball travels,” “button activates” is easier to understand
than one frame that tries to show the whole chain at once.

Application to Coopagents: each shot must show a visible cause and result, for example:

1. A person receives two incompatible agent requests.
2. The person drags one requirement across the room into the other agent.
3. The requirement becomes a shared thread that crosses a laptop, desktop and map.
4. A remote agent answers with a concrete field and source.
5. The answer snaps into the codebase and attaches to task/evidence.
6. The human approves the outcome while the relay path disappears.

The visual should carry the explanation. On-screen copy should name the beat, not narrate
every object.

### 3. Use styleframes to establish craft, not decoration

The styleframe step exists to make the final art direction visible before animation:
composition, type treatment, object detail, material, color, light and density. A useful
styleframe is a finished frame from the film, not a moodboard or a collection of generic
cards. The [Art of Styleframe reference](https://artofstyleframe.com/) makes the same
distinction: hierarchy, type and color decide whether a frame reads immediately.

Application to Coopagents: produce three key frames before rewriting the whole cut:

- **Pain:** a cinematic relay composition with a clear human bottleneck, layered
  documents/messages and directional motion cues.
- **Connection:** one shared context thread physically linking agents, devices and
  regions, with a visible handoff rather than a node diagram.
- **Payoff:** a concrete code change, evidence trail and human approval in one clean
  composition.

These frames should have enough texture and depth to prove the film is designed, while
keeping the product palette light and the accent colors purposeful.

### 4. Build an animatic before full animation

An animatic is a rough sequence timed to music or voiceover. School of Motion's guidance
is to place the boards on the timeline, sync them to the track, add simple movement and
use that cut to find dead time, rushed beats and weak transitions before production.

Application to the supplied Funk Caravan track: use the first 45–60 seconds as the
working edit, cut on musical phrases, and reserve the final phrase for the payoff and
logo. The film should have a deliberate energy curve:

| Section | Energy | Job |
| --- | --- | --- |
| 0–5s | immediate | show the human relay pain in one readable action |
| 5–18s | rising | connect agents, devices and regions through one carrier |
| 18–32s | peak | show a question, answer and code transformation |
| 32–45s | release | show traceable work and retained human control |
| 45–60s | resolve | brand payoff, then audio fade |

The exact cut points should follow the track after a beat pass, but the pacing must vary;
constant medium-speed motion is the source of the current sluggish feel.

### 5. Treat transitions as continuity, not effects

The [motion-doctrine skill](https://github.com/heygen-com/hyperframes/blob/main/.agents/skills/motion-doctrine/SKILL.md)
defines a useful seam rule: the outgoing motion determines the incoming motion. Match
axis, direction and speed, cut while both sides are moving, and hand a concrete carrier
across the seam. Its companion [cut-the-curve skill](https://github.com/heygen-com/hyperframes/blob/main/.agents/skills/cut-the-curve/SKILL.md)
describes partial travel, mirrored easing, waterfall text handoffs and reserved use of
zoom or blur.

Application to Coopagents: use one dominant travel direction for ordinary seams and let
the same object carry the viewer across scenes. A message chip can become a shared
context thread; that thread can become a route on the globe; the route can become a code
underline; the underline can become an evidence link. The cut is then motivated by the
product action.

### 6. Motion must perform work

The motion-doctrine skill explicitly rejects idle wobble, breathing, floating and glow
loops used only to fill time. Every pause should either reveal information, let a result
land, or create a short stillness before a payoff. It also recommends limiting the film to
two or three transition families and repeating them consistently.

Application to Coopagents: remove decorative oscillation and replace it with staged
reveals, purposeful camera travel, UI state changes, cursor-led actions or object
transformations. The current film's repeated orbiting nodes and persistent text fail this
test because they move without changing the viewer's understanding.

### 7. Use a small, reputable skill set

The research found three relevant sources with different roles:

- [Remotion official skills](https://github.com/remotion-dev/skills): implementation
  guidance for frame-driven animation, audio and transitions. The repository has more
  than 6,000 GitHub stars and is the appropriate technical reference for Remotion.
- [motion-video skill](https://github.com/farhan-syah/motion-video-skill): a compact
  workflow that explicitly requires direction, concepts, sound design, per-scene checks
  and a final craft review. Its repository has 49 stars, so it is useful as a workflow
  reference but not treated as an authority. Its [direction guide](https://github.com/farhan-syah/motion-video-skill/blob/main/references/direction.md)
  adds two rules that matter here: the first two seconds must orient a stranger, and
  every feature needs a physical verb moment. Its [concept guide](https://github.com/farhan-syah/motion-video-skill/blob/main/references/concepts.md)
  warns that a fixed headline-plus-panel recipe becomes a slide deck; beats should be
  1.5–4 seconds, vary in length, and carry the eye through a changing object.
- [motion-doctrine in HyperFrames](https://github.com/heygen-com/hyperframes/tree/main/.agents/skills/motion-doctrine):
  a high-star repository's seam and continuity rules for multi-scene launch films. The
  repository has more than 70,000 stars; the specific skill is especially useful for
  preventing the “stack of slides” feeling.

No new package or skill is installed in this research pass. The goal is to apply the
methodology to the existing project and keep the source of truth inspectable in `docs/`.

## Diagnosis of the current cut

The active 54-second cut is technically coherent but creatively under-designed against
the research criteria:

- Large words such as `COPY`, `PASTE` and `EXPLAIN` are clear labels, but they are not
  yet a sequence of physical actions with cause and payoff.
- Agent glyphs, beams, globe arcs and pages form an infographic vocabulary, but the
  film lacks a hero object with changing state. The viewer sees symbols, not a working
  collaboration.
- The terminal strip is a texture beat rather than a meaningful action; extended terminal
  time therefore feels slow and disconnected.
- The eight broad beats are closer to title cards than a shot-driven advert. Each beat
  needs two or three purposeful sub-actions with changing composition and a carrier into
  the next beat.
- The light palette is directionally right, but the frames need richer material treatment,
  depth, scale contrast and controlled accent color to read as designed brand film work.

## Production decision for the next pass

The next pass should be a short craft test before a full rewrite:

1. Build three styleframes for Pain, Connection and Payoff using the existing product
   palette and one shared visual carrier.
2. Cut those frames to a 12–15 second music-synced animatic with no explanatory copy
   beyond the hook and payoff.
3. Apply the carrier and seam rules to one transition between each styleframe.
4. Review the animatic at normal speed and muted. If the action is unclear without text,
   revise the visual before expanding the sequence.
5. Only after that test reads clearly, rebuild the one-minute master around the approved
   visual language.

This sequence directly addresses the user's complaint: simple should mean a few strong,
readable actions with art direction, not a sparse set of cards and symbols.

