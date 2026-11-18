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
assert.equal(Git.safeReleaseURL('https://github.com/acme/demo/releases/tag/v1.2.3'),'https://github.com/acme/demo/releases/tag/v1.2.3');
assert.equal(Git.safeReleaseURL('https://github.com.evil.test/acme/demo/releases/tag/v1.2.3'),null);
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
  const releaseDetail=new Element('div');
  let submitted;
  const releaseGit={...git,can_manage:true,binding:{repository:'acme/demo'},releases:[{release_id:42,tag_name:'v1.2.3',name:'<img src=x>',state:'published',url:'https://github.com/acme/demo/releases/tag/v1.2.3',assets:[{name:'PRIVATE-ASSET-BODY'}]}]};
  Git.renderDetails(releaseDetail,task,releaseGit,{...context,me:{member_id:'member'},api:async(path,payload)=>{submitted={path,payload};},sync:async()=>{}});
  const releaseText=descendants(releaseDetail).map(n=>n.textContent).join(' ');
  assert.match(releaseText,/v1\.2\.3/);
  assert.doesNotMatch(releaseText,/PRIVATE-ASSET-BODY/);
  assert.ok(!descendants(releaseDetail).some(n=>n.tagName==='IMG'));
  const releaseSelect=descendants(releaseDetail).find(n=>n.name==='release_id');
  assert.ok(releaseSelect);
  const releaseForm=descendants(releaseDetail).find(n=>n.className==='git-link-form');
  releaseSelect.value='42';
  await releaseForm.listeners.submit({preventDefault(){}});
  assert.deepEqual(submitted,{path:'/api/git/github/link',payload:{task_id:1,release_id:42}});
  // Write-path state: branch, conflict block with manager override, merge request.
  const writeDetail=new Element('div');
  let writeCall;
  const writeGit={can_manage:true,binding:{repository:'acme/demo'},
    branches:[{task_id:1,ownership_epoch:1,branch:'coopagents/task-1-1-build-login',base_sha:'a'.repeat(40),created_at:'2026-01-01T00:00:00Z',pushed_at:null}],
    conflict_blocks:[{id:7,task_id:1,ownership_epoch:1,gate:'delivery',paths:['src/shared.py'],conflicts:[{task_id:2,member_id:'m2',paths:['src/shared.py']}]}],
    merge_requests:[{id:9,task_id:1,ownership_epoch:1,pr_number:42,branch:'coopagents/task-1-1-build-login',base_branch:'main',head_sha:'c'.repeat(40),revision:3,created_at:'2026-01-01T00:00:00Z'}]};
  Git.renderDetails(writeDetail,{...task,ownership_epoch:1},writeGit,{...context,me:{member_id:'member'},memberName:()=>'Member',api:async(path,payload)=>{writeCall={path,payload};},sync:async()=>{}});
  const writeText=descendants(writeDetail).map(n=>n.textContent).join(' ');
  assert.match(writeText,/任务分支 coopagents\/task-1-1-build-login · 基准 aaaaaaaaaaaa/);
  assert.match(writeText,/冲突拦截（交付关口）：等待任务 #2/);
  assert.match(writeText,/合并请求：PR #42/);
  const reason=descendants(writeDetail).find(n=>n.name==='reason');
  reason.value='coordinated';
  const overrideForm=descendants(writeDetail).find(n=>n.className==='git-override-form');
  await overrideForm.listeners.submit({preventDefault(){}});
  assert.deepEqual(writeCall,{path:'/api/git/overlap-overrides',payload:{block_id:7,reason:'coordinated'}});
  const mergeButton=descendants(writeDetail).find(n=>n.textContent==='合并 PR #42');
  await mergeButton.listeners.click();
  assert.deepEqual(writeCall,{path:'/api/git/merge',payload:{merge_request_id:9,expected_revision:3,expected_head_sha:'c'.repeat(40),expected_base_branch:'main'}});
  // A non-manager sees the wait state without the mutation controls.
  const plainDetail=new Element('div');
  Git.renderDetails(plainDetail,{...task,ownership_epoch:1},{...writeGit,can_manage:false},{...context,me:{member_id:'other'},memberName:()=>'Member',api:async()=>{},sync:async()=>{}});
  assert.ok(!descendants(plainDetail).some(n=>n.className==='git-override-form'));
  assert.ok(!descendants(plainDetail).some(n=>n.textContent==='合并 PR #42'));
  assert.ok(descendants(plainDetail).some(n=>n.textContent==='等待项目管理者合并。'));
  // The manager-only flag toggle posts the flipped state.
  const panel=new Element('div');
  let toggleCall;
  Git.renderPanel(panel,{me:{room_id:'first'},git:{binding:{repository:'github.com/acme/demo'},can_manage:true,github_configured:true,git_write_enabled:false}},{...context,api:async(path,payload)=>{toggleCall={path,payload};return {};},sync:async()=>{}});
  const toggle=descendants(panel).find(n=>n.textContent==='启用 Git 写入路径');
  assert.ok(toggle);
  await toggle.listeners.click();
  assert.deepEqual(toggleCall,{path:'/api/git/write-enabled',payload:{enabled:true}});
  // Task-named branches without a governed record render as distinct evidence on the owning task only.
  const directDetail=new Element('div');
  Git.renderDetails(directDetail,task,{github_unattributed:[
    {kind:'direct_branch',task_id:1,branch:'coopagents/task-1-1-build',head_sha:'d'.repeat(40),sync_at:'2026-01-01T00:00:00Z',stale:false},
    {kind:'direct_branch',task_id:2,branch:'coopagents/task-2-1-other',head_sha:'e'.repeat(40),sync_at:'2026-01-01T00:00:00Z',stale:false},
    {kind:'unattributed_branch',branch:'wip',head_sha:'f'.repeat(40),sync_at:'2026-01-01T00:00:00Z',stale:false}]},
    {...context,me:{member_id:'other'},memberName:()=>'Member'});
  const directText=descendants(directDetail).map(n=>n.textContent).join(' ');
  assert.match(directText,/发现任务分支 coopagents\/task-1-1-build · 无对应治理记录/);
  assert.doesNotMatch(directText,/未走 adapter/);
  assert.doesNotMatch(directText,/task-2-1-other/);
  assert.doesNotMatch(directText,/wip/);
  assert.ok(descendants(directDetail).some(n=>n.className==='git-evidence git-direct'));
  // Unattributed branches get their own panel section; empty state takes no space.
  const unattributedPanel=new Element('div');
  Git.renderPanel(unattributedPanel,{me:{room_id:'first'},git:{binding:{repository:'github.com/acme/demo'},can_manage:false,github_configured:true,
    github_unattributed:[
      {kind:'unattributed_branch',branch:'wip',head_sha:'f'.repeat(40),sync_at:'2026-01-01T00:00:00Z',stale:false},
      {kind:'default_branch_direct_push',branch:'main',head_sha:'a'.repeat(40),sync_at:'2026-01-01T00:00:00Z',stale:true}],
    github_discovery:{branches:{limit:50,truncated:true}}}},{...context,api:async()=>({}),sync:async()=>{}});
  const panelText=descendants(unattributedPanel).map(n=>n.textContent).join(' ');
  assert.match(panelText,/未归属分支/);
  assert.match(panelText,/wip · HEAD ffffffffffff/);
  assert.match(panelText,/默认分支 main 的 HEAD 暂无对应的治理记录 · HEAD aaaaaaaaaaaa/);
  assert.match(panelText,/同步过期/);
  assert.match(panelText,/分支列表仅展示最近 50 条/);
  const emptyPanel=new Element('div');
  Git.renderPanel(emptyPanel,{me:{room_id:'first'},git:{binding:{repository:'github.com/acme/demo'},can_manage:false,github_configured:true,github_unattributed:[]}},{...context,api:async()=>({}),sync:async()=>{}});
  assert.ok(!descendants(emptyPanel).some(n=>n.textContent.includes('未归属分支')));
  assert.ok(!descendants(emptyPanel).some(n=>n.textContent.includes('暂无对应的治理记录')));
  console.log('Git state, freshness, safe DOM, authorization, project-switch and timeline regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
