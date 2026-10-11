'use strict';
const assert=require('node:assert/strict');
const Git=require('../src/static/git.js');
const task={id:1,owner_member_id:'member'};
const report={state:'working'};
const delivery={task_id:1,state:'merged',source:'github_verified',stale:false,head:'a'.repeat(40)};
const git={connection:{active:true},deliveries:[delivery]};
assert.equal(Git.state(task,report,git),'merged');
assert.equal(Git.state(task,{state:'blocked'},git),'blocked');
assert.equal(Git.state(task,report,{...git,deliveries:[{...delivery,stale:true}]}),'working');
assert.equal(Git.state(task,report,{...git,connection:{active:false}}),'working');
assert.equal(Git.state(task,report,{...git,deliveries:[{...delivery,task_id:2}]}),'working');
assert.equal(Git.state(task,report,{...git,deliveries:[{...delivery,state:'closed'}]}),'working');
assert.equal(Git.state(task,{state:'pr_open'},undefined),'pr_open');
assert.equal(Git.safeURL('javascript:alert(1)'),null);
assert.equal(Git.safeURL('https://github.com.evil.test/a/b/pull/1'),null);
assert.equal(Git.safeURL('https://user:secret@github.com/a/b/pull/1'),null);
assert.equal(Git.safeURL('https://github.com/a/b/pull/1'),'https://github.com/a/b/pull/1');
assert.equal(Git.caption({source:'local_git'}),'本地 Git 观测');
assert.equal(Git.caption({source:'agent_report'}),'agent 自述');
assert.equal(Git.state(task,report,{...git,deliveries:[delivery,{...delivery,state:'pushed',commit_sha:'a'.repeat(40)}]}),'merged');
assert.equal(Git.checks({...delivery,head_sha:'b'.repeat(40),checks:[{head_sha:'a'.repeat(40),status:'completed',conclusion:'success'}]}),'检查未知');
assert.equal(Git.checks({...delivery,head_sha:'a'.repeat(40),checks:[{head_sha:'a'.repeat(40),status:'completed',conclusion:'failure'}]}),'检查未通过');
assert.match(Git.summarize(1,{...git,deliveries:[{...delivery,pr_number:4,stale:true}]}),/PR #4.*同步过期/);
assert.equal(Git.checks({checks:[{status:'completed',conclusion:'success'}]}),'检查未知');
class Element {
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.textContent='';}
  append(child){child.parent=this;this.children.push(child);}
  replaceChildren(){this.children=[];}
  contains(target){return target===this||this.children.some(c=>c.contains(target));}
  addEventListener(type,fn){this.listeners[type]=fn;}
  setAttribute(){}
  querySelector(selector){return this.children.find(c=>c.className===selector.slice(1))||this.children.map(c=>c.querySelector(selector)).find(Boolean);}
  remove(){this.parent.children=this.parent.children.filter(c=>c!==this);}
}
function descendants(root){return root.children.flatMap(child=>[child,...descendants(child)]);}
global.document={createElement:tag=>new Element(tag),activeElement:null};
(async()=>{
  Git.clear();
  let current=true;
  const root=new Element('div'),snapshot={me:{room_id:'first'},git:{binding:{repository:'github.com/acme/demo'},can_manage:true,github_configured:true}};
  const context={isCurrent:()=>current,origin:'https://example.test',sync:async()=>{},api:async()=>({state:'one',authorization_url:'https://github.com/login/oauth/authorize?state=one'})};
  Git.renderPanel(root,snapshot,context);
  await descendants(root).find(n=>n.textContent==='授权仓库访问 ↗').listeners.click();
  Git.renderPanel(root,snapshot,context);
  assert.ok(descendants(root).some(n=>n.textContent==='我已授权，完成连接'));
  // An authorization continuation must not reappear in a replacement project.
  let resolve;
  context.api=()=>new Promise(done=>{resolve=done;});
  const pending=descendants(root).find(n=>n.textContent==='授权仓库访问 ↗').listeners.click();
  current=false;Git.clear();
  const second={...snapshot,me:{room_id:'second'}};
  Git.renderPanel(root,second,context);
  resolve({state:'old',authorization_url:'https://github.com/login/oauth/authorize?state=old'});await pending;
  assert.ok(!descendants(root).some(n=>n.textContent==='我已授权，完成连接'));
  // Payload text remains text, and delayed checkpoints render in capture order.
  const detail=new Element('div');
  Git.renderDetails(detail,task,{workspaces:[{task_id:1,branch:'<img src=x onerror=alert(1)>',head:'a'.repeat(40),paths:['src/a'],member_id:'m'}],events:[{id:1,task_id:1,captured_at:'2026-01-02T00:00:00Z',branch:'newer',head:'a'},{id:2,task_id:1,captured_at:'2026-01-01T00:00:00Z',branch:'older',head:'b'}]}, {...context,me:{member_id:'other'},memberName:()=>'<script>unsafe</script>'});
  assert.ok(descendants(detail).some(n=>n.textContent.includes('<img src=x')));
  assert.ok(!descendants(detail).some(n=>n.tagName==='IMG'||n.tagName==='SCRIPT'));
  const timeline=descendants(detail).find(n=>n.tagName==='DETAILS');
  assert.match(timeline.children[1].textContent,/newer/);
  console.log('Git state, freshness, safe DOM, authorization, project-switch and timeline regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
