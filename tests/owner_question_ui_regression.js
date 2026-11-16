'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.textContent='';this.listeners={};this.attributes={};this.dataset={};this.value='';this.hidden=false;this.open=false;}
  append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  addEventListener(name,handler){this.listeners[name]=handler;}setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}
  querySelectorAll(){return [];}querySelector(){return null;}get firstChild(){return this.children[0];}close(){}reset(){}
}
const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const document={getElementById:element,querySelectorAll:()=>[],createElement:tag=>new Element(tag),activeElement:null};
const context=vm.createContext({document,window:{addEventListener(){}},sessionStorage:{getItem:()=>'',setItem(){},removeItem(){}},location:{hash:'',origin:'http://localhost'},history:{pushState(){},replaceState(){}},setTimeout:()=>1,clearTimeout(){},AbortController,Date,JSON});
vm.runInContext(fs.readFileSync('src/static/app.js','utf8'),context);
const run=source=>vm.runInContext(source,context),walk=root=>[root,...root.children.flatMap(walk)],content=root=>walk(root).map(n=>n.textContent).join(' ');
run(`snapshot={me:{member_id:'front'},members:[],tasks:[],requests:[],contracts:[],events:[]};`);
for(const state of ['historical','closed']){
  assert.equal(run(`requestIsActive({owner_route_state:'${state}'})`),false);
  const record=run(`requestRecord({id:1,body:'Retained question',context_version:1,sender_member_id:'front',receiver_member_id:'old',owner_target_task_id:7,owner_route_state:'${state}',replies:[{body:'Retained answer'}]})`);
  assert.match(content(record),state==='historical'?/历史路由/:/已关闭路由/);
  assert.equal(walk(record).some(n=>n.textContent==='确认请求已解决'),false);
}
assert.equal(run(`requestIsActive({owner_route_state:'current'})`),true);
assert.equal(run(`requestIsActive({})`),true,'ordinary explicitly addressed questions retain existing behavior');
assert.equal(run(`requestIsActive({dependency_id:1,dependency_route_state:'historical'})`),false);
assert.equal(run(`requestIsActive({owner_route_state:'current',resolved_at:'now'})`),false);
const current=run(`requestRecord({id:2,body:'Current question',context_version:2,sender_member_id:'front',receiver_member_id:'new',owner_target_task_id:7,owner_route_state:'current',replies:[{body:'Current answer'}]})`);
assert(walk(current).some(n=>n.textContent==='确认请求已解决'));
run(`snapshot.requests=[{id:1,body:'Old',owner_route_state:'historical',replies:[]},{id:2,body:'Current',owner_route_state:'current',replies:[]}];`);
element('request-filter').value='pending';run('renderRequests()');
assert.equal(element('requests').children.length,1,'pending filter excludes historical owner routes');
element('request-filter').value='all';run('renderRequests()');
assert.match(content(element('requests')),/历史路由/,'history stays searchable without a waiting label');
vm.runInContext(fs.readFileSync('src/static/board.js','utf8'),context);
const summary=context.window.CoopagentsBoard.requestSummary({id:4,body:'Old board question',owner_route_state:'historical',replies:[]},{members:[]});
assert.match(content(summary),/历史路由/);
assert.doesNotMatch(content(summary),/等待回复/);
vm.runInContext(fs.readFileSync('src/static/collaboration.js','utf8'),context);
const queued=new Element(),navigation=[];
context.window.CoopagentsCollaboration.renderPanel(queued,{me:{room_id:'r',member_id:'front'},workflow:{
  requests:[],owner_questions:[{question_key:'q',target_task_id:7,body:'Queued interface question',status:'queued',wait_reason:'awaiting_owner'}]
}},{memberName:id=>id,openWorkflowItem:target=>navigation.push(target)});
assert.match(content(queued),/等待目标任务分配负责人/);
assert.match(content(queued),/Queued interface question/);
assert.doesNotMatch(content(queued),/请求 #undefined|本页暂无待处理请求/);
walk(queued).find(n=>n.textContent==='查看任务 #7').listeners.click();
assert.equal(navigation[0].kind,'task');assert.equal(navigation[0].id,7);
console.log('Owner question current routes, retained history, pending filters and safe actions passed');
