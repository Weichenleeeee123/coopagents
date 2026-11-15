import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import {openBrowser,getCompositions,renderMedia} from '@remotion/renderer';

const root=resolve(import.meta.dirname,'..');
assert.ok(process.env.PROMO_BUNDLE,'Set PROMO_BUNDLE to the verified bundle; avoid creating another copy.');
const output=resolve(root,'..','.local','promo-audio-qa',new Date().toISOString().replace(/[:.]/g,'-'));
mkdirSync(output,{recursive:true});
const audio=join(output,'launch-mix.mp3');
const browser=await openBrowser('chrome',{chromeMode:'chrome-for-testing',browserExecutable:process.env.PROMO_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
try {
 const comps=await getCompositions(process.env.PROMO_BUNDLE,{puppeteerInstance:browser});
 const composition=comps.find(c=>c.id==='CoopagentsPromo');
 assert.equal(composition.durationInFrames,2640);
 await renderMedia({serveUrl:process.env.PROMO_BUNDLE,composition,codec:'mp3',audioBitrate:'160k',outputLocation:audio,overwrite:false,puppeteerInstance:browser});
} finally {await browser.close({silent:true});}
const decode=(file)=>{
 const result=spawnSync(process.env.PROMO_FFMPEG||'ffmpeg',['-v','error','-i',file,'-t','44','-ac','1','-ar','8000','-f','f32le','pipe:1'],{maxBuffer:4*1024*1024});
 assert.equal(result.status,0,String(result.stderr));return result.stdout;
};
const source=decode(join(root,'public','funk-caravan.m4a')),mix=decode(audio);
assert.ok(Math.abs(mix.length/4/8000-44)<.08,'actual exported mix is 44 seconds');
const rms=(buffer,a,b)=>{let energy=0;const start=Math.floor(a*8000),end=Math.min(buffer.length/4,Math.floor(b*8000));for(let i=start;i<end;i++)energy+=buffer.readFloatLE(i*4)**2;return Math.sqrt(energy/(end-start));};
const checks=[[39,40],[41.5,42],[42.5,43],[43.6,43.9]].map(([start,end])=>({start,end,gain:rms(mix,start,end)/rms(source,start,end)}));
assert.ok(checks[0].gain>.7&&checks[0].gain<.95,'music remains audible before fade');
for(let i=1;i<checks.length;i++)assert.ok(checks[i].gain<checks[i-1].gain,'fade gain descends');
assert.ok(checks.at(-1).gain<.17,'last audible window fades toward silence');
writeFileSync(join(output,'audio.json'),JSON.stringify({duration:44,checks,audio},null,2));
console.log(JSON.stringify({duration:44,checks,audio}));
