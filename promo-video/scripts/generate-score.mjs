import { writeFileSync } from "node:fs";
import { join } from "node:path";

const sampleRate = 22050;
const seconds = 180;
const beatsPerMinute = 96;
const beatLength = 60 / beatsPerMinute;
const sampleCount = sampleRate * seconds;
const wav = Buffer.alloc(44 + sampleCount * 4);
const sineSize = 4096;
const sine = Float32Array.from({ length: sineSize }, (_, i) => Math.sin((i * Math.PI * 2) / sineSize));
const melodyChords = [
  { root: 146.83, third: 185.00, fifth: 220.00, seventh: 277.18, ninth: 329.63 },
  { root: 110.00, third: 138.59, fifth: 164.81, seventh: 196.00, ninth: 246.94 },
  { root: 130.81, third: 164.81, fifth: 196.00, seventh: 246.94, ninth: 293.66 },
  { root: 98.00, third: 123.47, fifth: 146.83, seventh: 185.00, ninth: 220.00 },
  { root: 123.47, third: 146.83, fifth: 185.00, seventh: 220.00, ninth: 277.18 },
  { root: 110.00, third: 138.59, fifth: 164.81, seventh: 207.65, ninth: 246.94 },
  { root: 146.83, third: 185.00, fifth: 220.00, seventh: 261.63, ninth: 329.63 },
  { root: 98.00, third: 123.47, fifth: 146.83, seventh: 196.00, ninth: 246.94 },
];
const arpeggio = ["root", "fifth", "ninth", "third", "fifth", "seventh", "ninth", "fifth"];
const melody = ["ninth", "fifth", "seventh", "third", "fifth", "ninth", "seventh", "fifth"];

wav.write("RIFF", 0);
wav.writeUInt32LE(wav.length - 8, 4);
wav.write("WAVEfmt ", 8);
wav.writeUInt32LE(16, 16);
wav.writeUInt16LE(1, 20);
wav.writeUInt16LE(2, 22);
wav.writeUInt32LE(sampleRate, 24);
wav.writeUInt32LE(sampleRate * 4, 28);
wav.writeUInt16LE(4, 32);
wav.writeUInt16LE(16, 34);
wav.write("data", 36);
wav.writeUInt32LE(sampleCount * 4, 40);

const osc = (hz, time) => sine[Math.floor((((hz * time) % 1 + 1) % 1) * sineSize)];
const smoothAttack = (age, length) => Math.max(0, Math.min(1, age / length));

for (let i = 0; i < sampleCount; i++) {
  const t = i / sampleRate;
  const beat = t / beatLength;
  const bar = Math.floor(beat / 4);
  const beatInBar = beat % 4;
  const chord = melodyChords[bar % melodyChords.length];
  const fadeIn = Math.min(1, t / 3);
  const fadeOut = Math.min(1, (seconds - t) / 4);
  const master = Math.min(fadeIn, fadeOut);

  const previous = melodyChords[(bar + melodyChords.length - 1) % melodyChords.length];
  const padVoice = (harmony) => osc(harmony.root,t)*.070 + osc(harmony.fifth,t+.003)*.043 + osc(harmony.seventh*2,t+.007)*.022 + osc(harmony.ninth*2,t+.011)*.016;
  const chordFade = smoothAttack(beatInBar * beatLength, .28);
  const pad = padVoice(previous)*(1-chordFade) + padVoice(chord)*chordFade;
  const bassEnv = smoothAttack(beatInBar, 0.08) * Math.exp(-beatInBar * 0.65);
  const bass = osc(chord.root / 2, t) * bassEnv * 0.095;

  const step = beat / 2;
  const stepIndex = Math.floor(step);
  const pluckAge = (step - stepIndex) * beatLength * 2;
  const pluckName = arpeggio[(stepIndex + Math.floor(bar / 8)) % arpeggio.length];
  const pluckHz = chord[pluckName] * 2;
  const pluckEnv = smoothAttack(pluckAge,.008)*Math.exp(-pluckAge * 5.8) * (stepIndex % 4 === 3 ? 0.47 : 1) * smoothAttack(t-8,8);
  const pluck = (osc(pluckHz, pluckAge) + osc(pluckHz * 2.01, pluckAge) * 0.22) * pluckEnv * 0.048;

  const melodyStep = beat % 8;
  const melodyAge = (melodyStep % 2) * beatLength;
  const melodyName = melody[bar % melody.length];
  const leadEnv = smoothAttack(melodyAge,.03)*Math.exp(-melodyAge * 2.7)*smoothAttack(t-45,10);
  const leadHz = chord[melodyName] * 2;
  const lead = (osc(leadHz, melodyAge) + osc(leadHz * 2, melodyAge) * 0.16) * leadEnv * 0.030;

  const kickAge = beat % 2;
  const rhythmIn = smoothAttack(t-28,8)*Math.min(1,(seconds-t)/18);
  const kick = osc(52 + 18 * Math.exp(-kickAge * 18), kickAge) * Math.exp(-kickAge * 7) * 0.055 * rhythmIn;
  const value = Math.max(-0.82, Math.min(0.82, (pad + bass + pluck + lead + kick) * master * 1.8));
  const side = (pad * 0.18 + pluck * 0.82 + lead * 0.5) * master * 1.8;
  const offset = 44 + i * 4;
  wav.writeInt16LE(Math.round(value * 32767), offset);
  wav.writeInt16LE(Math.round(Math.max(-0.82, Math.min(0.82, value * 0.78 + side)) * 32767), offset + 2);
}

const output = join(import.meta.dirname, "..", "public", "coopagents-original-score.wav");
writeFileSync(output, wav);
console.log(`Wrote ${seconds}s, ${sampleRate}Hz stereo score: ${output}`);
