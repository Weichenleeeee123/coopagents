"""Extract deterministic audio envelopes from the supplied local soundtrack."""
import array
import json
import math
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
MUSIC = ROOT / 'public' / 'funk-caravan.m4a'
FPS = 60
RATE = 8000
ffmpeg = shutil.which('ffmpeg')
if not ffmpeg:
    raise SystemExit('Install FFmpeg or put it on PATH before analyzing the music.')
process = subprocess.run([ffmpeg, '-v', 'error', '-i', str(MUSIC), '-ac', '1', '-ar', str(RATE), '-f', 's16le', 'pipe:1'], capture_output=True, check=True)
pcm = array.array('h', process.stdout)
bass = 0.0
smooth = 0.0
bands = []
buffer = [0.0, 0.0, 0.0]
count = 0
for i, value in enumerate(pcm):
    x = value / 32768
    bass += .1 * (x - bass)
    smooth += .75 * (x - smooth)
    buffer[0] += bass * bass
    buffer[1] += x * x
    buffer[2] += (x - smooth) ** 2
    count += 1
    if (i+1) * FPS // RATE > i * FPS // RATE:
        bands.append([math.sqrt(v/count) for v in buffer])
        buffer = [0.0, 0.0, 0.0]
        count = 0
if count:
    bands.append([math.sqrt(v/count) for v in buffer])
normalizers = [sorted(row[j] for row in bands)[int(len(bands)*.94)] for j in range(3)]
normalized = [[round(min(1.3, value/max(normalizers[j],.0001)),4) for j,value in enumerate(row)] for row in bands]
output = ROOT / 'src' / 'motion' / 'audio-envelope.ts'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text('// Generated from the locally supplied Funk Caravan recording. 60 samples per second.\nexport const AUDIO_ENVELOPE: readonly (readonly [number, number, number])[] = '+json.dumps(normalized,separators=(',',':'))+';\n', encoding='utf-8')
print(json.dumps({'audio_seconds':len(pcm)/RATE,'envelope_frames':len(normalized),'fps':FPS,'output':str(output)},ensure_ascii=False))
