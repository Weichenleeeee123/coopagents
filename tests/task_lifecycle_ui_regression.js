'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
assert.ok(fs.existsSync('src/static/task_lifecycle.js'),'task lifecycle UI module missing');
const Lifecycle=require('../src/static/task_lifecycle.js');
class Element{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.textContent='';this.value='';this.disabled=false;this.open=false;this.dataset={};}
  append(...children){this.children.push(...children);}
  replaceChildren(){this.children=[];}
  querySelectorAll(selector){return descendants(this).filter(node=>selector.split(',').some(tag=>node.tagName===tag.toUpperCase()));}
  focus(){document.activeElement=this;}
  reset(){}
  setAttribute(){}
  addEventListener(type,fn){this.listeners[type]=fn;}
  contains(target){return target===this||this.children.some(child=>child.contains(target));}
}
const descendants=root=>root.children.flatMap(child=>[child,...descendants(child)]);
const content=root=>[root,...descendants(root)].map(node=>node.textContent).join('\n');
global.document={createElement:tag=>new Element(tag),activeElement:null};
// Node 22 exposes webcrypto globally.
(async()=>{
  const task={id:1,state:'claimed',owner_member_id:'me',creator_member_id:'me',revision:2,ownership_epoch:1,execution_session_key:'<img session>'};
  const snapshot={me:{room_id:'room',member_id:'me'},members:[{member_id:'me',display_name:'Me'},{member_id:'next',display_name:'<script>Next</script>'}],lifecycle:{can_manage:false,handoffs:[],history:[]}};
  const root=new Element('div');let calls=[],current=true,done;
  const context={me:snapshot.me,memberName:id=>id,isCurrent:()=>current,api:(path,args)=>{calls.push({path,args});return new Promise(resolve=>{done=resolve;});},sync:async()=>{}};
  Lifecycle.renderDetails(root,task,snapshot,context);
  assert.match(content(root),/<img session>/);
  assert.match(content(root),/释放任务/);assert.match(content(root),/提出转交/);assert.match(content(root),/取消任务/);
  assert.doesNotMatch(content(root),/负责人强制转交/);
  assert.ok(!descendants(root).some(n=>n.tagName==='IMG'||n.tagName==='SCRIPT'));
  const summary=descendants(root).find(n=>n.tagName==='TEXTAREA');summary.value='保留分支和测试结果';summary.listeners.input();
  const select=descendants(root).find(n=>n.tagName==='SELECT');select.value='next';select.listeners.change();
  root.replaceChildren();Lifecycle.renderDetails(root,{...task,revision:3},snapshot,context);
  assert.equal(descendants(root).find(n=>n.tagName==='TEXTAREA').value,'保留分支和测试结果','draft survives poll rerender');
  const handoff=descendants(root).find(n=>n.textContent==='提出转交');const pending=handoff.listeners.click();
  assert.equal(calls[0].args.expected_revision,3);assert.equal(calls[0].args.target_member_id,'next');assert.equal(calls[0].args.summary,'保留分支和测试结果');
  current=false;Lifecycle.clear();done({});await pending;
  const replacement={...snapshot,me:{room_id:'other',member_id:'other'}};root.replaceChildren();Lifecycle.renderDetails(root,{...task,owner_member_id:'other',creator_member_id:'other'},replacement,{...context,me:replacement.me});
  assert.equal(descendants(root).find(n=>n.tagName==='TEXTAREA').value,'','project switch clears drafts');
  const offered={...snapshot,lifecycle:{...snapshot.lifecycle,handoffs:[{id:1,task_id:1,status:'pending',target_member_id:'me',from_member_id:'next',summary:'<img onerror=bad>'}]}};
  root.replaceChildren();Lifecycle.renderDetails(root,{...task,owner_member_id:'next'},offered,context);
  assert.match(content(root),/接受交接/);assert.match(content(root),/拒绝交接/);assert.match(content(root),/<img onerror=bad>/);
  const cancelled={...task,state:'cancelled',owner_member_id:null,cancelled_at:'now',last_owner_member_id:'me'};
  root.replaceChildren();Lifecycle.renderDetails(root,cancelled,snapshot,context);
  assert.match(content(root),/重新打开/);assert.doesNotMatch(content(root),/释放任务/);
  assert.match(content(root),/恢复后可认领/);assert.doesNotMatch(content(root),/当前责任人：待认领/);
  assert.equal(Lifecycle.matches(task,'active'),true);assert.equal(Lifecycle.matches(cancelled,'active'),false);assert.equal(Lifecycle.matches(cancelled,'cancelled'),true);
  current=true;root.replaceChildren();Lifecycle.renderDetails(root,{...task,owner_member_id:'next'},{...snapshot,lifecycle:{...snapshot.lifecycle,handoffs_truncated:true}},context);
  const scoped=descendants(root).find(n=>n.textContent==='查询此任务的当前交接');assert.ok(scoped);
  const query=scoped.listeners.click();done({task:{...task,owner_member_id:'next',revision:4},handoff:offered.lifecycle.handoffs[0]});await query;
  assert.match(content(root),/接受交接/);
  // Exercise the actual app's polling detail render, with nested history and keyboard focus.
  Lifecycle.clear();
  const vm=require('node:vm'), elements=new Map();
  document.getElementById=id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);};
  document.querySelectorAll=()=>[];
  const app=vm.createContext({document,window:{CoopagentsTaskLifecycle:Lifecycle},sessionStorage:{getItem:()=>'',setItem(){},removeItem(){}},setTimeout:()=>1,clearTimeout(){},location:{origin:'http://localhost'},AbortController,Date,JSON});
  vm.runInContext(fs.readFileSync('src/static/app.js','utf8'),app);
  const event=id=>({id,task_id:1,action:'release_task',actor_member_id:'me',from_owner_member_id:'me',ownership_epoch:1,summary:'Event '+id,created_at:'2026-10-11T00:00:00Z',context:{progress:{summary:'Progress '+id}}});
  const fixture={...snapshot,tasks:[task],progress:[],requests:[],contracts:[],lifecycle:{...snapshot.lifecycle,history:[event(30)]}};
  app.fixture=fixture;app.testApi=context.api;
  vm.runInContext('snapshot=fixture;activeTaskId=1;api=testApi;renderTaskDetail()',app);
  const panel=document.getElementById('task-detail');
  const history=()=>descendants(panel).find(n=>n.tagName==='DETAILS');
  const entries=()=>descendants(history()).filter(n=>n.tagName==='DETAILS');
  const control=label=>descendants(panel).find(n=>n.textContent===label);
  const poll=()=>vm.runInContext('snapshot={...snapshot};renderTaskDetail()',app);
  history().open=true;entries()[0].open=true;
  const evidence=control('查看完整交接证据').listeners.click();
  done({context:{progress:{summary:'Complete evidence <script>safe</script>'}}});await evidence;
  let page=control('查看此任务的更多记录').listeners.click();
  done({events:[event(30),event(20)],next_before_id:20});await page;
  entries()[1].open=true;
  const focused=entries()[1].children[0];focused.focus();
  poll();
  assert.equal(history().open,true,'poll must preserve outer history expansion');
  assert.equal(entries().length,2,'poll must retain loaded history pages');
  assert.ok(entries().every(n=>n.open),'poll must preserve each event expansion');
  assert.match(content(panel),/Complete evidence <script>safe<\/script>/,'poll must retain full evidence');
  assert.ok(panel.contains(document.activeElement),'poll must restore focus to mounted summary');
  assert.equal(document.activeElement.tagName,'SUMMARY');
  assert.equal(document.activeElement,entries()[1].children[0],'same-label event focus must use the event ID');
  page=control('查看此任务的更多记录').listeners.click();
  assert.equal(calls.at(-1).args.before_id,20,'poll must preserve pagination cursor');
  poll(); // A pending page may finish after its original DOM has been replaced.
  assert.equal(control('查看此任务的更多记录').disabled,true);
  done({events:[event(10)],next_before_id:null});await page;
  assert.match(content(panel),/Event 10/,'pending page must update the current mounted history');
  assert.equal(control('查看此任务的更多记录').hidden,true);
  poll();assert.equal(entries().length,3);assert.equal(control('查看此任务的更多记录').hidden,true);
  assert.equal(descendants(panel).filter(n=>n.tagName==='PRE').length,1,'cached evidence must not duplicate');
  history().children[0].focus();poll();assert.equal(document.activeElement,history().children[0]);
  for(const change of [{me:{room_id:'room',member_id:'other'}},{tasks:[{...task,id:2}]},{me:{room_id:'other',member_id:'me'}}]){
    app.other={...fixture,...change};
    vm.runInContext('snapshot=other;activeTaskId=other.tasks[0].id;renderTaskDetail()',app);
    assert.equal(history().open,false,'history state must be scoped by member, task and project');
    assert.doesNotMatch(content(panel),/Complete evidence/);
  }
  vm.runInContext('snapshot=fixture;activeTaskId=1;renderTaskDetail()',app);
  assert.equal(history().open,true);assert.equal(entries().length,3);
  // Clear invalidates in-flight responses even if the caller reuses a context.
  const late=entries()[1].querySelectorAll('button')[0].listeners.click();
  Lifecycle.clear();poll();done({context:{private:'Late evidence'}});await late;poll();
  assert.equal(history().open,false);assert.equal(entries().length,1);
  assert.doesNotMatch(content(panel),/Late evidence|Complete evidence/);
  page=control('查看此任务的更多记录').listeners.click();
  Lifecycle.clear();poll();done({events:[event(5)],next_before_id:5});await page;poll();
  assert.equal(entries().length,1,'cleared pages must not leak back into replacement project state');
  console.log('Lifecycle permissions, retained drafts/history/evidence/pagination/focus, and project switching regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
