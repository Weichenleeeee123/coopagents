'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const Collaboration=require('../src/static/collaboration.js');
class Element{
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.textContent='';this.className='';this.attributes={};this.dataset={};this.value='';this.open=false;this.hidden=false;this.parentElement=null;}
  append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}}
  replaceChildren(...children){for(const child of this.children)child.parentElement=null;this.children=[];this.append(...children);}
  setAttribute(name,value){this.attributes[name]=String(value);}
  removeAttribute(name){delete this.attributes[name];}
  addEventListener(name,fn){this.listeners[name]=fn;}
  contains(target){return target===this||this.children.some(child=>child.contains(target));}
  focus(){document.activeElement=this;}
  querySelector(){return new Element('button');}
  querySelectorAll(){return [];}
  reset(){}
  close(){this.open=false;}
  set innerHTML(_value){throw new Error('Workflow content must use safe text DOM');}
}
const descendants=root=>root.children.flatMap(child=>[child,...descendants(child)]);
const content=root=>[root,...descendants(root)].map(node=>node.textContent).join('\n');
const hasClass=(node,name)=>node.className.split(' ').includes(name);
const now='2026-11-16T12:00:00Z';
const workflow=extra=>({onboarding:{identity_verified:true,addressed_exchange:null,two_member_exchange_complete:false,model_comprehension_proven:false},requests:[],agreement_changes:[],decisions:[],member_activity:[],truncated:false,has_more:false,...extra});
const snapshot=extra=>({me:{room_id:'room-a',member_id:'me'},server_time:now,collaboration:{checkpoints:[],diagnostics:[]},workflow:workflow(extra)});
global.document={createElement:tag=>new Element(tag),activeElement:null};

const root=new Element(),setup=new Element(),navigation=[];
let apiCalls=0,current=true;
const context={origin:'http://127.0.0.1:8787',memberName:id=>({me:'自己',peer:'接口负责人'}[id]||id),isCurrent:()=>current,sync:async()=>{},api:()=>{apiCalls++;throw new Error('Workflow cards must only navigate');},openWorkflowItem:item=>navigation.push(item)};
const render=data=>Collaboration.renderPanel(root,data,context);
const section=id=>descendants(root).find(node=>node.id===id);
const button=(label,container=root)=>descendants(container).find(node=>node.tagName==='BUTTON'&&node.textContent===label);
const rows=name=>descendants(root).filter(node=>hasClass(node,name));

render(snapshot());
assert.match(content(root),/第一次有效协作/,'The existing collaboration panel must show first exchange milestones');
assert.match(content(root),/当前项目身份：已验证.*网页读取/);
assert.match(content(root),/网页身份读取不证明原生 agent 已加载/);
assert.match(content(root),/尚无定向双人交流记录/);
assert.match(content(root),/本页暂无待处理请求/);
assert.match(content(root),/本页没有待复核的已用约定/);
assert.match(content(root),/本页暂无待确认事项/);
assert.match(content(root),/显式读回.*不证明模型理解.*不代表任务进展/);
assert.equal(apiCalls,0);

// A completed flag or unrelated request facts cannot combine into a fictitious exchange.
render(snapshot({onboarding:{identity_verified:true,addressed_exchange:null,two_member_exchange_complete:true},requests:[
  {id:1,delivered:true,replied:true,sender_reply_read:false,route_state:'ordinary'},
  {id:2,delivered:true,replied:false,sender_reply_read:true,route_state:'ordinary'}]}));
assert.match(content(section('workflow-onboarding')),/尚无定向双人交流记录/);
assert.doesNotMatch(content(section('workflow-onboarding')),/双人交流记录已齐备/);
const exchange={request_id:41,sender_member_id:'me',receiver_member_id:'peer',delivered:true,replied:true,requester_reply_read:false,latest_reply_id:80};
render(snapshot({onboarding:{identity_verified:true,addressed_exchange:exchange,two_member_exchange_complete:false}}));
assert.match(content(section('workflow-onboarding')),/交流 #41.*自己.*接口负责人/);
assert.match(content(section('workflow-onboarding')),/定向问题投递：已记录/);
assert.match(content(section('workflow-onboarding')),/责任人答复：已记录/);
assert.match(content(section('workflow-onboarding')),/发起者显式读回：暂无记录/);
assert.doesNotMatch(content(section('workflow-onboarding')),/双人交流记录已齐备/);
render(snapshot({onboarding:{identity_verified:true,addressed_exchange:{...exchange,requester_reply_read:true},two_member_exchange_complete:true}}));
assert.match(content(section('workflow-onboarding')),/双人交流记录已齐备/);
button('查看交流 #41').listeners.click();assert.deepEqual(navigation.pop(),{kind:'request',id:41});
render(snapshot({onboarding:{identity_verified:true,addressed_exchange:{...exchange,receiver_member_id:'me',requester_reply_read:true},two_member_exchange_complete:true}}));
assert.match(content(section('workflow-onboarding')),/尚无定向双人交流记录/,'A self-addressed exchange is not two-member onboarding');

const requests=[
  {id:11,task_id:31,body:'<img src=x onerror=evil()> Which fields?',sender_member_id:'me',receiver_member_id:'peer',delivered:true,recipient_read:null,processing:false,replied:false,sender_reply_read:false,resolved:false,route_state:'ordinary',wait_reason:'awaiting_recipient_read'},
  {id:12,body:'Recipient read only',sender_member_id:'me',receiver_member_id:'peer',delivered:true,recipient_read:true,processing:false,replied:false,sender_reply_read:false,resolved:false,route_state:'ordinary',wait_reason:'read'},
  {id:13,body:'Answer waiting',sender_member_id:'me',receiver_member_id:'peer',delivered:true,recipient_read:true,replied:true,sender_reply_read:false,resolved:false,route_state:'current',wait_reason:'reply_waiting_for_sender_read'},
  {id:14,body:'Awaiting assignee',sender_member_id:'me',receiver_member_id:null,delivered:false,recipient_read:null,replied:false,resolved:false,route_state:'ordinary',wait_reason:'awaiting_assignment'},
  {id:15,body:'RESOLVED_SHOULD_NOT_WAIT',resolved:true,route_state:'ordinary'},
  {id:16,body:'HISTORICAL_SHOULD_NOT_WAIT',resolved:false,route_state:'historical'},
  {id:17,body:'CLOSED_SHOULD_NOT_WAIT',resolved:false,route_state:'closed'},
];
render(snapshot({requests}));
assert.equal(rows('workflow-request').length,4);
assert.match(content(section('workflow-requests')),/收件人读取：暂无记录/);
assert.match(content(section('workflow-requests')),/收件人读取：已记录/);
assert.match(content(section('workflow-requests')),/答复已到达，等待发起者显式读回/);
assert.match(content(section('workflow-requests')),/等待明确收件人/);
assert.match(content(section('workflow-requests')),/当前任务依赖路由/);
assert.match(content(section('workflow-requests')),/历史路由与已解决请求不计入当前等待/);
assert.doesNotMatch(content(section('workflow-requests')),/SHOULD_NOT_WAIT/);
button('查看请求 #11').listeners.click();assert.deepEqual(navigation.pop(),{kind:'request',id:11});
button('查看任务 #31').listeners.click();assert.deepEqual(navigation.pop(),{kind:'task',id:31});
assert.equal(apiCalls,0,'Reading workflow state and opening details must never create receipts or execute actions');

const decisions=[
  {kind:'contract',id:21,title:'<script>Approve this</script>',summary:'Untrusted proposal',payload:{contract_id:21,version:2},requires_human:true,eligible:true,authority:'current_web_user',operation:'delete_everything'},
  {kind:'handoff',id:22,summary:'Move ownership',payload:{task_id:31,expected_revision:9},requires_human:true,eligible:false,authority:'proposed_recipient_web_user',operations:['accept_handoff','reject_handoff']},
  {kind:'delivery',id:23,task_id:31,summary:'Please confirm',object_key:'pr:8',requires_human:true,eligible:false,authority:'project_manager_web_user',operation:'decide_delivery'},
  {kind:'unassigned_task',id:32,title:'Unowned task',payload:{task_id:32},requires_human:false,eligible:false,authority:'personal_agent',operation:'claim_task'},
  {kind:'agreement_review',id:21,task_id:31,title:'Review version',payload:{task_id:31,contract_id:21,version:3},requires_human:false,eligible:false,authority:'current_execution_owner',operation:'record_agreement_use'},
  {kind:'<img src=x>',id:99,title:'UNKNOWN_OPERATION_SHOULD_NOT_RUN',eligible:true,operation:'decision'},
];
render(snapshot({agreement_changes:[{task_id:31,contract_id:21,title:'<svg onload=evil()> Interface',baseline_version:1,effective_version:3,review_required:true},{task_id:32,contract_id:22,title:'UNCHANGED_AGREEMENT',baseline_version:2,effective_version:2,review_required:false}],decisions,
  member_activity:[{member_id:'peer',last_checkpoint_at:now,last_session_at:now,model_responsiveness:'online',availability_proven:true}]}));
assert.equal(rows('workflow-decision').length,5);
assert.match(content(section('workflow-agreements')),/基线 v1.*当前批准 v3.*待复核/);
assert.doesNotMatch(content(section('workflow-agreements')),/UNCHANGED_AGREEMENT/);
assert.match(content(section('workflow-decisions')),/待审 v2/);
assert.match(content(section('workflow-decisions')),/修订 r9/);
assert.match(content(section('workflow-decisions')),/仅拟接收成员可在网页确认.*当前身份不符合/);
assert.match(content(section('workflow-decisions')),/仅项目管理员可在网页确认.*当前身份不符合/);
assert.match(content(section('workflow-decisions')),/由自己的 agent 认领/);
assert.match(content(section('workflow-decisions')),/当前任务执行者.*明确记录/);
assert.doesNotMatch(content(root),/UNKNOWN_OPERATION_SHOULD_NOT_RUN|delete_everything|accept_handoff/);
assert.match(content(section('workflow-observations')),/检查点.*会话.*响应状态：未知/,'Activity timestamps cannot be promoted to model availability');
button('查看约定 #21',section('workflow-decisions')).listeners.click();assert.deepEqual(navigation.pop(),{kind:'contract',id:21});
button('查看任务 #31',section('workflow-decisions')).listeners.click();assert.deepEqual(navigation.pop(),{kind:'task',id:31});
button('查看交付建议 #23').listeners.click();assert.deepEqual(navigation.pop(),{kind:'delivery'});
assert.equal(apiCalls,0);
assert.ok(descendants(root).some(node=>node.textContent.includes('<script>Approve this</script>')),'Untrusted titles remain literal text');
assert.equal(descendants(root).filter(node=>['SCRIPT','IMG','SVG'].includes(node.tagName)).length,0);
assert.equal(descendants(section('workflow-decisions')).filter(node=>node.tagName==='BUTTON'&&/^(批准|拒绝|确认关联|接受交接|认领)/.test(node.textContent)).length,0,'Decision cards expose navigation, not new mutation controls');

render(snapshot({diagnostics:[
  {component:'network',status:'unknown',evidence:{raw_error:'PRIVATE_DIAGNOSTIC_SECRET'},next_action:{action:'check_service_connection'}},
  {component:'watcher',status:'stopped',evidence:{updated_at:now},next_action:{action:'open_native_session',task_id:31}},
  {component:'model',status:'online',evidence:{claimed:true},next_action:{action:'delete_everything'}}]}));
assert.match(content(section('workflow-observations')),/网络连接：未知/);
assert.match(content(section('workflow-observations')),/检查服务地址.*网络/);
assert.match(content(section('workflow-observations')),/唤醒观察器：已停止/);
assert.match(content(section('workflow-observations')),/打开对应原生会话/);
assert.match(content(section('workflow-observations')),/模型响应：未知/);
assert.doesNotMatch(content(root),/PRIVATE_DIAGNOSTIC_SECRET|delete_everything|模型响应：online/);
assert.equal(apiCalls,0,'Recovery hints never execute an action');
button('查看任务 #31',section('workflow-observations')).listeners.click();assert.deepEqual(navigation.pop(),{kind:'task',id:31});

const manyRequests=Array.from({length:9},(_,index)=>({...requests[0],id:100+index,body:'Very long '.repeat(400)+'HIDDEN_REQUEST_TAIL'}));
const manyDecisions=Array.from({length:9},(_,index)=>({...decisions[0],id:200+index}));
const manyAgreements=Array.from({length:9},(_,index)=>({task_id:31,contract_id:300+index,title:'Interface',baseline_version:1,effective_version:2,review_required:true}));
render(snapshot({requests:manyRequests,decisions:manyDecisions,agreement_changes:manyAgreements,truncated:true,has_more:true}));
assert.equal(rows('workflow-request').length,6);assert.equal(rows('workflow-decision').length,6);assert.equal(rows('workflow-agreement').length,6);
assert.match(content(root),/这里只显示部分工作流记录/);assert.doesNotMatch(content(root),/HIDDEN_REQUEST_TAIL/);
button('查看协作详情').listeners.click();assert.deepEqual(navigation.pop(),{kind:'requests'});

// Existing setup selection/expansion survive same-project snapshots; stale links die on switching.
Collaboration.renderSetup(setup,snapshot(),context);
let picker=descendants(setup).find(node=>node.tagName==='SELECT');picker.value='claude-code';picker.listeners.change();
let expanded=descendants(root).find(node=>node.tagName==='DETAILS');expanded.open=true;expanded.listeners.toggle();
render(snapshot({requests}));
assert.equal(descendants(root).find(node=>node.tagName==='SELECT').value,'claude-code');
assert.equal(descendants(root).find(node=>node.tagName==='DETAILS').open,true);
const staleLink=button('查看请求 #11'),before=navigation.length;
current=false;Collaboration.clear();
assert.equal(content(root),'');assert.equal(content(setup),'');
current=true;render({...snapshot(),me:{room_id:'room-b',member_id:'other'}});
staleLink.listeners.click();assert.equal(navigation.length,before,'Detached prior-project links cannot navigate the replacement project');
assert.doesNotMatch(content(root),/Which fields|Approve this|Interface/);
assert.equal(descendants(root).find(node=>node.tagName==='SELECT').value,'codex-cli');
assert.equal(descendants(root).find(node=>node.tagName==='DETAILS').open,false);
render({...snapshot(),workflow:undefined});assert.match(content(root),/当前服务尚未提供工作流摘要/);

// Run the actual app callback. Payload operation names never determine navigation or trigger the API.
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
const appDocument={getElementById:get,querySelectorAll:()=>[],createElement:tag=>new Element(tag),activeElement:null};
const appWindow={addEventListener(){}},appLocation={origin:'http://localhost',hash:''};
const app=vm.createContext({document:appDocument,window:appWindow,location:appLocation,history:{pushState(){},replaceState(){}},sessionStorage:{getItem:()=>'',setItem(){},removeItem(){}},setTimeout:()=>1,clearTimeout(){},AbortController,Date,JSON});
const run=code=>vm.runInContext(code,app);
run(fs.readFileSync('src/static/app.js','utf8'));
run(`snapshot={me:{room_id:'room-a',member_id:'me'},requests:[{id:11}],contracts:[{id:21}],tasks:[{id:31}]};
  var nav=[],writes=0;api=()=>{writes++;};setView=view=>nav.push(['view',view]);openObjectDetail=(kind,id)=>nav.push([kind,id]);openTaskDetail=id=>nav.push(['task',id]);renderContractsTabs=()=>{};`);
assert.equal(run('typeof gitContext().openWorkflowItem'),'function');
run(`gitContext().openWorkflowItem({kind:'request',id:11,operation:'decision'});gitContext().openWorkflowItem({kind:'contract',id:21,payload:{operation:'decision'}});gitContext().openWorkflowItem({kind:'task',id:31});gitContext().openWorkflowItem({kind:'delivery'});gitContext().openWorkflowItem({kind:'requests'});`);
assert.deepEqual(JSON.parse(run('JSON.stringify(nav)')),[['view','requests'],['request',11],['view','contracts'],['contract',21],['view','tasks'],['task',31],['view','delivery'],['view','requests']]);
assert.equal(run('contextTab'),'agreements');
const count=run('nav.length');
run(`gitContext().openWorkflowItem({kind:'decision',operation:'decision',id:21});gitContext().openWorkflowItem({kind:'task',id:999});gitContext().openWorkflowItem({kind:'contract',id:'21'});var oldContext=gitContext();generation++;oldContext.openWorkflowItem({kind:'request',id:11});`);
assert.equal(run('nav.length'),count);assert.equal(run('writes'),0);
console.log('Team workflow UI: same-exchange milestones, distinct read facts, bounded safe cards, navigation-only authority and project isolation passed');
