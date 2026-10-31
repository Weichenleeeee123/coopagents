'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const descendants=root=>root.children.flatMap(n=>[n,...descendants(n)]);
class E{constructor(tag){this.tagName=String(tag).toUpperCase();this.children=[];this.textContent='';this.listeners={};this.attributes={};this.dataset={};this.value='';this.className='';this.parentElement=null;this.isConnected=true;this.hidden=false;this.style={setProperty(){}};this.classList={add:name=>{this.className+=(this.className?' ':'')+name;}};this.x=E.counter++*32;}get firstChild(){return this.children[0]||null;}append(...items){items.forEach(n=>{n.parentElement=this;this.children.push(n);});}prepend(...items){items.reverse().forEach(n=>{n.parentElement=this;this.children.unshift(n);});}replaceChildren(...items){this.children=[];this.append(...items);}setAttribute(k,v){this.attributes[k]=String(v);if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=String(v);}addEventListener(k,fn){this.listeners[k]=fn;}contains(){return false;}querySelectorAll(selector){return this.children.flatMap(n=>[(n.className.split(' ').includes(selector.slice(1))?n:null),...n.querySelectorAll(selector)].filter(Boolean));}querySelector(selector){if(selector.startsWith('[data-node-key=')){const key=selector.split('"')[1];return all(this).find(n=>n.dataset.nodeKey===key)||null;}return null;}getBoundingClientRect(){return {left:this.x,top:this.x,width:12,height:12,right:this.x+12,bottom:this.x+12};}}
E.counter=1;
global.document={createElement:t=>new E(t),createElementNS:(_ns,t)=>new E(t)};global.CSS={escape:value=>value};
const Graph=require('../src/static/delivery_graph.js');
const styles=fs.readFileSync('src/static/styles.css','utf8');
assert.match(styles,/\.git-graph-groups\s*\{[^}]*position:\s*relative/,'Graph surface must establish a positioning context for SVG edges');
assert.match(styles,/\.git-object-row\s*\{[^}]*display:\s*grid/,'Graph objects must use a stable marker/body grid');
assert.match(styles,/\.git-object-marker\s*\{[^}]*grid-column:\s*1/,'Graph markers must stay in the dedicated marker column');
assert.match(styles,/\.git-edge-layer\s*\{[^}]*pointer-events:\s*none/,'Edge layer must stay behind interactive object rows');
assert.match(fs.readFileSync('src/static/delivery_graph.js','utf8'),/z-index:0/,'Edge layer must render behind object rows');
let resizeGraph;const observers=[];
global.ResizeObserver=class{constructor(callback){resizeGraph=callback;this.disconnected=false;observers.push(this);}observe(){}disconnect(){this.disconnected=true;}};
const all=descendants,text=root=>all(root).map(n=>n.textContent).join(' ');
const sha='a'.repeat(40);
const graph={items:[
 {object_key:'branch:feat/ui',kind:'branch',value:'feat/ui',task_ids:[1],associations:[{task_id:1,relationship_source:'observed',source:'local_git',observation_id:7,linked_at:'2026-10-30T12:00:00Z',evidence:'Explicit local Git checkpoint'}]},
 {object_key:'commit:'+sha,kind:'commit',value:sha,task_ids:[1],associations:[{task_id:1,relationship_source:'observed',source:'local_git',observation_id:7,linked_at:'2026-10-30T12:00:00Z',evidence:'Explicit local Git checkpoint'}]},
 {object_key:'pr:17',kind:'pr',value:17,task_ids:[1],associations:[{task_id:1,relationship_source:'observed',source:'github_verified',linked_at:'2026-10-30T12:10:00Z',evidence:'GitHub PR head matches linked branch',head_sha:sha}]},
 {object_key:'release:9',kind:'release',value:9,task_ids:[1],associations:[{task_id:1,relationship_source:'explicit',source:'member_link',linked_at:'2026-10-30T13:00:00Z'}]},
 {object_key:'branch:suspicious',kind:'branch',value:'suspicious',task_ids:[2],associations:[{task_id:2,relationship_source:'suggested',source:'agent_suggestion',state:'pending_confirmation',status:'pending',suggestion_id:44,linked_at:'2026-10-30T13:01:00Z'}]}
],truncated:false};
const git={workspaces:[{id:7,task_id:1,branch:'feat/ui',head:sha,member_id:4,stale:false}],deliveries:[{pr_number:17,branch:'feat/ui',head_sha:sha,state:'open',source:'github_verified',sync_at:'2026-10-30T12:10:00Z',stale:false}],releases:[{release_id:9,tag_name:'v0.9.0',name:'Launch',target_commitish:'main',state:'published',source:'github_verified',sync_at:'2026-10-30T13:00:00Z',stale:false}],github:{deliveries:[{pr_number:17,branch:'feat/ui',head_sha:sha,state:'open',source:'github_verified',sync_at:'2026-10-30T12:10:00Z',stale:false}],releases:[{release_id:9,tag_name:'v0.9.0',name:'Launch',target_commitish:'main',state:'published',source:'github_verified',sync_at:'2026-10-30T13:00:00Z',stale:false}]}};
const projection=Graph.buildGraph(graph,git);
assert.equal(projection.nodes.length,5);
const evidenceOnly=Graph.buildGraph(graph,{...git,workspaces:[]});
assert.ok(evidenceOnly.groups.find(g=>g.id==='branch:feat/ui').nodes.some(n=>n.key==='commit:'+sha),'Explicit checkpoint evidence must group commit and branch even when the workspace list is absent');
assert.ok(projection.edges.some(e=>e.kind==='workspace-head'&&e.from==='branch:feat/ui'&&e.to==='commit:'+sha));
assert.ok(projection.edges.some(e=>e.kind==='pr-head-branch'&&e.from==='branch:feat/ui'&&e.to==='pr:17'));
assert.ok(projection.edges.some(e=>e.kind==='pr-head-sha'&&e.from==='pr:17'&&e.to==='commit:'+sha));
assert.ok(!projection.edges.some(e=>e.to==='release:9'));
assert.ok(!projection.edges.some(e=>e.to==='branch:suspicious'));
assert.equal(projection.nodes.find(n=>n.key==='release:9').title,'Launch');
const multiBranch={items:[
 {kind:'branch',value:'feat/a',task_ids:[10],associations:[{task_id:10,ref_id:11,ownership_epoch:0,relationship_source:'explicit'}]},
 {kind:'branch',value:'feat/b',task_ids:[10],associations:[{task_id:10,ref_id:12,ownership_epoch:0,relationship_source:'explicit'}]},
 {kind:'pr',value:42,task_ids:[10],associations:[{task_id:10,ref_id:11,ownership_epoch:0,relationship_source:'observed',evidence:'GitHub PR head matches linked branch'}]}
]};
const branchEvidence=Graph.buildGraph(multiBranch,{});
assert.deepEqual(branchEvidence.edges.filter(e=>e.kind==='pr-head-branch').map(e=>e.from),['branch:feat/a'],'A shared task cannot connect a PR to a different branch reference');
assert.ok(branchEvidence.groups.find(g=>g.id==='branch:feat/a').nodes.some(n=>n.key==='pr:42'),'Reference-matched PR stays in the evidenced branch lane');
const root=new E('div');let opened=[],decisions=[];
Graph.render(root,graph,git,{openTask:id=>opened.push(id),openNode:key=>opened.push(key),canManage:true,api:async(_path,payload)=>decisions.push(payload),sync:async()=>{}});
assert.match(text(root),/PR #17/);assert.match(text(root),/同一工作区 HEAD/);assert.match(text(root),/PR head SHA 匹配/);
assert.ok(all(root).some(n=>n.className.split(' ').includes('git-lane')));assert.ok(projection.edges.length>=3,'Evidence projection includes actual connected relationships');
const edge=all(root).find(n=>n.tagName==='PATH');
const marker=all(root).find(n=>n.className.split(' ').includes('git-object-marker'));
const previousPath=edge.attributes.d;marker.x+=96;resizeGraph();assert.notEqual(edge.attributes.d,previousPath,'Graph connectors must recalculate when responsive layout moves nodes');
// SVG needs explicit display semantics, and hidden endpoints must never be measured.
const search=all(root).find(n=>n.tagName==='INPUT');
search.value='Launch';search.listeners.input();
assert.equal(edge.attributes.display,'none','Edges touching filtered rows must use SVG display semantics');
assert.equal(edge.attributes.d,'','Filtered endpoints must never generate paths from zero coordinates');
resizeGraph();assert.equal(edge.attributes.d,'');
assert.equal(all(root).filter(n=>n.className==='git-lane'&&!n.hidden).length,1,'Empty branch groups must disappear');
search.value='no object matches';search.listeners.input();
assert.ok(all(root).some(n=>n.className==='graph-filter-empty'&&!n.hidden),'Empty filter results need a clear recovery state');
search.value='';search.listeners.input();
assert.equal(edge.attributes.display,'');assert.ok(edge.attributes.d.startsWith('M '));
// A snapshot refresh while filtering must retain the complete object set.
search.value='Launch';search.listeners.input();
Graph.render(root,graph,git,{openTask:id=>opened.push(id),openNode:key=>opened.push(key),canManage:true,api:async(_path,payload)=>decisions.push(payload),sync:async()=>{}});
const restoredSearch=all(root).find(n=>n.tagName==='INPUT');restoredSearch.value='';restoredSearch.listeners.input();
assert.equal(all(root).filter(n=>n.className==='git-object-row'&&!n.hidden).length,5);
const node=all(root).find(n=>n.className.split(' ').includes('git-object-link')&&n.attributes['data-node-key']==='pr:17');node.listeners.click();assert.ok(opened.includes('pr:17'));
const task=all(root).find(n=>n.textContent==='任务 #1');task.listeners.click();assert.ok(opened.includes(1));
const approve=all(root).find(n=>n.textContent==='确认关联');assert.ok(approve);
(async()=>{await approve.listeners.click();assert.equal(decisions[0].decision,'confirmed');
 const readOnly=new E('div');Graph.render(readOnly,graph,git,{readOnly:true,openTask:id=>opened.push(id)});assert.equal(all(readOnly).some(n=>n.textContent==='确认关联'),false);
 const noAncestry=new E('div');Graph.render(noAncestry,{items:[{object_key:'commit:'+sha,kind:'commit',value:sha,task_ids:[],associations:[]},{object_key:'commit:'+('b'.repeat(40)),kind:'commit',value:'b'.repeat(40),task_ids:[],associations:[]}],truncated:false},{github:{deliveries:[],releases:[]},workspaces:[]},{});assert.equal(Graph.buildGraph({items:[{object_key:'commit:'+sha,kind:'commit',value:sha,associations:[]},{object_key:'commit:'+('b'.repeat(40)),kind:'commit',value:'b'.repeat(40),associations:[]} ]},{github:{deliveries:[],releases:[]},workspaces:[]}).edges.length,0);
 assert.equal(all(root).some(n=>['SCRIPT','IMG'].includes(n.tagName)),false);
 Graph.render(root,null);assert.equal(observers[0].disconnected,true,'Clearing the delivery graph must release its resize observer');
 console.log('Git graph evidence, confirmed edges, object/task navigation, read-only guard and safe DOM passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
