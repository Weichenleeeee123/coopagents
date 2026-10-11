'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
assert.ok(fs.existsSync('src/static/task_lifecycle.js'),'task lifecycle UI module missing');
const Lifecycle=require('../src/static/task_lifecycle.js');
class Element{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.textContent='';this.value='';this.disabled=false;}
  append(...children){this.children.push(...children);}
  replaceChildren(){this.children=[];}
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
  console.log('Lifecycle permission, safe DOM, retained drafts, revision payload and project switching regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
