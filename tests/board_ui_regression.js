'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {constructor(tag){this.tagName=tag;this.children=[];this.textContent='';this.handlers={};}append(...nodes){this.children.push(...nodes);}setAttribute(){}addEventListener(event,fn){this.handlers[event]=fn;}replaceChildren(...nodes){this.children=nodes;}}
const context={window:{},document:{createElement:tag=>new Node(tag)}};
vm.createContext(context);vm.runInContext(fs.readFileSync('src/static/board.js','utf8'),context);
const board=context.window.CoopagentsBoard, task={id:1,title:'<img onerror=evil>',scope:'src/',owner_member_id:2,state:'claimed'},progress={task_id:1,state:'merged',summary:'<script>evil</script>'};
const snapshot={tasks:[task],progress:[progress],members:[{member_id:2,display_name:'Owner'}],requests:[],contracts:[],dependencies:[],git:{}};
assert.equal(board.column({...task,cancelled_at:'now'},progress,snapshot),'cancelled');
assert.equal(board.column({...task,owner_member_id:null},progress,snapshot),'open');
assert.equal(board.column(task,progress,snapshot,{dependencies:{blocked:()=>true}}),'blocked');
assert.equal(board.column(task,progress,snapshot,{git:{state:()=> 'blocked'}}),'blocked');
assert.equal(board.column(task,progress,snapshot),'merged');
assert.equal(board.column(task,{state:'local_done'},snapshot),'review');
assert.equal(board.column(task,{state:'working'},snapshot),'working');
assert.equal(board.matchingTasks([task],[progress],'SCRIPT','2').length,1);
assert.equal(board.matchingTasks([task],[progress],'','unassigned').length,0);
const card=board.card(task,progress,snapshot,{open:()=>{},git:{summarize:()=> 'GitHub 验证 · 检查未知'}});
function values(n){return [n.textContent,...n.children.flatMap(values)];}
assert(values(card).includes(task.title));assert(values(card).includes(progress.summary));assert(values(card).includes('GitHub 验证 · 检查未知'));
assert(!Object.hasOwn(card,'innerHTML'));
console.log('Shared board classification, escaping and evidence passed');

// The hosted application delegates to the shared module while retaining its
// standalone fallback for existing embedded integrations.
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{value:'',hidden:false,open:false,textContent:'',addEventListener(){},replaceChildren(){},reset(){}});return elements.get(id);}
let release,fetchCount=0,timers=[];
const hosted=vm.createContext({window:{CoopagentsBoard:board,CoopagentsRealtime:{connect:()=>({close(){}})},addEventListener(){}},
 document:{getElementById:element,querySelectorAll:()=>[],activeElement:null},sessionStorage:{getItem:()=>'',setItem(){},removeItem(){}},
 setTimeout:(fn,delay)=>{timers.push({fn,delay});return fn;},clearTimeout:id=>{timers=timers.filter(t=>t.fn!==id);},AbortController,Date,JSON,
 location:{origin:'http://127.0.0.1:8000'},fetch:async()=>{fetchCount++;return {status:200,ok:true,json:()=>new Promise(resolve=>release=resolve)};}});
vm.runInContext(fs.readFileSync('src/static/app.js','utf8'),hosted);
assert.equal(vm.runInContext("taskColumn({owner_member_id:null},{state:'merged'})",hosted),'open');
vm.runInContext("token='hosted';render=()=>{};sync()",hosted);
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));vm.runInContext('sync()',hosted);assert.equal(fetchCount,1);
 release({tasks:[],server_time:null});await new Promise(resolve=>setImmediate(resolve));
 const followup=timers.find(t=>t.delay===0);assert(followup,'Invalidation during snapshot must schedule a follow-up');followup.fn();await new Promise(resolve=>setImmediate(resolve));assert.equal(fetchCount,2);
 release({tasks:[]});await new Promise(resolve=>setImmediate(resolve));
 console.log('Hosted shared delegation and busy snapshot invalidation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
