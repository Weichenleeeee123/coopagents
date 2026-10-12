'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[2]||'src/static/app.js','utf8');
function harness(){
  const elements=new Map(),storage=new Map(),calls=[],copies=[];
  function node(){return {hidden:false,open:false,value:'',textContent:'',children:[],listeners:{},
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
    querySelectorAll(){const out=[];const visit=n=>{for(const child of n.children){if(['input','textarea'].includes(child.tagName))out.push(child);visit(child);}};visit(this);return out;},
    addEventListener(event,fn){this.listeners[event]=fn;},querySelector(){return node();},reset(){},
    showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();}};}
  function el(id){if(!elements.has(id))elements.set(id,node());return elements.get(id);}
  let release,started;
  const pending=new Promise(resolve=>{release=resolve;}),bodyStarted=new Promise(resolve=>{started=resolve;});
  const context=vm.createContext({document:{getElementById:el,createElement:tag=>({...node(),tagName:tag}),querySelectorAll:()=>[],activeElement:null},
    sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    location:{origin:'https://team.example'},navigator:{clipboard:{writeText:async value=>{copies.push(value);}}},
    setTimeout:()=>1,clearTimeout(){},AbortController,Date,JSON,
    fetch:async(path,options)=>{calls.push({path,...options});started();return {status:200,ok:true,json:()=>pending};}});
  vm.runInContext(source,context);
  const run=code=>vm.runInContext(code,context);
  run("token='project-web';snapshot={me:{room_id:'project-one',member_id:'member-one'},members:[]}");
  el('connection-tool').value='codex-desktop';
  const click=id=>el(id).listeners.click({currentTarget:el(id)});
  return {el,run,calls,copies,storage,release,bodyStarted,click};
}
(async()=>{
  const h=harness();h.click('connection-button');assert.equal(h.calls.length,0,'Opening the dialog must not issue credentials');
  await h.click('copy-skill-preview');assert.doesNotMatch(h.copies[0],/private-agent-fixture/);
  const completed=h.click('generate-connection');await h.bodyStarted;
  assert.equal(h.calls[0].path,'/api/agent-connect');assert.equal(h.calls[0].headers.Authorization,'Bearer project-web');assert.deepEqual(JSON.parse(h.calls[0].body),{});
  h.release({room_id:'project-one',member_id:'member-one',agent_token:'private-agent-fixture',expires_at:'2027-01-01T00:00:00Z'});await completed;
  const input=h.el('private-content').querySelectorAll()[0];assert.equal(input.hidden,true);assert.match(input.value,/private-agent-fixture/);
  const buttons=h.el('private-content').children[0].children;
  buttons[1].listeners.click();assert.equal(input.hidden,false);await buttons[2].listeners.click();assert.match(h.copies[1],/private-agent-fixture/);
  assert.match(h.copies[1],/project-one/);assert.match(h.copies[1],/codex-desktop/);
  for(const [key,value]of h.storage)assert.doesNotMatch(key+' '+value,/private-agent-fixture/);
  h.click('close-dialog');assert.equal(input.value,'');assert.equal(h.el('private-content').children.length,0);
  for(const action of ['close','reopen','switch','tool','logout']){
    const x=harness();x.click('connection-button');const done=x.click('generate-connection');await x.bodyStarted;
    if(action==='close')x.click('close-dialog');
    if(action==='reopen'){x.click('close-dialog');x.click('connection-button');}
    if(action==='switch')x.run("generation++;token='other-project';snapshot={me:{room_id:'project-two',member_id:'member-two'}}");
    if(action==='tool'){x.el('connection-tool').value='claude-code';x.el('connection-tool').listeners.change();}
    if(action==='logout')x.run('logout()');
    x.release({room_id:'project-one',member_id:'member-one',agent_token:'private-agent-fixture'});await done;
    assert.equal(x.el('private-content').children.length,0,'Late response restored a credential after '+action);
    assert.doesNotMatch(x.el('dialog-status').textContent,/private-agent-fixture/);
  }
  const mismatch=harness();mismatch.click('connection-button');const rejected=mismatch.click('generate-connection');await mismatch.bodyStarted;
  mismatch.release({room_id:'project-two',member_id:'member-one',agent_token:'private-agent-fixture'});await rejected;
  assert.equal(mismatch.el('private-content').children.length,0);assert.match(mismatch.el('dialog-status').textContent,/身份不匹配/);
  process.stdout.write('Agent connection privacy and delayed-response checks passed\n');
})().catch(()=>{process.stderr.write('Agent connection behavior checks failed\n');process.exitCode=1;});
