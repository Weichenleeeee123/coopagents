'use strict';
const assert=require('node:assert/strict');
const UI=require('../src/static/dependencies.js');
class Element{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.textContent='';this.value='';this.disabled=false;this.open=false;this.dataset={};}
  append(...children){this.children.push(...children);}
  replaceChildren(){this.children=[];}
  setAttribute(){}
  addEventListener(name,fn){this.listeners[name]=fn;}
  contains(target){return target===this||this.children.some(c=>c.contains(target));}
  focus(){document.activeElement=this;}
}
const descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
const content=n=>[n,...descendants(n)].map(x=>x.textContent).join('\n');
global.document={createElement:tag=>new Element(tag),activeElement:null};
(async()=>{
  const root=new Element('div'),task={id:1,title:'Frontend',owner_member_id:'a',creator_member_id:'a',revision:3},target={id:2,title:'Backend',owner_member_id:'b',scope:'src/api'};
  let dep={id:1,source_task_id:1,target_task_id:2,source:task,target,need:'<img> schema',context:'<script> data',status:'active',routing_state:'routed',revision:2,creator_member_id:'a',latest_reply:{id:4,body:'Fields',actor_kind:'agent'}};
  let snapshot={me:{room_id:'room',member_id:'a'},tasks:[task,target],dependencies:[dep],requests:[],contracts:[],lifecycle:{can_manage:false,handoffs:[]}};
  let current=true,done,calls=[],syncs=0;
  const context={memberName:id=>id,isCurrent:()=>current,sync:async()=>{syncs++;},api:(path,body)=>{calls.push({path,body});return new Promise(resolve=>{done=resolve;});}};
  const render=()=>{root.replaceChildren();UI.renderDetails(root,task,snapshot,context);};
  const control=label=>descendants(root).find(n=>n.tagName==='BUTTON'&&n.textContent===label);
  render();assert.match(content(root),/我在等谁/);assert.match(content(root),/<img> schema/);
  assert.equal(descendants(root).filter(n=>['SCRIPT','IMG'].includes(n.tagName)).length,0);
  assert.equal(control('确认依赖已满足').disabled,true);
  const read=control('查看最新回复与记录').listeners.click();done({...dep,read_recorded:true,history:[{action:'created',summary:'Start',created_at:'now'}]});await read;
  assert.equal(control('确认依赖已满足').disabled,false);
  const summary=descendants(root).find(n=>n.tagName==='TEXTAREA');summary.value='Fits frontend';summary.listeners.input();
  const history=descendants(root).find(n=>n.tagName==='DETAILS');history.open=true;
  render();assert.equal(descendants(root).find(n=>n.tagName==='TEXTAREA').value,'Fits frontend');assert.equal(descendants(root).find(n=>n.tagName==='DETAILS').open,true);
  assert.match(content(root),/created · Start/);
  dep={...dep,revision:3,latest_reply:{id:5,body:'Changed',actor_kind:'web'}};snapshot.dependencies=[dep];render();
  assert.equal(control('确认依赖已满足').disabled,true,'later reply invalidates prior read');
  let action=control('查看最新回复与记录').listeners.click();done({...dep,read_recorded:true,history:[]});await action;
  action=control('确认依赖已满足').listeners.click();assert.equal(calls.at(-1).body.reply_id,5);assert.equal(calls.at(-1).body.expected_revision,3);assert.equal(calls.at(-1).body.summary,'Fits frontend');done({...dep,status:'satisfied'});await action;assert.equal(syncs,1);
  // Scope lookup displays all candidates and never silently chooses the first.
  const inputs=descendants(root).filter(n=>n.tagName==='INPUT');inputs[0].value='src/api';inputs[0].listeners.input();
  action=control('查找负责人').listeners.click();assert.equal(descendants(root).find(n=>n.tagName==='SELECT').disabled,true);done({status:'ambiguous',candidates:[target,{id:3,title:'Nested',scope:'src/api/auth',owner_member_id:null,evidence:'Slash-segment prefix overlap'}]});await action;
  assert.match(content(root),/多个任务范围匹配/);assert.equal(descendants(root).find(n=>n.tagName==='SELECT').value,'');
  const select=descendants(root).find(n=>n.tagName==='SELECT');select.value='2';select.listeners.change();inputs[1].value='Need full response';inputs[1].listeners.input();
  action=control('建立任务依赖').listeners.click();assert.equal(calls.at(-1).body.target_task_id,2);assert.equal(calls.at(-1).body.expected_revision,3);
  current=false;UI.clear();done({...dep,id:2});await action;assert.equal(syncs,1,'cross-project async response cannot trigger sync');
  current=true;snapshot={...snapshot,me:{room_id:'other',member_id:'a'}};render();assert.equal(descendants(root).filter(n=>n.tagName==='INPUT')[1].value,'');assert.equal(control('确认依赖已满足').disabled,true);
  assert.equal(UI.blocked(task,snapshot),true);assert.equal(UI.blocked({...task,cancelled_at:'now'},snapshot),false);
  snapshot.dependencies=[{...dep,status:'satisfied'}];assert.equal(UI.blocked(task,snapshot),false);
  snapshot.dependencies=[{...dep,routing_state:'unassigned',target:{...target,owner_member_id:null},latest_reply:null}];
  snapshot.requests=[{id:100,dependency_id:1,dependency_route_state:'historical',receiver_member_id:'a',body:'Old'},{id:101,receiver_member_id:'a',body:'Ordinary'}];
  snapshot.lifecycle.handoffs=[{task_id:7,target_member_id:'a',summary:'Handoff'}];snapshot.contracts=[{id:9,current_version:1,versions:[{version:1,title:'Contract'}]}];
  const pending=UI.pending(snapshot);assert.equal(pending.length,4);assert.ok(!pending.some(p=>p.id===100));
  // Read state is keyed by identity + task and clear invalidates responses.
  snapshot.dependencies=[dep];render();action=control('查看最新回复与记录').listeners.click();UI.clear();render();done({...dep,read_recorded:true,history:[{summary:'Old private response'}]});await action;
  assert.equal(control('确认依赖已满足').disabled,true);assert.doesNotMatch(content(root),/Old private response/);
  // Recipient gets a human reply entry, unrelated members get no mutation controls.
  snapshot.me={room_id:'room',member_id:'b'};render();assert.ok(control('发送答复'));assert.equal(control('确认依赖已满足'),undefined);
  snapshot.me={room_id:'room',member_id:'c'};render();assert.equal(control('发送答复'),undefined);assert.equal(control('撤销依赖'),undefined);
  // An unclaimed source's creator retains cancellation permission even when
  // another manager created the dependency; dependency creation is not ownership.
  snapshot.dependencies=[{...dep,source:{...task,owner_member_id:null,creator_member_id:'c'},creator_member_id:'a'}];
  render();assert.ok(control('撤销依赖'));assert.equal(control('确认依赖已满足'),undefined);
  snapshot.me={room_id:'room',member_id:'a'};render();assert.equal(control('撤销依赖'),undefined);
  console.log('Dependency UI: explicit read/confirm, stale replies, drafts/history, scope ambiguity, safe DOM and project isolation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
