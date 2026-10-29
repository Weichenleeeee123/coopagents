'use strict';
const assert=require('node:assert/strict');
const Assets=require('../src/static/project_assets.js');
class Element{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.textContent='';this.className='';this.listeners={};this.attributes={};this.value='';this.files=[];this.disabled=false;}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  addEventListener(type,fn){this.listeners[type]=fn;}
  setAttribute(key,value){this.attributes[key]=value;}
  click(){this.listeners.click?.({currentTarget:this});}
}
function descendants(node){return node.children.flatMap(child=>[child,...descendants(child)]);}
global.document={createElement:tag=>new Element(tag)};
global.FormData=class{constructor(){this.values=[];}append(...args){this.values.push(args);}};
global.URL={createObjectURL:()=> 'blob:asset',revokeObjectURL(){}};
const calls=[];
let activeRoomId='project-a';
const context={roomId:'project-a',isCurrent:()=>true,api:async(path,data,auth,headers,mode)=>{
  calls.push({path,data,auth,headers,mode});
  if(path==='/api/assets')return {assets:activeRoomId==='project-a'?[{id:'a1',filename:'guide.md',size_bytes:7,media_type:'text/markdown',sha256:'abc',source_type:'upload',source_ref:'',uploader_member_id:'m1',created_at:'2026-01-01T00:00:00Z'}]:[]};
  return {ok:true};
}};
const root=new Element('main');
Assets.render(root,context);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  let nodes=descendants(root),input=nodes.find(n=>n.tagName==='INPUT'),upload=nodes.find(n=>n.tagName==='BUTTON');
  assert.ok(input,'file input is present');
  assert.equal(calls.filter(c=>c.path==='/api/assets'&&c.data).length,0,'selecting a file does not upload it');
  input.files=[{name:'notes.txt'}];
  const sourceType=nodes.find(n=>n.tagName==='SELECT'),sourceRef=nodes.find(n=>n.tagName==='INPUT'&&n!==input);
  sourceType.value='path';sourceType.listeners.change();sourceRef.value='docs/notes.txt';
  upload.click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.filter(c=>c.path==='/api/assets'&&c.data).length,1);
  const form=calls.find(c=>c.path==='/api/assets'&&c.data).data;
  assert.equal(form.values[0][0],'file');
  assert.equal(form.values[1][0],'source_type');
  assert.deepEqual(form.values.slice(1).map(value=>value[1]),['path','docs/notes.txt']);
  assert.match(descendants(root).map(n=>n.textContent).join(' '),/guide\.md/);
  assert.ok(nodes.some(n=>n.textContent.includes('SHA-256 abc')));
  activeRoomId='project-b';Assets.render(root,{...context,roomId:'project-b'});
  await new Promise(resolve=>setImmediate(resolve));
  assert.doesNotMatch(descendants(root).map(n=>n.textContent).join(' '),/guide\.md/,'switching projects clears the previous asset list');
  console.log('Project asset panel requires explicit upload and clears project-scoped data');
})().catch(error=>{console.error(error);process.exitCode=1;});
