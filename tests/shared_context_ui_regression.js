'use strict';
const assert=require('node:assert/strict');
class E{constructor(t){this.tagName=t.toUpperCase();this.children=[];this.textContent='';this.listeners={};this.value='';}append(...n){this.children.push(...n);}replaceChildren(...n){this.children=n;}setAttribute(){}addEventListener(k,f){this.listeners[k]=f;}contains(){return false;}}
global.document={createElement:t=>new E(t),activeElement:null};
const UI=require('../src/static/shared_context.js');
const all=r=>r.children.flatMap(n=>[n,...all(n)]),text=r=>all(r).map(n=>n.textContent).join(' ');
const root=new E('div');let resolve,opened,current=true;
const data={items:[{id:'contract:1:1',kind:'contract',source:'contract',scope:'project',observed_at:'2026-01-01',freshness:'current',data:{task_id:3,body:'<script>approved</script>',confirmation:'confirmed'}}],total:2,offset:0,next_offset:1,limit:1,truncated:true};
const context={roomId:'one',tasks:[{id:3,title:'API'}],members:[],isCurrent:()=>current,openTask:id=>opened=id,query:()=>new Promise(r=>resolve=r)};
(async()=>{
UI.render(root,data,context);assert.match(text(root),/成员已确认/);
assert.ok(!all(root).some(n=>n.tagName==='SCRIPT'));
all(root).find(n=>n.textContent==='任务 #3').listeners.click();assert.equal(opened,3);
const pending=all(root).find(n=>n.tagName==='FORM').listeners.submit({preventDefault(){}});
current=false;UI.render(root,null,{roomId:'two'});resolve({items:[{id:'late',data:{body:'PRIVATE-LATE'}}]});await pending;
assert.doesNotMatch(text(root),/PRIVATE-LATE|approved/);
console.log('Shared context query, confirmation, references and stale responses passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
