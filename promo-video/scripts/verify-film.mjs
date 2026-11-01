import assert from 'node:assert/strict';
import {mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {bundle} from '@remotion/bundler';
import {openBrowser, getCompositions, renderStill} from '@remotion/renderer';

const root=resolve(import.meta.dirname,'..');
const stamp=new Date().toISOString().replace(/[:.]/g,'-');
const output=resolve(root,'..','.local','promo-video-qa',stamp);
mkdirSync(output,{recursive:true});
const wav=readFileSync(join(root,'public','coopagents-original-score.wav'));
assert.equal(wav.toString('ascii',0,4),'RIFF');
assert.equal(wav.readUInt16LE(22),2,'Soundtrack must be stereo');
assert.equal(wav.readUInt32LE(40)/wav.readUInt32LE(28),180,'Soundtrack must cover 180 seconds');
let peak=0; let energy=0;
for(let offset=44;offset<wav.length;offset+=2){const value=wav.readInt16LE(offset)/32768;peak=Math.max(peak,Math.abs(value));energy+=value*value;}
assert.ok(peak>0.05 && peak<.99,'Music must contain signal and avoid clipping');
for(let second=1;second<179;second++){
 let sum=0;const start=44+second*wav.readUInt32LE(28);
 for(let i=0;i<4000;i+=4)sum+=Math.abs(wav.readInt16LE(start+i));
 assert.ok(sum>1000,`Unexpected silence at ${second}s`);
}

const serveUrl=await bundle({entryPoint:join(root,'src','index.ts'),outDir:join(output,'bundle'),rspack:true});
const browser=await openBrowser('chrome',{chromeMode:'chrome-for-testing',browserExecutable:process.env.PROMO_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const logs=[];
try{
 const compositions=await getCompositions(serveUrl,{puppeteerInstance:browser});
 const main=compositions.find(c=>c.id==='CoopagentsPromo');
 assert.ok(main,'Main composition is registered');
 assert.equal(main.durationInFrames,5400);assert.equal(main.fps,30);assert.equal(main.width,1920);assert.equal(main.height,1080);
 const scenes=compositions.filter(c=>c.id!=='CoopagentsPromo');
 assert.equal(scenes.length,10);assert.equal(scenes.reduce((sum,c)=>sum+c.durationInFrames,0),main.durationInFrames);
 const samples=[['opening',240],['friction',800],['connection',1440],['context',2070],['dialogue',2640],['tasks',3240],['evidence',3840],['modes',4350],['control',4800],['closing',5280]];
 for(const [name,frame] of samples){
  await renderStill({serveUrl,composition:main,frame,puppeteerInstance:browser,output:join(output,`${name}.png`),scale:.5,onBrowserLog:log=>{if(log.type==='error')logs.push(log.text);}});
  console.log(`PASS ${name} / frame ${frame}`);
 }
 assert.equal(logs.length,0,`Browser errors: ${JSON.stringify(logs)}`);
 const report={duration:180,fps:30,width:1920,height:1080,scenes:scenes.map(c=>({id:c.id,frames:c.durationInFrames})),sampledFrames:samples,music:{channels:2,duration:180,peakDbfs:20*Math.log10(peak),rmsDbfs:20*Math.log10(Math.sqrt(energy/((wav.length-44)/2)))},browserErrors:logs,output};
 writeFileSync(join(output,'verification.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close({silent:true});}
