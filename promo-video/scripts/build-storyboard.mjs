import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
const root=resolve(import.meta.dirname,'..');
if(!process.argv.includes('--legacy')) throw new Error('Legacy generator: would replace the 44-second launch film. Pass --legacy only to deliberately restore the earlier cut.');
const shots=JSON.parse(readFileSync(join(root,'src/story/shots.json'),'utf8'));
// Extending outgoing shots by 24 frames creates overlap; fixed starts and the master duration do not change.
const sequence=shots.map(s=>`    <Sequence ${s.start?`from={${s.start}} `:''}durationInFrames={${s.duration+(s.id<shots.length-1?24:0)}} name={${JSON.stringify(String(s.id+1).padStart(2,'0')+' · '+s.caption)}} premountFor={fps}><StoryStage shotId={${s.id}}/></Sequence>`).join('\n');
writeFileSync(join(root,'src/Film.tsx'),`import {AbsoluteFill,Sequence,staticFile,useVideoConfig} from 'remotion';\nimport {Audio} from '@remotion/media';\nimport {StoryStage} from './story/StoryStage';\nimport {ContinuityBridge} from './story/ContinuityBridge';\n\n// Authored shot nodes keep each cut independently editable in Studio.\nexport const Film=()=>{\n const {fps}=useVideoConfig();\n return <AbsoluteFill style={{background:'#F7F8FA'}}>\n${sequence}\n    <ContinuityBridge/>\n    <Audio name="Funk Caravan / Supplied soundtrack" src={staticFile('funk-caravan.m4a')} volume={.85} premountFor={fps}/>\n </AbsoluteFill>;\n};\n`);
const registrations=shots.map(s=>`      <Composition id="Shot${String(s.id+1).padStart(2,'0')}" component={StoryStage} defaultProps={{shotId:${s.id}}} durationInFrames={${s.duration}} fps={60} width={1920} height={1080}/>`).join('\n');
writeFileSync(join(root,'src/Root.tsx'),`import {Composition,Folder} from 'remotion';\nimport {Film} from './Film';\nimport {StoryStage} from './story/StoryStage';\n\nexport const RemotionRoot=()=> <>\n  <Composition id="CoopagentsPromo" component={Film} durationInFrames={7762} fps={60} width={1920} height={1080}/>\n  <Folder name="Product-Story">\n${registrations}\n  </Folder>\n</>;\n`);
console.log(`Wrote ${shots.length} independently editable shots; ${shots.at(-1).start+shots.at(-1).duration} frames.`);
