'use strict';
const assert=require('node:assert/strict');
class E{constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.textContent='';this.listeners={};this.value='';}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}setAttribute(){}addEventListener(k,fn){this.listeners[k]=fn;}}
global.document={createElement:tag=>new E(tag)};
const Discovery=require('../src/static/capability_discovery.js');
const all=root=>root.children.flatMap(n=>[n,...all(n)]);
const root=new E('div');let opened;
Discovery.render(root,{members:[{member_id:'m',display_name:'<script>member</script>',agent_count:1,agents:[{harness:'cursor',version:'1',platform:'windows',repository:'repo',branch:'main',status:'stale',updated_at:'2020-01-01T00:00:00Z',task_id:3,reported_capabilities:{idle_wake:'supported'},capabilities:{idle_wake:'unknown'},evidence_source:'agent_report'}]}],harnesses:[{harness:'cursor',name:'Cursor',capabilities:{mcp:'unknown'},evidence:{source:'unverified',version:'unknown',platform:'unknown',constraints:'PRIVATE <img src=x>'}}]}, {openTask:id=>opened=id});
let text=all(root).map(n=>n.textContent).join(' ');
assert.match(text,/登记已过期/);assert.match(text,/未验证/);assert.match(text,/windows/);
assert.match(text,/agent 自报/);assert.doesNotMatch(text,/模型正在工作|在线/);
assert.ok(!all(root).some(n=>['IMG','SCRIPT'].includes(n.tagName)));
all(root).find(n=>n.tagName==='BUTTON'&&n.textContent==='任务 #3').listeners.click();assert.equal(opened,3);
Discovery.render(root,null);assert.doesNotMatch(all(root).map(n=>n.textContent).join(' '),/member|PRIVATE/);
console.log('Capability discovery evidence, safe DOM and replacement regressions passed');
