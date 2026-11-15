import {readFileSync, writeFileSync} from 'node:fs';
import {resolve, join} from 'node:path';

const root=resolve(import.meta.dirname,'..');
if(!process.argv.includes('--legacy')) throw new Error('Legacy generator: would replace the 44-second launch film. Pass --legacy only to deliberately restore the earlier cut.');
const shots=JSON.parse(readFileSync(join(root,'src/story/shots.json'),'utf8'));
const cut=[
  [0,180], [1,180], [2,180], [4,210], [5,240], [6,240], [10,180],
  [14,210], [17,240], [19,240], [24,240], [25,240], [28,240], [30,480],
];
let offset=0;
const sequences=cut.map(([shotId,duration],i)=>{
  const shot=shots[shotId]; const from=offset; offset+=duration;
  return `    <Sequence${from?' from={'+from+'}':''} durationInFrames={${duration}} name={${JSON.stringify(String(i+1).padStart(2,'0')+' · '+shot.caption)}} premountFor={fps}><StoryStage shotId={${shotId}}/></Sequence>`;
}).join('\n');
writeFileSync(join(root,'src/Film.tsx'),`import {AbsoluteFill,Sequence,staticFile,useCurrentFrame,useVideoConfig,interpolate} from 'remotion';\nimport {Audio} from '@remotion/media';\nimport {StoryStage} from './story/StoryStage';\nimport {ContinuityBridge} from './story/ContinuityBridge';\n\nexport const Film=()=>{\n const {fps}=useVideoConfig();\n const frame=useCurrentFrame();\n const musicVolume=interpolate(frame,[0,45,${offset-120},${offset}],[0,.85,.85,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});\n return <AbsoluteFill style={{background:'#F7F8FA'}}>\n${sequences}\n  <ContinuityBridge/>\n  <Audio name="Funk Caravan / Supplied soundtrack" src={staticFile('funk-caravan.m4a')} volume={musicVolume} premountFor={fps}/>\n </AbsoluteFill>;\n};\n`);
console.log(`Built the promo cut with ${cut.length} shots and ${offset} frames (${(offset/60).toFixed(2)} seconds).`);
