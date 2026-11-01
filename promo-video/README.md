# Coopagents Promo

An original three-minute animated film about Coopagents, written in Remotion and React. The main 1920 × 1080, 30 fps composition is `CoopagentsPromo`. It contains ten independent Studio compositions that follow the story from disconnected context through agent discovery, messages, work, evidence and human decisions.

The film uses the current Coopagents icon and a purpose-composed three-minute stereo synthesizer score. Re-create the waveform any time with `npm run generate:music`; no stock footage, external images or third-party music are used.

## Start the preview

```powershell
npm install
npm run dev
```

## Verify the film

```powershell
npm run verify
```

This runs ESLint and TypeScript, checks that the film and soundtrack are exactly three minutes, opens the composition in Chrome headless mode, and exports ten chapter keyframes under the repository's ignored `.local/promo-video-qa/` folder.

## Export MP4

```powershell
npm run render
```

The result is `out/coopagents-promo.mp4` in 1920 × 1080 at 30 fps with the original soundtrack mixed in. The staged copy used to repair the original interrupted npm install is retained under `.local/promo-video-verified/`; the project now runs from this directory.
