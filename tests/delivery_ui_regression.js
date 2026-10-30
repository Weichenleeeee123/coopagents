 'use strict';
const assert=require('node:assert/strict');
class E{constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.textContent='';this.listeners={};this.value='';}append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}setAttribute(){}addEventListener(k,f){this.listeners[k]=f;}}
global.document={createElement:t=>new E(t)};
const Delivery=require('../src/static/delivery.js');
const root=new E('div'),all=root=>root.children.flatMap(n=>[n,...all(n)]);let opened,resolve,calls=[];let current=true;
const graph={items:[{object_key:'pr:7',kind:'pr',value:7,task_ids:[1,2],associations:[
{task_id:1,relationship_source:'explicit',state:'closed_unmerged',linked_by:'m',linked_at:'2026-01-01',stale:false,unavailable:false},
{task_id:2,relationship_source:'suggested',status:'pending',state:'pending_confirmation',suggestion_id:4,linked_by:'<script>actor</script>',linked_at:'2026-01-01',evidence:'<img src=x>',stale:true,unavailable:false}]}]};
const context={openTask:id=>opened=id,canManage:true,memberName:id=>id,isCurrent:()=>current,api:(path,body)=>{calls.push({path,body});return new Promise(r=>resolve=r);},sync:async()=>{}};
(async()=>{
Delivery.render(root,graph,context);let text=all(root).map(n=>n.textContent).join(' ');
assert.match(text,/明确关联/);assert.match(text,/待确认建议/);assert.match(text,/证据已过期/);assert.match(text,/closed_unmerged/);
assert.ok(!all(root).some(n=>['IMG','SCRIPT'].includes(n.tagName)));
all(root).find(n=>n.textContent==='任务 #1').listeners.click();assert.equal(opened,1);
const pending=all(root).find(n=>n.textContent==='确认关联').listeners.click();assert.equal(calls[0].body.suggestion_id,4);
current=false;Delivery.render(root,null,context);resolve({});await pending;
assert.equal(root.children.length,0);
console.log('Delivery reverse task links, confirmation, freshness and stale response regressions passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
