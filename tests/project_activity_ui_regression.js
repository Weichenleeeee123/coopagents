'use strict';
const assert=require('node:assert/strict');
const Activity=require('../src/static/project_activity.js');
class Element{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.textContent='';this.className='';this.listeners={};this.value='';}
  append(child){this.children.push(child);}
  replaceChildren(...children){this.children=children;}
  setAttribute(){}
  addEventListener(type,fn){this.listeners[type]=fn;}
  click(){this.listeners.click?.();}
}
function descendants(root){return root.children.flatMap(child=>[child,...descendants(child)]);}
global.document={createElement:tag=>new Element(tag)};
const root=new Element('section');
let openedTask=null;
Activity.render(root,{limit:2,truncated:true,items:[
  {id:'new',type:'progress_reported',occurred_at:'2026-01-02T00:00:00Z',actor_member_id:'m1',task_id:1,source:'agent_report',summary:'Tests pass',reference:null,prompt:'PRIVATE-PROMPT'},
  {id:'old',type:'release_verified',occurred_at:'2026-01-01T00:00:00Z',actor_member_id:null,task_id:1,source:'github_verified',summary:'Release v1.0.0 published',reference:{tag_name:'v1.0.0',url:'https://github.com/acme/demo/releases/tag/v1.0.0',body:'PRIVATE-BODY',transcript_path:'PRIVATE-PATH',stale:true}}
]},{openTask:id=>{openedTask=id;}});
assert.match(descendants(root).map(n=>n.textContent).join(' '),/Tests pass.*v1\.0\.0.*仅显示最近 2 条/);
assert.doesNotMatch(descendants(root).map(n=>n.textContent).join(' '),/PRIVATE/);
assert.ok(!descendants(root).some(n=>['IMG','SCRIPT'].includes(n.tagName)));
assert.equal(descendants(root).filter(n=>n.tagName==='A').length,1);
assert.match(descendants(root).map(n=>n.textContent).join(' '),/远端证据已过期/);
descendants(root).find(n=>n.tagName==='BUTTON'&&n.textContent==='打开任务').click();
assert.equal(openedTask,1);
const directActivity=new Element('section');
Activity.render(directActivity,{items:[
  {id:'d1',type:'github_direct_branch',occurred_at:'2026-01-03T00:00:00Z',task_id:3,source:'github_verified',summary:'Task branch coopagents/task-3-1-build has no matching governed delivery record',reference:{branch:'coopagents/task-3-1-build',head_sha:'a'.repeat(40),stale:false}},
  {id:'d2',type:'github_unattributed_branch',occurred_at:'2026-01-02T00:00:00Z',task_id:null,source:'github_verified',summary:'Branch wip is not associated with any task',reference:{branch:'wip',head_sha:'b'.repeat(40),stale:false}},
  {id:'d3',type:'github_default_branch_direct_push',occurred_at:'2026-01-01T00:00:00Z',task_id:null,source:'github_verified',summary:'Default branch main head has no matching governed evidence',reference:{branch:'main',head_sha:'c'.repeat(40),stale:true}}
]},{});
assert.equal(descendants(directActivity).filter(n=>n.className==='activity-item').length,3);
assert.match(descendants(directActivity).map(n=>n.textContent).join(' '),/任务分支无治理记录.*未归属分支.*默认分支 HEAD 无治理记录/);
assert.match(descendants(directActivity).map(n=>n.textContent).join(' '),/远端证据已过期/);
const directCompact=new Element('section');
Activity.render(directCompact,{items:[
  {id:'d1',type:'github_direct_branch',occurred_at:'2026-01-03T00:00:00Z',task_id:3,source:'github_verified',summary:'No governed record',reference:null},
  {id:'d2',type:'github_unattributed_branch',occurred_at:'2026-01-02T00:00:00Z',task_id:null,source:'github_verified',summary:'Unattributed',reference:null}
]},{compact:true,maxItems:4});
assert.equal(descendants(directCompact).filter(n=>n.className==='activity-item').length,2);
const typeFilter=descendants(root).find(n=>n.tagName==='SELECT');
typeFilter.value='progress_reported';typeFilter.listeners.change();
assert.match(descendants(root).map(n=>n.textContent).join(' '),/Tests pass/);
assert.doesNotMatch(descendants(root).map(n=>n.textContent).join(' '),/Release v1\.0\.0/);
const compact=new Element('section');let viewedAll=false;
Activity.render(compact,{items:Array.from({length:5},(_,i)=>({id:'compact-'+i,type:'task_created',occurred_at:`2026-01-0${i+1}T00:00:00Z`,source:'task',summary:'Task '+i,reference:null}))},{compact:true,maxItems:2,viewAll:()=>{viewedAll=true;}});
assert.equal(descendants(compact).filter(n=>n.className==='activity-filter').length,0);
assert.equal(descendants(compact).filter(n=>n.className==='activity-item').length,2);
descendants(compact).find(n=>n.textContent==='查看全部活动').click();assert.equal(viewedAll,true);
console.log('Activity bounded projection, safe DOM and private-field regressions passed');
