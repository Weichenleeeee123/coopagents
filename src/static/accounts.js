/* Account cookies stay HttpOnly. Only scoped project credentials use the existing tab storage. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const project = window.CrewmeshProject;
  let epoch = 0, session = null, config = null, teams = [], projects = [], managed = [], members = [], teamId = '', roomId = '', busy = false, operationId = 0;
  const pending = new Set();
  const stale = () => new Error('访问已切换');
  const node = (tag, value, cls) => { const n=document.createElement(tag); n.textContent=value == null?'':String(value); if(cls)n.className=cls;return n; };
  const btn = (label, action) => {const n=node('button',label);n.type='button';n.addEventListener('click',()=>act(n,action));return n;};
  const routeTeam = () => '/account/teams/'+encodeURIComponent(teamId);
  function invalidate() {
    window.CrewmeshBilling?.clear();
    epoch++; for(const c of pending)c.abort(); pending.clear(); project.clear();
    el('workspace').hidden=true;el('account-switchers').hidden=true;
    ['hub-projects','hub-members','invite-scopes'].forEach(id=>el(id).replaceChildren());
    el('hub-identity').textContent='';el('hub-error').textContent='';el('workspace-project').replaceChildren();
    for(const input of document.querySelectorAll('input[type=password]'))input.value='';projects=[];managed=[];members=[];roomId='';
    sessionStorage.removeItem('crewmesh_selected_project');
  }
  function loggedOut() {
    invalidate();session=null;teams=[];teamId='';
    sessionStorage.removeItem('crewmesh_account_project');sessionStorage.removeItem('crewmesh_selected_team');
    el('account-hub').hidden=true;el('login').hidden=false;
    ['account-login','bootstrap-form','register-form','accept-form','password-form','claim-form','project-form','team-form','team-invite-form'].forEach(id=>el(id).reset());
    el('hub-team').replaceChildren();el('workspace-team').replaceChildren();el('workspace-project').replaceChildren();
  }
  async function request(path, data, headers = {}, check = true, timeout = 10000) {
    const mine=epoch, c=new AbortController();pending.add(c);
    const timer=setTimeout(()=>c.abort(),timeout);
    try {
      const h={...headers};if(data!==undefined){h['Content-Type']='application/json';if(session)h['X-Crewmesh-CSRF']=session.csrf_token;}
      const response=await fetch(path,{method:data===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:h,body:data===undefined?undefined:JSON.stringify(data),signal:c.signal});
      if(mine!==epoch)throw stale();
      const body=await response.json();if(mine!==epoch)throw stale();
      if(!response.ok){
        if(response.status===401 && session && check){
          // Authorization denials use 401 too: validate the cookie before ending the account session.
          try{await request('/account/session',undefined,{},false);}catch(error){if(mine===epoch && error.status===401)loggedOut();}
          if(mine!==epoch)throw stale();
        }
        const error=new Error(body.message || (response.status===503?'服务繁忙，请稍后重试':'操作未完成'));error.status=response.status;throw error;
      }
      return body;
    } catch(error) {if(mine!==epoch)throw stale();if(error.name==='AbortError')throw new Error('连接超时，请重试');throw error;}
    finally{clearTimeout(timer);pending.delete(c);}
  }
  async function act(button, operation) {
    if(busy)return;busy=true;const ticket=++operationId,mine=epoch;button.disabled=true;el(session?'hub-error':'account-error').textContent='';
    try{await operation();}catch(error){if(mine===epoch || error.message!=='访问已切换')el(session?'hub-error':'account-error').textContent=error.message;}
    finally{if(ticket===operationId)busy=false;button.disabled=false;}
  }
  function bind(id, operation) {el(id).addEventListener('submit',e=>{e.preventDefault();const form=e.currentTarget;const values=Object.fromEntries(new FormData(form));act(form.querySelector('button'),async()=>{const mine=epoch;try{await operation(values);}finally{if(mine===epoch)form.reset();else for(const input of form.querySelectorAll('input[type=password]'))input.value='';}});});}
  function options(target, rows, value, key, placeholder) {
    target.replaceChildren();const first=node('option',placeholder);first.value='';target.append(first);
    for(const row of rows){const option=node('option',row.name);option.value=row[key];target.append(option);}target.value=value;
  }
  function manager(){return ['owner','admin'].includes(teams.find(t=>t.team_id===teamId)?.role);}
  function showHub(){el('login').hidden=true;el('workspace').hidden=true;el('account-hub').hidden=false;el('hub-identity').textContent=session.account.display_name+' / '+(session.account.username || 'GitHub');}
  function renderTeams(){
    for(const id of ['hub-team','workspace-team'])options(el(id),teams,teamId,'team_id','选择团队');
    options(el('workspace-project'),projects,roomId,'room_id','选择项目');
    el('team-manager').hidden=!manager();el('password-section').hidden=!config.local_login_enabled || !session.account.username;
    el('account-switchers').hidden=!project.managed();
  }
  function renderProjects(){
    const box=el('hub-projects');box.replaceChildren();
    if(!projects.length)box.append(node('p',teamId?'当前没有获授权的项目。团队管理员可创建项目或授予访问。':'创建一个团队，或接受邀请后选择项目。','empty'));
    for(const p of projects){const card=node('article','','project-card');card.append(node('p','PROJECT / 共享工作现场','eyebrow'),node('h3',p.name),node('p',p.repository || '未声明仓库','muted'),btn('进入项目 ↗',()=>selectProject(p.room_id)));box.append(card);}
    const roles=teams.find(t=>t.team_id===teamId)?.role==='owner'?['member','admin','owner']:['member'];
    el('invite-role').replaceChildren();for(const role of roles){const o=node('option',{member:'成员',admin:'管理员',owner:'所有者'}[role]);o.value=role;el('invite-role').append(o);}
    el('invite-scopes').replaceChildren();for(const p of managed){const label=node('label',p.name,'scope-option'),input=document.createElement('input');input.type='checkbox';input.value=p.room_id;label.prepend(input);el('invite-scopes').append(label);}
  }
  function renderMembers(){
    const box=el('hub-members');box.replaceChildren();const role=teams.find(t=>t.team_id===teamId)?.role, owners=members.filter(m=>m.role==='owner').length;
    for(const m of members){
      const row=node('article','','account-member');row.append(node('h3',m.display_name),node('p',(m.username || 'GitHub')+' · '+{owner:'所有者',admin:'管理员',member:'成员'}[m.role],'muted'));
      const self=m.account_id===session.account.id,last=m.role==='owner'&&owners===1;
      const path=routeTeam()+'/members/'+encodeURIComponent(m.account_id);
      if(role==='owner'){
        const select=document.createElement('select');select.setAttribute('aria-label','设置 '+m.display_name+' 的团队角色');
        for(const r of ['owner','admin','member']){const o=node('option',{owner:'所有者',admin:'管理员',member:'成员'}[r]);o.value=r;o.disabled=last&&r!=='owner';select.append(o);}select.value=m.role;
        row.append(select,btn('保存角色',async()=>{await change(path+'/role',{role:select.value});}));
      }
      if(last)row.append(node('p','最后一位所有者必须保留','meta'));
      if(!last && (self || role==='owner' || (role==='admin'&&m.role==='member')))row.append(btn(self?'离开团队':'移出团队',async()=>{await change(path+'/remove',{});}));
      const canTarget=manager()&&(role==='owner'||m.role==='member'||self);
      if(canTarget){
        const panel=node('details'),summary=node('summary','项目访问与凭据管理');panel.append(summary);
        for(const p of managed){const line=node('div','','grant-line');line.append(node('span',p.name+(p.has_access?' · 你有访问权限':' · 仅管理信息')),btn('授予访问',async()=>{await change('/account/projects/'+encodeURIComponent(p.room_id)+'/members/'+encodeURIComponent(m.account_id)+'/grant',{});}),btn('撤销访问',async()=>{await change('/account/projects/'+encodeURIComponent(p.room_id)+'/members/'+encodeURIComponent(m.account_id)+'/remove',{});}));panel.append(line);}
        if(config.local_login_enabled && m.username && !self && m.role!=='owner' && (role==='owner'||m.role==='member')){
          const form=node('form'),label=node('label','为此成员重置密码'),input=document.createElement('input');input.type='password';input.required=true;input.minLength=12;input.autocomplete='new-password';label.append(input);const submit=node('button','重置密码');submit.type='submit';form.append(label,submit,node('p','仅限只属于当前团队的本地账号；服务会验证。','meta'));
          form.addEventListener('submit',e=>{e.preventDefault();const value=input.value;input.value='';act(submit,async()=>{await request(path+'/reset-password',{new_password:value});});});panel.append(form);
        }row.append(panel);
      }box.append(row);
    }
  }
  async function loadTeam(id) {
    invalidate();teamId=id;sessionStorage.setItem('crewmesh_selected_team',id);showHub();renderTeams();const mine=epoch;
    if(!id){renderProjects();return;}
    window.CrewmeshBilling?.load({teamId:id,role:teams.find(t=>t.team_id===id)?.role,
      isCurrent:()=>mine===epoch && !!session && teamId===id,
      request:(path,data)=>{if(mine!==epoch || !session || teamId!==id)return Promise.reject(stale());return request(path,data,{},true,60000);}});
    const base=routeTeam();projects=await request(base+'/projects');if(mine!==epoch)return;
    members=await request(base+'/members');if(mine!==epoch)return;
    managed=manager()?await request(base+'/managed-projects'):[];if(mine!==epoch)return;
    renderTeams();renderProjects();renderMembers();
  }
  async function reload(preferred=teamId) {
    if(!session)return;const mine=epoch;const rows=await request('/account/teams');if(mine!==epoch)return;teams=rows;
    await loadTeam(teams.some(t=>t.team_id===preferred)?preferred:teams[0]?.team_id || '');
  }
  async function change(path,data){const mine=epoch;await request(path,data);if(mine===epoch)await reload();}
  async function selectProject(id){
    if(!session || !projects.some(p=>p.room_id===id))return;
    const selectedTeam=teamId, available=projects;invalidate();showHub();const mine=epoch;
    const credential=await request('/account/projects/'+encodeURIComponent(id)+'/select',{});if(mine!==epoch || selectedTeam!==teamId)return;
    projects=available;roomId=id;sessionStorage.setItem('crewmesh_selected_project',id);project.enter(credential.web_token);
    el('account-hub').hidden=true;el('account-switchers').hidden=false;el('logout').textContent='返回团队与项目';renderTeams();
  }
  async function home(){
    invalidate();if(!session)return;showHub();
    try{await reload();}catch(error){if(session && error.message!=='访问已切换')el('hub-error').textContent=error.message;}
  }
  async function denied(){invalidate();showHub();try{await request('/account/session');await reload();el('hub-error').textContent='项目访问已失效，请重新选择获授权的项目。';}catch(error){if(error.status===401)loggedOut();else el('hub-error').textContent=error.message;}}
  async function login(path,data,headers={}){
    loggedOut();const mine=epoch;const info=await request(path,data,headers);if(mine!==epoch)return;session=info;el('legacy-entry').open=false;await reload();
  }
  bind('account-login',data=>login('/account/login',data));
  bind('bootstrap-form',data=>{const secret=data.bootstrap_secret;delete data.bootstrap_secret;if(!data.display_name)delete data.display_name;return login('/account/bootstrap',data,{'X-Crewmesh-Bootstrap':secret});});
  bind('register-form',data=>{if(!data.display_name)delete data.display_name;return login('/account/invites/accept',data);});
  bind('team-form',async data=>{const mine=epoch,result=await request('/account/teams',data);if(mine===epoch)await reload(result.team_id);});
  bind('project-form',async data=>{await change(routeTeam()+'/projects',data);});
  bind('accept-form',async data=>{const mine=epoch,result=await request('/account/invites/accept',{invite_token:data.invite_token});if(mine===epoch)await reload(result.team_id);});
  bind('claim-form',async data=>{await change(routeTeam()+'/claim',data);});
  bind('team-invite-form',async data=>{const mine=epoch;data.project_ids=Array.from(el('invite-scopes').querySelectorAll('input:checked')).map(n=>n.value);const invite=await request(routeTeam()+'/invites',data);if(mine===epoch)project.private('保存团队邀请令牌',invite);});
  bind('password-form',async data=>{const mine=epoch;await request('/account/password',data);if(mine!==epoch)return;loggedOut();el('account-error').textContent='密码已修改，请重新登录。';});
  el('account-logout').addEventListener('click',()=>{busy=false;return act(el('account-logout'),async()=>{
    const csrf=session?.csrf_token;invalidate();el('account-hub').hidden=true;el('login').hidden=true;
    try{await request('/account/logout',{},csrf?{'X-Crewmesh-CSRF':csrf}:{});loggedOut();}
    catch(error){if(session){showHub();el('hub-error').textContent='退出未完成：'+error.message+'。请重试退出。';}throw error;}
  });});
  for(const id of ['hub-team','workspace-team'])el(id).addEventListener('change',()=>{const value=el(id).value;act(el(id),()=>loadTeam(value));});
  el('workspace-project').addEventListener('change',()=>{const value=el('workspace-project').value;act(el('workspace-project'),()=>selectProject(value));});
  el('account-settings').addEventListener('click',()=>act(el('account-settings'),home));
  el('hub-refresh').addEventListener('click',()=>act(el('hub-refresh'),reload));
  async function start(){
    const storedTeam=sessionStorage.getItem('crewmesh_selected_team');const storedProject=sessionStorage.getItem('crewmesh_selected_project');const wasManaged=sessionStorage.getItem('crewmesh_account_project');
    if(wasManaged)project.clear();const mine=epoch;
    config=await request('/account/config',undefined,{},false);if(mine!==epoch)return;
    el('account-mode').textContent=config.local_login_enabled?'本地部署 · 使用本机服务的账号登录':config.github_oauth_enabled?'云端部署 · 使用 GitHub 账号登录':'云端部署尚未配置 GitHub 登录，请联系部署管理员。';
    el('account-login').hidden=!config.local_login_enabled;el('account-bootstrap').hidden=!config.bootstrap_enabled;el('account-register').hidden=!config.local_login_enabled;el('github-login').hidden=!config.github_oauth_enabled;
    for(const id of ['tab-create','tab-join','form-create','form-join'])el(id).hidden=!config.local_login_enabled;
    if(!config.local_login_enabled)el('tab-restore').click();
    let info;
    try{info=await request('/account/session',undefined,{},false);}
    catch(error){if(mine!==epoch)return;if(error.status===401){if(wasManaged)loggedOut();return;}throw error;}
    if(mine!==epoch)return;session=info;await reload(storedTeam);
    if(wasManaged&&storedProject&&!['#billing','#billing-return'].includes(window.location?.hash)&&projects.some(p=>p.room_id===storedProject))await selectProject(storedProject);
  }
  window.CrewmeshAccounts={home,denied};
  el('account-retry').addEventListener('click',()=>act(el('account-retry'),start));
  act(el('account-retry'),start);
})();

