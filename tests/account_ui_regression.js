'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[2],'utf8');
const flush=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
function deferred(){let release;const promise=new Promise(r=>release=r);return {promise,release};}
function harness(hash='', invitation=false, anonymous=false, oauth=false){
  const elements=new Map(),storage=new Map(),calls=[],delays=new Map(),privateViews=[];let bridgeManaged=false,entered=[];
  function element(id){if(!elements.has(id))elements.set(id,new N(id));return elements.get(id);}
  class N {
    constructor(id=''){this.id=id;this.children=[];this.hidden=false;this.value='';this.textContent='';this.listeners={};this.fields={};this.open=false;this.disabled=false;this.tagName='DIV';}
    append(...n){this.children.push(...n);}prepend(...n){this.children.unshift(...n);}replaceChildren(...n){this.children=n;this.textContent='';}
    addEventListener(type,cb){this.listeners[type]=cb;}setAttribute(k,v){this[k]=v;}reset(){for(const n of this.querySelectorAll('input[type=password]'))n.value='';this.fields={};}
    querySelector(selector){return element(this.id+(selector==='[name=invite_token]'?'-invite':'-submit'));}querySelectorAll(){return [];}
    closest(selector){return selector==='label'?element(this.id+'-label'):null;}
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
  if(anonymous)delete replies['/account/session'];
  if(oauth)replies['/account/config']={mode:'cloud',local_login_enabled:false,github_oauth_enabled:true};
  replies['/account/invites/preview']={team_id:'t1',team_name:'Team',role:'member',projects:[{room_id:'p1',name:'Project'}],expires_at:'2099-01-01'};
  replies['/account/invites/accept']={...info,team_id:'t1',project_ids:['p1']};replies['/account/login']=info;
  const location={hash,origin:'https://crew.example',pathname:'/',search:''};
  const context=vm.createContext({window:{listeners:{},addEventListener(type,cb){const prior=this.listeners[type];this.listeners[type]=async(...args)=>{await prior?.(...args);return cb(...args);};},location,history:{replaceState(){location.hash='';}},CrewmeshProject:{clear(){bridgeManaged=false;storage.delete('crewmesh_web_token');element('workspace').hidden=true;},enter(token){bridgeManaged=true;entered.push(token);storage.set('crewmesh_web_token',token);element('workspace').hidden=false;},managed:()=>bridgeManaged,private(...args){privateViews.push(args);}}},document:{getElementById:element,querySelectorAll:()=>[],createElement:tag=>{const n=new N();n.tagName=tag.toUpperCase();return n;}},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},AbortController,setTimeout:()=>1,clearTimeout(){},JSON,Error,FormData:class{constructor(form){this.form=form;}*[Symbol.iterator](){yield* Object.entries(this.form.fields);}},fetch:async(path,options)=>{calls.push({path,...options});const delay=delays.get(path);if(delay){delays.delete(path);return {status:delay.status||200,ok:!delay.status||delay.status===200,json:()=>delay.body.promise};}const reply=replies[path];return {status:reply===undefined?401:200,ok:reply!==undefined,json:async()=>reply===undefined?{message:'Permission denied'}:reply};}});
  if(invitation)vm.runInContext(fs.readFileSync('src/static/invitations.js','utf8'),context);
  vm.runInContext(source,context);
  return {element,storage,calls,delays,replies,info,entered,privateViews,window:context.window,document:context.document,async submit(id,fields={}){const form=element(id);form.fields=fields;form.listeners.submit({preventDefault(){},currentTarget:form});await flush();}};
}
(async()=>{
  // Landing immediately strips the fragment, previews without consuming, and waits for a person.
  const invite=harness('#invite=private%2Binvite',true);await flush();
  assert.equal(invite.window.location.hash,'');
  assert.equal(invite.calls.filter(c=>c.path==='/account/invites/preview').length,1);
  assert.equal(invite.calls.some(c=>c.path==='/account/invites/accept'),false);
  assert.equal(invite.element('invitation-accept').hidden,false);
  assert.equal(invite.element('register-form-invite').value,'private+invite');
  assert.equal(invite.element('register-form-invite-label').hidden,true);
  assert.equal(invite.window.CrewmeshInvitations.link({invite_token:'a+b'}),'https://crew.example/#invite=a%2Bb');
  invite.element('invitation-accept').click();await flush();
  assert.equal(invite.calls.filter(c=>c.path==='/account/invites/accept').length,1);
  assert.deepEqual(invite.entered,['scoped-private-token']);
  assert.equal(invite.element('invitation-panel').hidden,true);
  assert.equal(invite.element('register-form-invite-label').hidden,false);
  assert.equal(invite.element('register-form-invite').value,'');
  assert.ok([...invite.storage.values()].every(v=>!String(v).includes('private+invite')));
  // Local login keeps the in-memory invitation and still requires explicit acceptance.
  const loginInvite=harness('#invite=login-secret',true,true);await flush();
  await loginInvite.submit('account-login',{username:'alice',password:'password'});
  assert.equal(loginInvite.calls.some(c=>c.path==='/account/invites/accept'),false);
  assert.equal(loginInvite.element('invitation-accept').hidden,false);
  loginInvite.element('invitation-accept').click();await flush();assert.deepEqual(loginInvite.entered,['scoped-private-token']);
  // New local registration includes the pending token and routes to the invited project.
  const registerInvite=harness('#invite=registration-secret',true,true);await flush();
  await registerInvite.submit('register-form',{username:'new',password:'password',invite_token:''});
  assert.equal(JSON.parse(registerInvite.calls.find(c=>c.path==='/account/invites/accept').body).invite_token,'registration-secret');
  assert.deepEqual(registerInvite.entered,['scoped-private-token']);
  const dismissedInvite=harness('#invite=dismissed-secret',true,true);await flush();
  assert.equal(dismissedInvite.element('register-form-invite-label').hidden,true);
  dismissedInvite.element('invitation-dismiss').click();await flush();
  assert.equal(dismissedInvite.element('register-form-invite-label').hidden,false);
  assert.equal(dismissedInvite.element('register-form-invite').value,'');
  assert.equal(dismissedInvite.calls.some(c=>c.path==='/account/invites/accept'),false);
  // OAuth preserves the secret in the original page while authentication runs in a new tab.
  const oauthInvite=harness('#invite=oauth-secret',true,true,true);await flush();
  assert.equal(oauthInvite.element('github-login').target,'_blank');
  assert.match(oauthInvite.element('invitation-status').textContent,/新标签页/);
  oauthInvite.replies['/account/session']=oauthInvite.info;
  oauthInvite.element('invitation-refresh').click();await flush();
  assert.equal(oauthInvite.element('invitation-accept').hidden,false);
  assert.equal(oauthInvite.calls.some(c=>c.path==='/account/invites/accept'),false);
  assert.ok([...oauthInvite.storage.values()].every(v=>!String(v).includes('oauth-secret')));
  // Invalid/used invitations never enable acceptance; unrelated billing hashes are preserved.
  const invalidInvite=harness('#invite=used-secret',true,true);delete invalidInvite.replies['/account/invites/preview'];await flush();
  assert.equal(invalidInvite.element('invitation-accept').hidden,true);
  assert.equal(invalidInvite.element('invitation-status').textContent,'Permission denied');
  const billingInvite=harness('#billing',true);await flush();assert.equal(billingInvite.window.location.hash,'#billing');
  // A team-load generation switch during preview retries instead of losing the invitation.
  const slowInvite=harness('#invite=slow-secret',true),previewBody=deferred();
  slowInvite.delays.set('/account/invites/preview',{body:previewBody});await flush();
  previewBody.release(slowInvite.replies['/account/invites/preview']);await flush();
  assert.equal(slowInvite.element('invitation-accept').hidden,false);
  // A project-card shortcut issues a member invite for exactly that project and shows a copyable link.
  const shortcut=harness('',true);await flush();shortcut.replies['/account/teams/t1/invites']={invite_token:'copy-secret',expires_at:'2099-01-01'};
  shortcut.element('hub-projects').children[0].children[4].click();await flush();
  assert.deepEqual(JSON.parse(shortcut.calls.find(c=>c.path==='/account/teams/t1/invites').body),{role:'member',project_ids:['p1']});
  assert.equal(shortcut.privateViews[0][1].invite_url,'https://crew.example/#invite=copy-secret');
  assert.equal(shortcut.privateViews[0][1].invite_token,undefined);
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
  // Hub navigation exposes one view; same-team refresh keeps it, team changes reset it.
  const views=harness();await flush();
  assert.equal(views.element('hub-view-projects').hidden,false);
  assert.equal(views.element('hub-view-members').hidden,true);
  views.element('hub-nav-members').click();
  assert.equal(views.element('hub-view-members').hidden,false);
  assert.equal(views.element('hub-view-projects').hidden,true);
  assert.equal(views.element('hub-nav-members')['aria-current'],'page');
  assert.equal(views.document.title,'团队成员 · Crewmesh');
  views.element('hub-refresh').click();await flush();
  assert.equal(views.element('hub-view-members').hidden,false);
  views.replies['/account/teams'].push({team_id:'t2',name:'Second',role:'member'});
  views.replies['/account/teams/t2/projects']=[];views.replies['/account/teams/t2/members']=[];
  views.element('hub-team').value='t2';views.element('hub-team').listeners.change();await flush();
  assert.equal(views.element('hub-view-projects').hidden,false);
  assert.equal(views.element('hub-view-members').hidden,true);
  assert.equal(views.element('project-manager').hidden,true);
  for(const hash of ['#billing','#billing-return']){
    const billing=harness(hash);await flush();
    assert.equal(billing.element('hub-view-billing').hidden,false);
    assert.equal(billing.element('hub-view-projects').hidden,true);
  }
  const fragment=harness();await flush();fragment.window.location.hash='#billing-return';
  assert.equal(typeof fragment.window.listeners.hashchange,'function');
  await fragment.window.listeners.hashchange();await flush();
  assert.equal(fragment.element('hub-view-billing').hidden,false);
  assert.equal(fragment.element('hub-view-projects').hidden,true);
  // Switching team during a delayed refresh must not silently ignore the user's choice.
  const rapid=harness();await flush();
  rapid.replies['/account/teams'].push({team_id:'t2',name:'Second',role:'member'});
  rapid.replies['/account/teams/t2/projects']=[];rapid.replies['/account/teams/t2/members']=[];
  const slowRefresh=deferred();rapid.delays.set('/account/teams',{body:slowRefresh});
  rapid.element('hub-refresh').click();await flush();
  rapid.element('hub-team').value='t2';rapid.element('hub-team').listeners.change();await flush();
  assert.equal(rapid.element('hub-team').value,'t2');
  assert.ok(rapid.calls.some(c=>c.path==='/account/teams/t2/projects'));
  slowRefresh.release(rapid.replies['/account/teams']);await flush();
  assert.equal(rapid.element('hub-team').value,'t2');
  assert.equal(rapid.element('project-manager').hidden,true);
  // A delayed project load shows loading rather than an empty project state.
  const loading=harness();await flush();const loadingBody=deferred();
  loading.delays.set('/account/teams/t1/projects',{body:loadingBody});
  const loadingHome=loading.window.CrewmeshAccounts.home();await flush();
  assert.equal(loading.element('hub-loading').hidden,false);
  loadingBody.release([]);await loadingHome;await flush();
  assert.equal(loading.element('hub-loading').hidden,true);
  console.log('Account session, project, team, CSRF, and permission regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
