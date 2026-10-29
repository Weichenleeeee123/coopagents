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
const typeFilter=descendants(root).find(n=>n.tagName==='SELECT');
typeFilter.value='progress_reported';typeFilter.listeners.change();
assert.match(descendants(root).map(n=>n.textContent).join(' '),/Tests pass/);
assert.doesNotMatch(descendants(root).map(n=>n.textContent).join(' '),/Release v1\.0\.0/);
console.log('Activity bounded projection, safe DOM and private-field regressions passed');
