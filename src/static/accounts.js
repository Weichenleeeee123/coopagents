/* Account cookies stay HttpOnly. Only scoped project credentials use the existing tab storage. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const project = window.CoopagentsProject;
  let epoch = 0, session = null, config = null, teams = [], projects = [], managed = [], members = [], teamId = '', roomId = '', busy = false, operationId = 0;
  let hubView = 'projects';
  const hubViews = {
    projects:['YOUR PROJECTS / 共同的工作现场','我的项目','选择一个项目，继续团队的共同工作。'],
    members:['PEOPLE / 团队协作','团队成员','看清每位成员的角色与项目访问。'],
    settings:['TEAM SETTINGS / 空间与权限','团队设置','建立团队、邀请协作者，管理自己的账号。'],
    billing:['TEAM CAPACITY / PLAN & BILLING','Plan & billing','查看当前团队的套餐、用量与订阅状态。']
  };
  function setHubView(view) {
    if(!hubViews[view])return;
    hubView=view;
    for(const key of Object.keys(hubViews)){
      el('hub-view-'+key).hidden=key!==view;
      el('hub-nav-'+key).setAttribute('aria-current',key===view?'page':'false');
    }
    [el('hub-kicker').textContent,el('hub-title').textContent,el('hub-description').textContent]=hubViews[view];
    el('billing-empty').hidden=!!teamId;document.title=hubViews[view][1]+' · Coopagents';
  }
  for(const key of Object.keys(hubViews))el('hub-nav-'+key).addEventListener('click',()=>setHubView(key));
  const pending = new Set();
  const stale = () => new Error('访问已切换');
  const node = (tag, value, cls) => { const n=document.createElement(tag); n.textContent=value == null?'':String(value); if(cls)n.className=cls;return n; };
  const btn = (label, action, cls) => {const n=node('button',label,cls);n.type='button';n.addEventListener('click',()=>act(n,action));return n;};
  const routeTeam = () => '/account/teams/'+encodeURIComponent(teamId);
  function invitationState(){window.CoopagentsInvitations?.update({session,config,request,accept:acceptInvitation,refresh:start});}
  async function acceptInvitation(token,isCurrent=()=>true){
    const mine=epoch,result=await request('/account/invites/accept',{invite_token:token});
    if(mine!==epoch || !isCurrent())throw stale();await reload(result.team_id,isCurrent);
    if(!isCurrent())throw stale();
    if(result.project_ids?.length===1)await selectProject(result.project_ids[0],isCurrent);
  }
  async function createInvitation(projectIds,data={role:'member'}){
    const mine=epoch,invite=await request(routeTeam()+'/invites',{...data,project_ids:projectIds});
    if(mine===epoch)project.private('复制团队邀请链接',{invite_url:window.CoopagentsInvitations.link(invite),expires_at:invite.expires_at});
  }
  function invalidate() {
    window.CoopagentsBilling?.clear();el('hub-loading').hidden=true;
    epoch++; for(const c of pending)c.abort(); pending.clear(); project.clear();
    el('workspace').hidden=true;el('account-switchers').hidden=true;
    ['hub-projects','hub-members','invite-scopes'].forEach(id=>el(id).replaceChildren());
    el('hub-identity').textContent='';el('hub-error').textContent='';el('workspace-project').replaceChildren();
    for(const input of document.querySelectorAll('input[type=password]'))input.value='';projects=[];managed=[];members=[];roomId='';
    sessionStorage.removeItem('coopagents_selected_project');
  }
  function loggedOut() {
    invalidate();session=null;teams=[];teamId='';hubView='projects';document.title='Coopagents · 同频';
    sessionStorage.removeItem('coopagents_account_project');sessionStorage.removeItem('coopagents_selected_team');
    el('account-hub').hidden=true;el('login').hidden=false;
    ['account-login','bootstrap-form','register-form','accept-form','password-form','claim-form','project-form','team-form','team-invite-form'].forEach(id=>el(id).reset());
    el('hub-team').replaceChildren();el('workspace-team').replaceChildren();el('workspace-project').replaceChildren();
    invitationState();
  }
  async function request(path, data, headers = {}, check = true, timeout = 10000) {
    const mine=epoch, c=new AbortController();pending.add(c);
    const timer=setTimeout(()=>c.abort(),timeout);
    try {
      const h={...headers};if(data!==undefined){h['Content-Type']='application/json';if(session)h['X-Coopagents-CSRF']=session.csrf_token;}
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
  function showHub(){el('login').hidden=true;el('workspace').hidden=true;el('account-hub').hidden=false;el('hub-identity').textContent=session.account.display_name+' / '+(session.account.username || 'GitHub');invitationState();}
  function renderTeams(){
    for(const id of ['hub-team','workspace-team'])options(el(id),teams,teamId,'team_id','选择团队');
    options(el('workspace-project'),projects,roomId,'room_id','选择项目');
    const currentProject=projects.find(p=>p.room_id===roomId);
    el('workspace-switcher-current').textContent=currentProject?.name||'选择项目';
    el('workspace-switcher-team').textContent=teams.find(t=>t.team_id===teamId)?.name||'';
    project.updateSwitcher?.({team:teams.find(t=>t.team_id===teamId),current_room_id:roomId,projects:projects.map(p=>({room_id:p.room_id,team_id:teamId,team_name:teams.find(t=>t.team_id===teamId)?.name||'',name:p.name,repository:p.repository||''}))});
    el('team-manager').hidden=!manager();el('project-manager').hidden=!manager();el('password-section').hidden=!config.local_login_enabled || !session.account.username;
    el('account-switchers').hidden=!project.managed();
  }
  function renderProjectSwitcher(data){
    const list=el('workspace-project-list');list.replaceChildren();
    const current=projects.find(p=>p.room_id===roomId);
    el('workspace-switcher-current').textContent=current?.name||'选择项目';
    el('workspace-switcher-team').textContent=teams.find(t=>t.team_id===teamId)?.name||'';
    el('workspace-team-label').textContent=teams.find(t=>t.team_id===teamId)?.name||'当前团队';
    let lastTeam='';
    for(const p of data?.projects||projects){
      if(p.team_name&&p.team_name!==lastTeam){lastTeam=p.team_name;list.append(node('p',lastTeam,'workspace-project-group'));}
      const row=btn('',()=>{},'workspace-project-option');
      row.setAttribute('data-project-id',p.room_id);
      row.setAttribute('role','option');row.setAttribute('aria-selected',String(p.room_id===roomId));
      const mark=node('span',(p.name||'P').slice(0,1),'project-switch-mark');
      const detail=node('span','','workspace-project-detail');detail.append(node('strong',p.name),node('small',p.repository||'未声明仓库','meta'));
      row.append(mark,detail,p.room_id===roomId?node('span','当前','project-current'):node('span','›','project-arrow'));
      list.append(row);
    }
    if(!projects.length)list.append(node('p','当前团队没有已授权项目。','empty'));
  }
  async function openProjectSwitcher(){
    if(!session)return;
    const data=await switcherProjects();
    project.updateSwitcher?.(data);
    const dialog=el('workspace-project-dialog');
    if(dialog.showModal)dialog.showModal();
  }
  function renderProjects(){
    const box=el('hub-projects');box.replaceChildren();
    if(!projects.length)box.append(node('p',teamId?'当前没有获授权的项目。团队管理员可创建项目或授予访问。':'创建一个团队，或接受邀请后选择项目。','empty'));
    for(const p of projects){const card=node('article','','project-card');card.append(node('p','PROJECT / 共享工作现场','eyebrow'),node('h3',p.name),node('p',p.repository || '未声明仓库','muted'),btn('进入项目 ↗',()=>selectProject(p.room_id)));if(manager())card.append(btn('邀请队友 ↗',()=>createInvitation([p.room_id])));box.append(card);}
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
      if(!last && (self || role==='owner' || (role==='admin'&&m.role==='member')))row.append(btn(self?'离开团队':'移出团队',async()=>{await change(path+'/remove',{});},'danger'));
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
  function loadBilling(mine,id) {
    window.CoopagentsBilling?.load({teamId:id,role:teams.find(t=>t.team_id===id)?.role,
      isCurrent:()=>mine===epoch && !!session && teamId===id,
      request:(path,data)=>{if(mine!==epoch || !session || teamId!==id)return Promise.reject(stale());return request(path,data,{},true,60000);}});
  }
  async function loadTeam(id,isCurrent=()=>true) {
    if(!isCurrent())throw stale();
    const nextView=id===teamId?hubView:'projects';
    invalidate();teamId=id;sessionStorage.setItem('coopagents_selected_team',id);showHub();renderTeams();setHubView(nextView);const mine=epoch;
    el('hub-loading').hidden=!id;el('hub-projects').setAttribute('aria-busy',String(!!id));
    if(!id){renderProjects();return;}
    try {
    loadBilling(mine,id);
    const base=routeTeam();const loadedProjects=await request(base+'/projects');if(mine!==epoch || !isCurrent())return;projects=loadedProjects;
    const loadedMembers=await request(base+'/members');if(mine!==epoch || !isCurrent())return;members=loadedMembers;
    const loadedManaged=manager()?await request(base+'/managed-projects'):[];if(mine!==epoch || !isCurrent())return;managed=loadedManaged;
    renderTeams();renderProjects();renderMembers();
    } finally {if(mine===epoch){el('hub-loading').hidden=true;el('hub-projects').setAttribute('aria-busy','false');}}
  }
  async function reload(preferred=teamId,isCurrent=()=>true) {
    if(!session || !isCurrent())return;const mine=epoch;const rows=await request('/account/teams');if(mine!==epoch || !isCurrent())return;teams=rows;
    await loadTeam(teams.some(t=>t.team_id===preferred)?preferred:teams[0]?.team_id || '',isCurrent);
  }
  async function change(path,data){const mine=epoch;await request(path,data);if(mine===epoch)await reload();}
  async function selectProject(id,isCurrent=()=>true,options={}){
    if(!session || !isCurrent() || !projects.some(p=>p.room_id===id))return;
    const selectedTeam=teamId, available=projects;invalidate();showHub();const mine=epoch;
    const credential=await request('/account/projects/'+encodeURIComponent(id)+'/select',{});if(mine!==epoch || selectedTeam!==teamId || !isCurrent())return;
    projects=available;roomId=id;sessionStorage.setItem('coopagents_selected_project',id);project.enter(credential.web_token,options);
    el('account-hub').hidden=true;el('account-switchers').hidden=false;el('logout').textContent='返回团队与项目';renderTeams();
  }
  async function switcherProjects(){
    if(!session)throw new Error('请先登录账号');
    const mine=epoch,accessible=[];
    for(const team of teams){
      const rows=team.team_id===teamId?projects:await request('/account/teams/'+encodeURIComponent(team.team_id)+'/projects');
      if(mine!==epoch)throw stale();
      accessible.push(...rows.map(p=>({room_id:p.room_id,team_id:team.team_id,team_name:team.name,name:p.name,repository:p.repository||''})));
    }
    return {team_id:teamId,teams:teams.map(t=>({team_id:t.team_id,name:t.name})),projects:accessible};
  }
  async function switchProject(id){
    if(!session)return;
    if(projects.some(p=>p.room_id===id))return selectProject(id);
    const mine=epoch;let target='';
    for(const team of teams){const rows=team.team_id===teamId?projects:await request('/account/teams/'+encodeURIComponent(team.team_id)+'/projects');if(mine!==epoch)throw stale();if(rows.some(p=>p.room_id===id)){target=team.team_id;break;}}
    if(!target)throw new Error('项目不存在或当前账号没有访问权限');
    await loadTeam(target);if(session&&teamId===target&&projects.some(p=>p.room_id===id))await selectProject(id);
  }
  async function home(){
    invalidate();if(!session)return;setHubView('projects');showHub();
    try{await reload();}catch(error){if(session && error.message!=='访问已切换')el('hub-error').textContent=error.message;}
  }
  async function denied(){invalidate();showHub();try{await request('/account/session');await reload();el('hub-error').textContent='项目访问已失效，请重新选择获授权的项目。';}catch(error){if(error.status===401)loggedOut();else el('hub-error').textContent=error.message;}}
  async function login(path,data,headers={},isCurrent=()=>true){
    loggedOut();const mine=epoch;const info=await request(path,data,headers);if(mine!==epoch || !isCurrent())return;session=info;el('legacy-entry').open=false;await reload(info.team_id,isCurrent);
    if(path==='/account/invites/accept' && isCurrent()){if(info.project_ids?.length===1)await selectProject(info.project_ids[0],isCurrent);if(isCurrent())window.CoopagentsInvitations?.clear();}
  }
  bind('account-login',data=>login('/account/login',data));
  bind('bootstrap-form',data=>{const secret=data.bootstrap_secret;delete data.bootstrap_secret;if(!data.display_name)delete data.display_name;return login('/account/bootstrap',data,{'X-Coopagents-Bootstrap':secret});});
  bind('register-form',data=>{if(!data.display_name)delete data.display_name;return login('/account/invites/accept',window.CoopagentsInvitations?.registration(data)||data,{},window.CoopagentsInvitations?.guard()||(()=>true));});
  bind('team-form',async data=>{const mine=epoch,result=await request('/account/teams',data);if(mine===epoch)await reload(result.team_id);});
  bind('project-form',async data=>{await change(routeTeam()+'/projects',data);});
  bind('accept-form',async data=>{await acceptInvitation(data.invite_token);});
  bind('claim-form',async data=>{await change(routeTeam()+'/claim',data);});
  bind('team-invite-form',async data=>{await createInvitation(Array.from(el('invite-scopes').querySelectorAll('input:checked')).map(n=>n.value),data);});
  bind('password-form',async data=>{const mine=epoch;await request('/account/password',data);if(mine!==epoch)return;loggedOut();el('account-error').textContent='密码已修改，请重新登录。';});
  el('account-logout').addEventListener('click',()=>{busy=false;return act(el('account-logout'),async()=>{
    const csrf=session?.csrf_token;invalidate();el('account-hub').hidden=true;el('login').hidden=true;
    try{await request('/account/logout',{},csrf?{'X-Coopagents-CSRF':csrf}:{});loggedOut();}
    catch(error){if(session){showHub();el('hub-error').textContent='退出未完成：'+error.message+'。请重试退出。';}throw error;}
  });});
  for(const id of ['hub-team','workspace-team'])el(id).addEventListener('change',()=>{const value=el(id).value;busy=false;act(el(id),()=>loadTeam(value));});
  el('workspace-team').addEventListener('change',()=>el('workspace-project-dialog').close?.());
  el('workspace-project').addEventListener('change',()=>{const value=el('workspace-project').value;busy=false;act(el('workspace-project'),()=>selectProject(value));});
  // The project picker is presented by the workbench shell; this module owns the authorized data and switch operation.
  el('close-project-switcher').addEventListener('click',()=>el('workspace-project-dialog').close?.());
  el('account-settings').addEventListener('click',()=>act(el('account-settings'),home));
  el('hub-refresh').addEventListener('click',()=>act(el('hub-refresh'),reload));
  async function start(){
    const storedTeam=sessionStorage.getItem('coopagents_selected_team');const storedProject=sessionStorage.getItem('coopagents_selected_project');const wasManaged=sessionStorage.getItem('coopagents_account_project');
    if(wasManaged)project.clear();const mine=epoch;
    config=await request('/account/config',undefined,{},false);if(mine!==epoch)return;
    el('account-mode').textContent=config.local_login_enabled?'本地部署 · 使用本机服务的账号登录':config.github_oauth_enabled?'云端部署 · 使用 GitHub 账号登录':'云端部署尚未配置 GitHub 登录，请联系部署管理员。';
    el('account-login').hidden=!config.local_login_enabled;el('account-bootstrap').hidden=!config.bootstrap_enabled;el('account-register').hidden=!config.local_login_enabled;el('github-login').hidden=!config.github_oauth_enabled;
    invitationState();
    for(const id of ['tab-create','tab-join','form-create','form-join'])el(id).hidden=!config.local_login_enabled;
    if(!config.local_login_enabled)el('tab-restore').click();
    let info;
    try{info=await request('/account/session',undefined,{},false);}
    catch(error){if(mine!==epoch)return;if(error.status===401){if(wasManaged)loggedOut();return;}throw error;}
    if(mine!==epoch)return;session=info;await reload(storedTeam);
    if(['#billing','#billing-return'].includes(window.location?.hash))setHubView('billing');
    if(wasManaged&&storedProject&&!window.CoopagentsInvitations?.pending()&&!['#billing','#billing-return'].includes(window.location?.hash)&&projects.some(p=>p.room_id===storedProject))await selectProject(storedProject,()=>true,{restoreView:true});
  }
  window.addEventListener('hashchange',async()=>{
    const hash=window.location.hash,account=session,selectedTeam=teamId;
    if(!account || !['#billing','#billing-return'].includes(hash))return;
    if(el('account-hub').hidden)await home();
    if(session!==account || selectedTeam!==teamId || window.location.hash!==hash || el('account-hub').hidden)return;
    setHubView('billing');loadBilling(epoch,teamId);
  });
  window.CoopagentsAccounts={home,denied,switcherProjects,selectProject:switchProject};
  el('account-retry').addEventListener('click',()=>act(el('account-retry'),start));
  act(el('account-retry'),start);
})();

