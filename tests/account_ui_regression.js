'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[2],'utf8');
const flush=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
function deferred(){let release;const promise=new Promise(r=>release=r);return {promise,release};}
function harness(){
  const elements=new Map(),storage=new Map(),calls=[],delays=new Map();let bridgeManaged=false,entered=[];
  function element(id){if(!elements.has(id))elements.set(id,new N(id));return elements.get(id);}
  class N {
    constructor(id=''){this.id=id;this.children=[];this.hidden=false;this.value='';this.textContent='';this.listeners={};this.fields={};this.open=false;this.disabled=false;this.tagName='DIV';}
    append(...n){this.children.push(...n);}prepend(...n){this.children.unshift(...n);}replaceChildren(...n){this.children=n;this.textContent='';}
    addEventListener(type,cb){this.listeners[type]=cb;}setAttribute(k,v){this[k]=v;}reset(){for(const n of this.querySelectorAll('input[type=password]'))n.value='';this.fields={};}
    querySelector(){return element(this.id+'-submit');}querySelectorAll(){return [];}
    click(){return this.listeners.click?.({currentTarget:this});}
  }
  const team={team_id:'t1',name:'Team',role:'owner'},p={room_id:'p1',team_id:'t1',name:'Project',repository:''};
  const info={account:{id:'a1',username:'alice',display_name:'Alice'},csrf_token:'csrf-memory-only'};
  const replies={
    '/account/config':{mode:'self-hosted',local_login_enabled:true,bootstrap_enabled:false,github_oauth_enabled:false},
    '/account/session':info,'/account/teams':[team],'/account/teams/t1/projects':[p],
    '/account/teams/t1/managed-projects':[{...p,has_access:true}],'/account/teams/t1/members':[{account_id:'a1',username:'alice',display_name:'Alice',role:'owner'}],
    '/account/projects/p1/select':{web_token:'scoped-private-token',room_id:'p1'},'/account/logout':{ok:true},
  };
  const context=vm.createContext({window:{CrewmeshProject:{clear(){bridgeManaged=false;storage.delete('crewmesh_web_token');element('workspace').hidden=true;},enter(token){bridgeManaged=true;entered.push(token);storage.set('crewmesh_web_token',token);element('workspace').hidden=false;},managed:()=>bridgeManaged,private(){}}},document:{getElementById:element,querySelectorAll:()=>[],createElement:tag=>{const n=new N();n.tagName=tag.toUpperCase();return n;}},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},AbortController,setTimeout:()=>1,clearTimeout(){},JSON,Error,FormData:class{constructor(form){this.form=form;}*[Symbol.iterator](){yield* Object.entries(this.form.fields);}},fetch:async(path,options)=>{calls.push({path,...options});const delay=delays.get(path);if(delay){delays.delete(path);return {status:delay.status||200,ok:!delay.status||delay.status===200,json:()=>delay.body.promise};}const reply=replies[path];return {status:reply===undefined?401:200,ok:reply!==undefined,json:async()=>reply===undefined?{message:'Permission denied'}:reply};}});
  vm.runInContext(source,context);
  return {element,storage,calls,delays,replies,info,entered,window:context.window,async submit(id,fields={}){const form=element(id);form.fields=fields;form.listeners.submit({preventDefault(){},currentTarget:form});await flush();}};
}
(async()=>{
  // A delayed account JSON body must never restore the hub after explicit logout.
  const a=harness(),body=deferred();a.delays.set('/account/session',{body});await flush();a.element('account-logout').click();await flush();body.release(a.info);await flush();assert.equal(a.element('account-hub').hidden,true);assert.equal(a.element('login').hidden,false);
  // Selecting a project returns a scoped token only after the current generation check.
  const b=harness();await flush();const select=deferred();b.delays.set('/account/projects/p1/select',{body:select});b.element('hub-projects').children[0].children[3].click();await flush();b.element('account-logout').click();await flush();select.release({web_token:'stale-project-token'});await flush();assert.deepEqual(b.entered,[]);assert.equal(b.storage.has('crewmesh_web_token'),false);assert.equal(b.element('account-hub').hidden,true);
  // An old team response body cannot repaint a replacement hub generation.
  const c=harness();await flush();const team=deferred();c.delays.set('/account/teams/t1/projects',{body:team});const old=c.window.CrewmeshAccounts.home().catch(()=>{});await flush();c.replies['/account/teams']=[];await c.window.CrewmeshAccounts.home();team.release([{room_id:'old',name:'PRIVATE OLD PROJECT'}]);await old;await flush();assert.equal(c.element('hub-projects').children.some(n=>n.children.some?.(v=>v.textContent==='PRIVATE OLD PROJECT')),false);
  // Permission 401 validates the session rather than logging out a valid account.
  const d=harness();await flush();await d.submit('team-invite-form',{role:'member'});assert.equal(d.element('account-hub').hidden,false);assert.equal(d.element('hub-error').textContent,'Permission denied');assert.equal(d.calls.filter(c=>c.path==='/account/session').length,2);
  const write=d.calls.find(c=>c.path.endsWith('/invites'));assert.equal(write.credentials,'same-origin');assert.equal(write.headers['X-Crewmesh-CSRF'],'csrf-memory-only');assert.deepEqual(JSON.parse(write.body),{role:'member',project_ids:[]});
  for(const [key,value]of d.storage){assert.ok(!/csrf|password|invite|cookie|account_token/i.test(key));assert.ok(!/csrf-memory-only/.test(value));}
  // Project exit is invoked without an awaiting form handler: a failed reload must be caught and displayed.
  const failed=harness();await flush();delete failed.replies['/account/teams'];await assert.doesNotReject(()=>failed.window.CrewmeshAccounts.home());assert.equal(failed.element('hub-error').textContent,'Permission denied');assert.equal(failed.element('account-hub').hidden,false);
  // Successful project selection uses the bridge; logout revokes with CSRF then clears it.
  const e=harness();await flush();e.element('hub-projects').children[0].children[3].click();await flush();assert.deepEqual(e.entered,['scoped-private-token']);assert.equal(e.element('workspace-project').value,'p1');e.element('account-logout').click();await flush();assert.equal(e.storage.has('crewmesh_web_token'),false);const revoke=e.calls.find(c=>c.path==='/account/logout');assert.equal(revoke.headers['X-Crewmesh-CSRF'],'csrf-memory-only');
  console.log('Account session, project, team, CSRF, and permission regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
