import assert from 'node:assert/strict';
import {mkdirSync, readFileSync, readdirSync, writeFileSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {bundle} from '@remotion/bundler';
import {openBrowser, getCompositions, renderStill} from '@remotion/renderer';

const root=resolve(import.meta.dirname,'..');
const shotPlan=JSON.parse(readFileSync(join(root,'src/story/shots.json'),'utf8'));
assert.equal(shotPlan.length,31);
assert.deepEqual(shotPlan.slice(0,4).map(s=>s.kind),['pain','pain','pain','pain'],'Lead with the human relay problem');
assert.ok(shotPlan.some(s=>s.kind==='reach'&&s.stage==='devices'));
assert.ok(shotPlan.some(s=>s.kind==='reach'&&s.stage==='regions'));
assert.ok(shotPlan.some(s=>s.kind==='relief'),'Return the human to decisions at the end');
for(let i=0;i<shotPlan.length;i++){
 assert.equal(shotPlan[i].id,i);
 assert.equal(shotPlan[i].start,i?shotPlan[i-1].start+shotPlan[i-1].duration:0,'Shots must be contiguous');
 assert.ok(shotPlan[i].duration<=360,'No extended idle shot');
}
const activeSources=['src/Film.tsx','src/Root.tsx',...readdirSync(join(root,'src/story')).filter(name=>/\.(tsx?|json)$/.test(name)).map(name=>'src/story/'+name)];
for(const file of activeSources)assert.ok(!/[\u3400-\u9fff]/u.test(readFileSync(join(root,file),'utf8')),`${file} must use English throughout the active film`);
const actualTools=readFileSync(resolve(root,'..','src','mcp_service.py'),'utf8');
for(const tool of new Set(shotPlan.map(s=>s.tool).filter(Boolean)))assert.ok(actualTools.includes(`'${tool}'`),`Unknown product tool shown in the film: ${tool}`);
assert.ok(shotPlan.filter(s=>!['brand','closing'].includes(s.kind)).length>=27,'Most shots must depict concrete product use');
const stamp=new Date().toISOString().replace(/[:.]/g,'-');
const output=resolve(root,'..','.local','promo-video-qa',stamp);
mkdirSync(output,{recursive:true});
const music=join(root,'public','funk-caravan.m4a');
const ffprobe=join(root,'node_modules','@remotion','compositor-win32-x64-msvc','ffprobe.exe');
const probe=spawnSync(ffprobe,['-v','error','-select_streams','a:0','-show_entries','format=duration','-of','json',music],{encoding:'utf8'});
assert.equal(probe.status,0,`The provided Funk Caravan track must decode: ${probe.stderr}`);
const musicDuration=Number(JSON.parse(probe.stdout).format.duration);
assert.ok(Math.abs(musicDuration-129.357937)<0.02,`Use the supplied soundtrack at its 2:09 length; got ${musicDuration}s`);

const serveUrl=await bundle({entryPoint:join(root,'src','index.ts'),outDir:join(output,'bundle'),rspack:true});
const browser=await openBrowser('chrome',{chromeMode:'chrome-for-testing',browserExecutable:process.env.PROMO_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const logs=[];
try{
 const compositions=await getCompositions(serveUrl,{puppeteerInstance:browser});
 const main=compositions.find(c=>c.id==='CoopagentsPromo');
 assert.ok(main,'Main composition is registered');
 assert.equal(main.durationInFrames,7762);assert.equal(main.fps,60);assert.equal(main.width,1920);assert.equal(main.height,1080);
 assert.ok(Math.abs(main.durationInFrames/main.fps-musicDuration)<1/main.fps,'The video must match the track within one video frame');
 const scenes=compositions.filter(c=>c.id!=='CoopagentsPromo');
 assert.equal(scenes.length,31,'The revised film needs 31 short product-story shots');
 assert.equal(scenes.reduce((sum,c)=>sum+c.durationInFrames,0),main.durationInFrames);
 assert.ok(scenes.every(c=>c.durationInFrames/c.fps<=6),'No shot may idle beyond six seconds');
 for(const shot of shotPlan){const registered=scenes.find(c=>c.id===`Shot${String(shot.id+1).padStart(2,'0')}`);assert.ok(registered);assert.equal(registered.durationInFrames,shot.duration);assert.equal(registered.defaultProps.shotId,shot.id);}
 const samples=shotPlan.map(s=>[`shot-${String(s.id+1).padStart(2,'0')}-${s.stage}`,s.start+80]);
 const motionChecks=[];const visualFailures=[];
 for(const [name,frame] of samples){
  const first=join(output,`${name}.png`);const second=join(output,`${name}-motion.png`);
  for(const [at,file] of [[frame,first],[frame+60,second]])await renderStill({serveUrl,composition:main,frame:at,puppeteerInstance:browser,output:file,scale:.5,onBrowserLog:log=>{if(log.type==='error')logs.push(log.text);}});
  const decode=file=>{const result=spawnSync(process.env.PROMO_FFMPEG || 'ffmpeg',['-v','error','-i',file,'-vf','scale=240:135','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],{maxBuffer:1024*1024});assert.equal(result.status,0,String(result.stderr));return result.stdout;};
  const a=decode(first),b=decode(second);let changed=0;
  for(let i=0;i<a.length;i+=3)if(Math.abs(a[i]-b[i])+Math.abs(a[i+1]-b[i+1])+Math.abs(a[i+2]-b[i+2])>36)changed++;
  const fraction=changed/(a.length/3);if(fraction<=.006)visualFailures.push(`${name}: insufficient movement (${(fraction*100).toFixed(2)}%)`);
  let border=0,bright=0;for(let y=0;y<135;y++)for(let x=0;x<240;x++){if(x<14||x>225||y<8||y>126){border++;const j=(y*240+x)*3;if((a[j]+a[j+1]+a[j+2])/3>215)bright++;}}
  const brightness=bright/border;if(brightness<.80)visualFailures.push(`${name}: light stage not preserved (${(brightness*100).toFixed(1)}% bright border)`);
  motionChecks.push({name,changedPixelsPercent:Number((fraction*100).toFixed(2)),lightBorderPercent:Number((brightness*100).toFixed(1))});console.log(`${fraction>.006&&brightness>=.80?'PASS':'CHECK'} ${name} / frame ${frame}; motion ${(fraction*100).toFixed(1)}%; light border ${(brightness*100).toFixed(0)}%`);
 }
 assert.equal(logs.length,0,`Browser errors: ${JSON.stringify(logs)}`);
 const report={duration:main.durationInFrames/main.fps,fps:main.fps,width:1920,height:1080,language:'English',shotCount:31,averageShotSeconds:main.durationInFrames/main.fps/31,toolsChecked:[...new Set(shotPlan.map(s=>s.tool).filter(Boolean))],scenes:scenes.map(c=>({id:c.id,frames:c.durationInFrames})),sampledFrames:samples,motionChecks,music:{file:'funk-caravan.m4a',duration:musicDuration},browserErrors:logs,output};
 writeFileSync(join(output,'verification.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 assert.deepEqual(visualFailures,[],visualFailures.join('\n'));
}finally{await browser.close({silent:true});}
