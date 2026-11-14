import assert from 'node:assert/strict';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import {openBrowser,getCompositions,renderStill} from '@remotion/renderer';
const root=resolve(import.meta.dirname,'..');
assert.ok(process.env.PROMO_BUNDLE,'Set PROMO_BUNDLE to the current verified bundle.');
const beats=JSON.parse(readFileSync(join(root,'src/ad/launch-beats.json'),'utf8'));
assert.equal(beats.length,20);
beats.forEach((b,i)=>{assert.equal(b.time,i?beats[i-1].end:0);assert.ok(b.end>b.time);});
assert.equal(beats.at(-1).end,44);
const output=resolve(root,'..','.local','promo-beat-review',new Date().toISOString().replace(/[:.]/g,'-'));
mkdirSync(output,{recursive:true});
const browser=await openBrowser('chrome',{chromeMode:'chrome-for-testing',browserExecutable:process.env.PROMO_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const errors=[];
try {
 const compositions=await getCompositions(process.env.PROMO_BUNDLE,{puppeteerInstance:browser});
 const composition=compositions.find(c=>c.id==='CoopagentsPromo');
 for(let i=0;i<beats.length;i++){
  const frame=Math.round((beats[i].time+Math.min(.7,(beats[i].end-beats[i].time)/2))*60);
  await renderStill({serveUrl:process.env.PROMO_BUNDLE,composition,frame,output:join(output,`beat-${String(i).padStart(2,'0')}.png`),scale:.5,puppeteerInstance:browser,onBrowserLog:log=>{if(log.type==='error')errors.push(log.text);}});
 }
 assert.deepEqual(errors,[]);
}finally{await browser.close({silent:true});}
const result=spawnSync(process.env.PROMO_FFMPEG||'ffmpeg',['-v','error','-n','-framerate','1','-i',join(output,'beat-%02d.png'),'-vf','scale=384:216,tile=5x4:padding=8:margin=8:color=0xECEFF3','-frames:v','1',join(output,'contact-sheet.png')],{encoding:'utf8'});
assert.equal(result.status,0,result.stderr);
writeFileSync(join(output,'review.json'),JSON.stringify({visualBeats:beats,errors,output},null,2));
console.log(output);
