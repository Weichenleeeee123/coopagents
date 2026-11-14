import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { spawnSync } from "node:child_process";
import { bundle } from "@remotion/bundler";
import { openBrowser, getCompositions, renderStill } from "@remotion/renderer";

const root = resolve(import.meta.dirname, "..");
const output = resolve(
  root,
  "..",
  ".local",
  "promo-transition-qa",
  new Date().toISOString().replace(/[:.]/g, "-"),
);
mkdirSync(output, { recursive: true });
const serveUrl =
  process.env.PROMO_BUNDLE ||
  (await bundle({
    entryPoint: join(root, "src/index.ts"),
    outDir: join(output, "bundle"),
    rspack: true,
  }));
const browser = await openBrowser("chrome", {
  chromeMode: "chrome-for-testing",
  browserExecutable:
    process.env.PROMO_CHROME ||
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
});
const checks = [];
const errors = [];
try {
  const compositions = await getCompositions(serveUrl, {
    puppeteerInstance: browser,
  });
  const main = compositions.find((c) => c.id === "CoopagentsPromo");
  assert.ok(main);
  assert.equal(main.durationInFrames, 2640);
  for (const [name, cut] of [
    ["pain-to-connect", 480],
    ["connect-to-distance", 960],
    ["distance-to-exchange", 1440],
    ["exchange-to-payoff", 1920],
    ["payoff-to-brand", 2280],
  ]) {
    for (const offset of [-12, -1, 0, 6, 12, 24]) {
      const file = join(output, `${name}-${offset}.png`);
      await renderStill({
        serveUrl,
        composition: main,
        frame: cut + offset,
        output: file,
        scale: 0.5,
        puppeteerInstance: browser,
        onBrowserLog: (log) => {
          if (log.type === "error") errors.push(log.text);
        },
      });
      const decoded = spawnSync(
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
      assert.equal(decoded.status, 0, String(decoded.stderr));
      let visible = 0;
      for (let i = 0; i < decoded.stdout.length; i += 3)
        if (
          (decoded.stdout[i] + decoded.stdout[i + 1] + decoded.stdout[i + 2]) /
            3 <
          210
        )
          visible++;
      const ratio = visible / (240 * 135);
      assert.ok(
        ratio > 0.003,
        `${name} at ${offset}: transition became an empty light frame`,
      );
      checks.push({
        name,
        offset,
        visiblePercent: Math.round(ratio * 1000) / 10,
      });
    }
    console.log(`PASS ${name}: before, cut, overlap, after`);
  }
  assert.deepEqual(errors, []);
  writeFileSync(
    join(output, "transitions.json"),
    JSON.stringify({ checks, errors, output }, null, 2),
  );
  console.log(output);
} finally {
  await browser.close({ silent: true });
}
