# Coopagents Promo

The current English advert is a 44-second, 1080p60 launch film using the supplied Funk Caravan track with a three-second fade-out.

It opens with the human relay problem, then shows agents connecting across real device setups and regions, a question and sourced answer, the answer turning into code, and the human review. Each 6-8 second chapter changes composition several times instead of holding a title card. The light product palette is grounded with dimensional devices, editorial closeups, staged depth and a moving shared-context motif.

## Run

The original recording stays at `public/funk-caravan.m4a` and is excluded from Git. The composition ends the music after 44 seconds with a three-second volume fade. Python 3 and FFmpeg must be on PATH for the music analyzer.

```powershell
npm run dev
npm run verify
npm run verify:transitions
```

The main Studio composition is `CoopagentsPromo`. Six individual `Launch-*` sections are also available for inspection.

Edit `src/ad/LaunchFilm.tsx` for timing and `src/ad/launchArt.ts` for artwork. The `storyboard` and `promo-cut` commands are legacy generators for retained earlier cuts; they must not be used to update the launch film because they overwrite `Film.tsx` and `Root.tsx`.

`npm run render` exports an MP4 when requested. The maintained creative brief, evidence boundaries and references are in `../docs/coopagents-promo-video.md`.
