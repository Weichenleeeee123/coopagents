'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const dialogEvents=[];
class N{constructor(tag='DIV'){this.tagName=tag.toUpperCase();this.children=[];this.textContent='';this.className='';this.listeners={};this.attributes={};this.dataset={};this.hidden=false;this.value='';this.open=false;this.isConnected=true;}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}setAttribute(k,v){this.attributes[k]=String(v);}removeAttribute(k){delete this.attributes[k];}addEventListener(k,fn){this.listeners[k]=fn;}querySelector(){return new N('button');}querySelectorAll(){return [];}contains(){return false;}focus(){}showModal(){this.open=true;}close(){if(!this.open)return;this.open=false;dialogEvents.push(()=>this.listeners.close?.());}reset(){}}
const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,new N());return elements.get(id);};
const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>[],createElement:t=>new N(t),activeElement:null},window:{addEventListener(){}},sessionStorage:{getItem:()=>'',setItem(){},removeItem(){}},location:{hash:'',origin:'http://localhost'},history:{pushState(){},replaceState(){}},setTimeout:()=>1,clearTimeout(){},AbortController,Date,JSON});
vm.runInContext(fs.readFileSync('src/static/app.js','utf8'),context);
const all=root=>root.children.flatMap(n=>[n,...all(n)]),text=root=>all(root).map(n=>n.textContent).join(' '),run=s=>vm.runInContext(s,context);
run(`snapshot={me:{member_id:1},members:[{member_id:1,display_name:'Alex'},{member_id:2,display_name:'Mia'}],tasks:[{id:1,title:'Linked real task',scope:'src/',intent_key:'linked-task',state:'open'}],progress:[],requests:[{id:8,body:'Can we approve the contract?',sender_member_id:1,receiver_member_id:2,context_version:1,replies:[{author_member_id:2,body:'Please review the source',evidence:'PRIVATE_DETAIL_EVIDENCE'}]}],contracts:[{id:9,contract_key:'contract-key',current_version:2,effective_version:1,versions:[{version:1,title:'Effective contract',body:'Current agreement',decision:'approved'},{version:2,title:'Proposed contract',body:'PROPOSED_VERSION_DETAIL',proposer_member_id:2}]}],events:[]};renderRequests();renderContracts();`);
assert(!text(element('requests')).includes('PRIVATE_DETAIL_EVIDENCE'),'Request list keeps full evidence in its drawer');
const request=all(element('requests')).find(n=>n.className==='object-title-button');assert(request,'Request title opens an object drawer');request.listeners.click();
assert.equal(element('task-dialog').open,true);assert.match(text(element('task-detail')),/PRIVATE_DETAIL_EVIDENCE/);assert.match(text(element('task-detail')),/确认请求已解决/);
run('closeTaskDetail()');while(dialogEvents.length)dialogEvents.shift()();
assert(!text(element('contracts')).includes('PROPOSED_VERSION_DETAIL'),'Agreement list keeps version history in its drawer');
assert.match(text(element('contracts')),/生效 v1/);assert.match(text(element('contracts')),/待审 v2/);
all(element('contracts')).find(n=>n.className==='object-title-button').listeners.click();
assert.match(text(element('task-detail')),/PROPOSED_VERSION_DETAIL/);assert.ok(all(element('task-detail')).some(n=>n.textContent==='批准 v2'),'Authorized approval stays available in the drawer');
run(`snapshot.git={can_manage:true,delivery_graph:{items:[]},workspaces:[{branch:'main',head:'actual'}]};snapshot.me.room_id='hosted';window.CoopagentsDeliveryGraph={render(...args){window.graphArgs=args;}};renderDeliveryTraceability();`);
const args=context.window.graphArgs;assert.equal(args[2].workspaces[0].head,'actual','Hosted graph receives actual Git facts');assert.equal(args[3].canManage,true);assert.equal(typeof args[3].api,'function','Suggestion controls retain the authenticated API');
args[3].openNode('pr:17',{kind:'pr',label:'PR #17',value:'17',title:'Actual PR title',task_ids:[1],associations:[],state:'open'});
assert.match(text(element('task-detail')),/Actual PR title/);assert.ok(all(element('task-detail')).some(n=>n.textContent==='PR #17'),'Graph object links pass the complete node into the drawer');
all(element('task-detail')).find(n=>n.textContent==='任务：Linked real task').listeners.click();
// A native dialog close event is queued, never dispatched synchronously by close().
while(dialogEvents.length)dialogEvents.shift()();
assert.equal(element('task-dialog').open,true);assert.match(text(element('task-detail')),/Linked real task/,'Delivery-to-task navigation survives queued native dialog events');
run('closeTaskDetail();openObjectDetail("request",8)');while(dialogEvents.length)dialogEvents.shift()();assert.match(text(element('task-detail')),/PRIVATE_DETAIL_EVIDENCE/,'A stale queued close cannot erase a newly opened object');
console.log('Object drawers retain content across asynchronous native close events and graph navigation');
