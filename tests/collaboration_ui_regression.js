'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
assert.ok(fs.existsSync('src/static/collaboration.js'),'collaboration UI module missing');
const Collaboration=require('../src/static/collaboration.js');
class Element{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.textContent='';this.value='';}
  append(...children){this.children.push(...children);}
  replaceChildren(){this.children=[];}
  setAttribute(){}
  addEventListener(type,fn){this.listeners[type]=fn;}
  contains(target){return target===this||this.children.some(child=>child.contains(target));}
}
const descendants=root=>root.children.flatMap(child=>[child,...descendants(child)]);
const content=root=>[root,...descendants(root)].map(node=>node.textContent).join('\n');
global.document={createElement:tag=>new Element(tag),activeElement:null};
(async()=>{
  const root=new Element('div'),setup=new Element('div');
  const snapshot={me:{room_id:'room-a',member_id:'me'},server_time:'2026-10-11T01:00:00Z',collaboration:{checkpoints:[],diagnostics:[]}};
  let current=true,resolve;
  const context={origin:'http://127.0.0.1:8787',memberName:()=>'<script>member</script>',isCurrent:()=>current,sync:()=>new Promise(done=>{resolve=done;})};
  Collaboration.renderPanel(root,snapshot,context);
  assert.match(content(root),/网页连接/);
  assert.match(content(root),/尚无真实诊断/);
  assert.match(content(root),/尚未收到.*hook/);
  assert.doesNotMatch(content(root),/诊断已完成/);
  Collaboration.renderSetup(setup,snapshot,context);
  assert.match(content(setup),/CREWMESH_PROJECT_ID/);
  assert.match(content(setup),/python -I -m crewmesh\.checkpoint_hook --tool codex-cli --config-preview/);
  assert.match(content(setup),/python -I -m crewmesh\.checkpoint_hook --tool codex-cli --doctor/);
  assert.match(content(setup),/--config-preview/);
  assert.match(content(setup),/--doctor/);
  assert.match(content(setup),/\/hooks/);
  const completed={...snapshot,collaboration:{diagnostics:[{status:'completed',completed_at:snapshot.server_time}],checkpoints:[]}};
  Collaboration.renderPanel(root,completed,context);
  assert.match(content(root),/诊断已完成/);
  assert.match(content(root),/尚未收到.*hook/);
  const observed={...completed,collaboration:{...completed.collaboration,checkpoints:[{member_id:'me',session_key:'<img src=x>',tool:'codex-cli',source:'hook',event:'SessionStart',updated_at:snapshot.server_time,last_hook_at:snapshot.server_time,stale:true,hook_stale:true}]}};
  Collaboration.renderPanel(root,observed,context);
  assert.match(content(root),/入口报告的 hook/);
  assert.match(content(root),/已过期/);
  assert.match(content(root),/<img src=x>/);
  assert.ok(!descendants(root).some(node=>node.tagName==='IMG'||node.tagName==='SCRIPT'));
  const currentHook={...observed.collaboration.checkpoints[0],session_key:'latest-hook',last_hook_at:'2026-10-11T02:00:00Z',hook_stale:false,stale:false};
  Collaboration.renderPanel(root,{...observed,collaboration:{...observed.collaboration,checkpoints:[...observed.collaboration.checkpoints,currentHook]}},context);
  assert.ok(descendants(root).some(node=>node.textContent.startsWith('收到入口报告的 hook 检查点 · 最近 5 分钟内收到')));
  const picker=descendants(setup).find(node=>node.tagName==='SELECT');picker.value='claude-code';picker.listeners.change();
  Collaboration.renderSetup(setup,snapshot,context);
  assert.equal(descendants(setup).find(node=>node.tagName==='SELECT').value,'claude-code');
  const expanded=descendants(root).find(node=>node.tagName==='DETAILS');expanded.open=true;expanded.listeners.toggle?.();
  Collaboration.renderPanel(root,observed,context);
  assert.equal(descendants(root).find(node=>node.tagName==='DETAILS').open,true,'setup expansion survives a fresh snapshot');
  const refresh=descendants(root).find(node=>node.textContent==='刷新接入结果');
  const pending=refresh.listeners.click();
  current=false;Collaboration.clear();
  assert.equal(content(root),'');assert.equal(content(setup),'');
  const replacement={...snapshot,me:{room_id:'room-b',member_id:'other'}};
  Collaboration.renderPanel(root,replacement,context);
  resolve();await pending;
  assert.doesNotMatch(content(root),/room-a|<img src=x>|诊断已完成/);
  assert.match(content(root),/尚无真实诊断/);
  const app=fs.readFileSync('src/static/app.js','utf8');
  assert.match(app,/collaborationUI\(\)\?\.clear\(\)/);
  assert.match(app,/collaborationUI\(\)\?\.renderPanel/);
  assert.match(app,/collaborationUI\(\)\?\.renderSetup/);
  console.log('Collaboration onboarding, genuine diagnostics, hook evidence, freshness, safe DOM and project reset regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
