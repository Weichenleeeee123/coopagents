# Coopagents Promo Video

The code-authored Remotion project in `promo-video/` produces an 180-second, 1920 × 1080, 30 fps film. Ten independently editable compositions cover:

1. Different agents and a shared mission
2. The distance between private work contexts
3. Connecting agents through MCP
4. Shared context
5. Direct questions and replies
6. Tasks and dependencies
7. Delivery evidence linked to Git objects
8. P2P and self-hosted options
9. Human control over important decisions
10. The closing Coopagents mark

It uses the current Coopagents icon and a custom three-minute stereo synth score. `promo-video/scripts/generate-score.mjs` deterministically generates the PCM WAV without stock footage, a third-party music track or external visual assets.

Run `npm run dev` from `promo-video/` to open Studio. Run `npm run verify` to lint, type-check, validate the 180-second soundtrack and composition, and export one QA still from every scene. Run `npm run render` to export `promo-video/out/coopagents-promo.mp4` at full resolution.

The installation initially interrupted by the full system drive contained incomplete packages. Its package lock and conflicting package files are preserved under ignored `.local/`. A complete npm installation from the official registry now lives in `promo-video/node_modules`, and the project commands run from the project directory.
