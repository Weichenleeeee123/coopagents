import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { spawnSync } from "node:child_process";
import { bundle } from "@remotion/bundler";
import { openBrowser, getCompositions, renderStill } from "@remotion/renderer";

const root = resolve(import.meta.dirname, "..");
const output = resolve(
  root,
  "..",
  ".local",
  "promo-ad-qa",
  new Date().toISOString().replace(/[:.]/g, "-"),
);
mkdirSync(output, { recursive: true });
const music = join(root, "public", "funk-caravan.m4a");
const ffprobe = join(
  root,
  "node_modules",
  "@remotion",
  "compositor-win32-x64-msvc",
  "ffprobe.exe",
);
const probe = spawnSync(
  ffprobe,
  ["-v", "error", "-show_entries", "format=duration", "-of", "json", music],
  { encoding: "utf8" },
);
assert.equal(probe.status, 0, "original supplied audio must decode");
const audioDuration = Number(JSON.parse(probe.stdout).format.duration);
assert.ok(audioDuration > 44);
const active = [
  "src/Film.tsx",
  "src/Root.tsx",
  "src/ad/LaunchFilm.tsx",
  "src/ad/launchArt.ts",
];
for (const file of active)
  assert.ok(
    !/[\u3400-\u9fff]/u.test(readFileSync(join(root, file), "utf8")),
    `${file} must stay English`,
  );
const serveUrl = await bundle({
  entryPoint: join(root, "src/index.ts"),
  outDir: join(output, "bundle"),
  rspack: true,
});
const browser = await openBrowser("chrome", {
  chromeMode: "chrome-for-testing",
  browserExecutable:
    process.env.PROMO_CHROME ||
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
});
const errors = [];
const starts = [0, 480, 960, 1440, 1920, 2280];
const names = ["pain", "connect", "distance", "exchange", "payoff", "brand"];
try {
  const compositions = await getCompositions(serveUrl, {
    puppeteerInstance: browser,
  });
  const main = compositions.find((c) => c.id === "CoopagentsPromo");
  assert.ok(main);
  assert.equal(main.durationInFrames, 2640);
  assert.equal(main.fps, 60);
  assert.equal(main.width, 1920);
  assert.equal(main.height, 1080);
  const scenes = compositions.filter((c) => c.id.startsWith("Launch-"));
  assert.equal(scenes.length, 6);
  assert.equal(main.durationInFrames, starts[5] + 360);
  const motion = [];
  for (let i = 0; i < starts.length; i++) {
    const first = join(output, `${names[i]}.png`),
      second = join(output, `${names[i]}-later.png`);
    for (const [at, file] of [
      [starts[i] + 45, first],
      [starts[i] + 150, second],
    ])
      await renderStill({
        serveUrl,
        composition: main,
        frame: at,
        puppeteerInstance: browser,
        output: file,
        scale: 0.5,
        onBrowserLog: (log) => {
          if (log.type === "error") errors.push(log.text);
        },
      });
    const decode = (file) => {
      const r = spawnSync(
        process.env.PROMO_FFMPEG || "ffmpeg",
        [
          "-v",
          "error",
          "-i",
          file,
          "-vf",
          "scale=240:135",
          "-f",
          "rawvideo",
          "-pix_fmt",
          "rgb24",
          "pipe:1",
        ],
        { maxBuffer: 1024 * 1024 },
      );
      assert.equal(r.status, 0, String(r.stderr));
      return r.stdout;
    };
    const a = decode(first),
      b = decode(second);
    let changed = 0,
      light = 0;
    for (let j = 0; j < a.length; j += 3) {
      if (
        Math.abs(a[j] - b[j]) +
          Math.abs(a[j + 1] - b[j + 1]) +
          Math.abs(a[j + 2] - b[j + 2]) >
        36
      )
        changed++;
      if ((a[j] + a[j + 1] + a[j + 2]) / 3 > 215) light++;
    }
    const changePct = changed / (a.length / 3);
    const lightPct = light / (a.length / 3);
    assert.ok(changePct > 0.005, `${names[i]} must move; ${changePct}`);
    assert.ok(
      lightPct > 0.5,
      `${names[i]} must retain light product stage; ${lightPct}`,
    );
    motion.push({
      name: names[i],
      changedPixelsPercent: +(changePct * 100).toFixed(2),
      lightPercent: +(lightPct * 100).toFixed(2),
    });
    console.log(`PASS ${names[i]} / motion ${(changePct * 100).toFixed(1)}%`);
  }
  assert.deepEqual(errors, []);
  const report = {
    duration: 44,
    fps: 60,
    width: 1920,
    height: 1080,
    chapterCount: 6,
    visualBeatCount: 20,
    music: {
      file: "funk-caravan.m4a",
      sourceDuration: audioDuration,
      usedDuration: 44,
      fadeOutSeconds: 3,
    },
    motion,
    browserErrors: errors,
    output,
  };
  writeFileSync(
    join(output, "verification.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report));
} finally {
  await browser.close({ silent: true });
}
