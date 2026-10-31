'use strict';
const $ = id => document.getElementById(id);
let token = sessionStorage.getItem('coopagents_web_token') || '';
let generation = 0, snapshot = null, pollTimer = null, syncing = false, lastSuccess = null;
let accountManaged = false, realtime=null, syncDirty=false;
const boardUI = () => typeof window!=='undefined' ? window.CoopagentsBoard : null;
const assetsUI = () => typeof window!=='undefined' ? window.CoopagentsProjectAssets : null;
function startRealtime(){realtime?.close();realtime=null;const epoch=generation;if(typeof window==='undefined'||!window.CoopagentsRealtime||!token)return;realtime=window.CoopagentsRealtime.connect({token,refresh:()=>epoch===generation?sync():Promise.resolve(),status:value=>{if(epoch===generation&&$('transport-status'))$('transport-status').textContent=value==='online'?'实时在线':'实时中断 · 轮询恢复';}});}
const projectRequests = new Set();
const gitUI = () => typeof window!=='undefined' ? window.CoopagentsGit : null;
const dependencyUI = () => typeof window!=='undefined' ? window.CoopagentsDependencies : null;
const lifecycleUI = () => typeof window!=='undefined' ? window.CoopagentsTaskLifecycle : null;
const collaborationUI = () => typeof window!=='undefined' ? window.CoopagentsCollaboration : null;
function gitContext(){const epoch=generation;return {api,sync,me:snapshot.me,memberName,openTask:openTaskDetail,origin:location.origin,isCurrent:()=>epoch===generation};}
function assetContext(){const epoch=generation;return {api,roomId:snapshot.me.room_id,memberName,openDetail:openContentDetail,isCurrent:()=>epoch===generation};}
const states = {cancelled:'已取消',open:'待认领', claimed:'已认领', working:'推进中', blocked:'受阻', local_done:'本地完成', pushed:'已推送', pr_open:'PR 已打开', merged:'已合并', approved:'已批准', rejected:'已拒绝'};
const views = {overview:['01 / OVERVIEW','概览','项目状况与需要留意的事项。'],tasks:['02 / TASKS','任务','谁在做什么，当前进展如何。'],requests:['03 / COLLABORATION','协作','问题、答复与处理状态各自独立。'],contracts:['04 / SHARED CONTEXT','共享上下文','约定、共享文件与可引用记录。'],delivery:['05 / DELIVERY','交付','从 Git 交付对象查找关联任务。'],members:['06 / MEMBERS','成员与 agent','队友、工具与能力状态。'],repository:['07 / PROJECT SETTINGS','项目设置','连接与项目级配置。'],activity:['项目活动','项目活动','查看有来源的结构化项目事件。']};
const text = (tag, value, cls) => { const e = document.createElement(tag); e.textContent = value == null ? '' : String(value); if(cls) e.className = cls; return e; };
const add = (parent, ...children) => { children.forEach(c => parent.append(c)); return parent; };
const button = (label, action, cls) => { const b = text('button', label, cls); b.type = 'button'; b.addEventListener('click', action); return b; };
const date = value => { if(!value) return '—'; const d = new Date(value); return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}); };
const memberName = id => snapshot?.members.find(m => m.member_id === id)?.display_name || (id ? '成员 ' + id : '待分派');
const taskName = id => snapshot?.tasks.find(t => t.id === id)?.title || '任务 #' + id;
const empty = (target, message) => target.append(text('p',message,'empty'));
const badge = value => text('span',states[value] || value,'badge'+(Object.hasOwn(states,value)?' badge-'+value:''));
const detail = (title, children) => add(document.createElement('details'),text('summary',title),...children);
// Navigation state is shared by pointer and keyboard actions and reset on project changes.
function setWorkspaceNavigation(open){
  $('workspace').setAttribute?.('data-navigation-open',String(open));
  $('workspace-mobile-menu')?.setAttribute?.('aria-expanded',String(open));
}
$('workspace-mobile-menu')?.addEventListener('click',()=>{
  const expanded=$('workspace-mobile-menu').getAttribute?.('aria-expanded')??$('workspace-mobile-menu').attributes?.['aria-expanded'];
  setWorkspaceNavigation(expanded!=='true');
});
$('workspace-sidebar')?.addEventListener('keydown',event=>{if(event.key==='Escape'){setWorkspaceNavigation(false);$('workspace-mobile-menu').focus();}});
$('workspace-crumb-project')?.addEventListener('click',()=>setView('overview'));
function setHubNavigation(open){$('account-hub').setAttribute?.('data-navigation-open',String(open));$('hub-mobile-menu')?.setAttribute?.('aria-expanded',String(open));}
$('hub-mobile-menu')?.addEventListener('click',()=>{
  const expanded=$('account-hub').getAttribute?.('data-navigation-open')??$('account-hub').attributes?.['data-navigation-open'];setHubNavigation(expanded!=='true');
});
$('hub-sidebar')?.addEventListener('keydown',event=>{if(event.key==='Escape'){setHubNavigation(false);$('hub-mobile-menu').focus();}});
document.querySelectorAll('#account-hub .sidebar nav button').forEach(button=>button.addEventListener('click',()=>setHubNavigation(false)));

function setView(view, options={}) {
  if(!views[view])return;
  setWorkspaceNavigation(false);
  if($('new-task'))$('new-task').hidden=view!=='tasks';
  if($('workspace-crumb-page'))$('workspace-crumb-page').textContent=views[view][1];
  for(const key of Object.keys(views)) $('view-'+key).hidden = key !== view;
  document.querySelectorAll('[data-view]').forEach(b => { if(b.dataset.view === view) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current'); });
  [$('view-kicker').textContent,$('view-title').textContent,$('view-description').textContent] = views[view];
  if(!$('workspace').hidden)document.title=views[view][1]+' · Coopagents';
  if(options.push!==false&&location.hash!=='#workspace='+view)history.pushState({workspaceView:view},'', '#workspace='+view);
  else if(options.replace&&location.hash!=='#workspace='+view)history.replaceState({workspaceView:view},'', '#workspace='+view);
}
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click',() => setView(b.dataset.view)));
const routeView=()=>/^#workspace=(overview|tasks|requests|contracts|delivery|members|repository|activity)$/.exec(location.hash)?.[1];
if(typeof window!=='undefined')window.addEventListener('popstate',()=>{const view=routeView();if(view)setView(view,{push:false});});
const tabs = Array.from(document.querySelectorAll('[data-entry]'));
function entryTab(b) { if(b.hidden)return;tabs.forEach(t => { const active=t===b; t.setAttribute('aria-selected',String(active)); t.tabIndex=active?0:-1; $('form-'+t.dataset.entry).hidden=!active; }); }
tabs.forEach((b,i) => { b.tabIndex=i? -1:0; b.addEventListener('click',() => entryTab(b)); b.addEventListener('keydown',e => { if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){ e.preventDefault(); const visible=tabs.filter(t=>!t.hidden),current=visible.indexOf(b); const next=e.key==='Home'?0:e.key==='End'?visible.length-1:(current+(e.key==='ArrowRight'?1:visible.length-1))%visible.length; entryTab(visible[next]); visible[next].focus(); } }); });
async function api(path, data, authenticated = true, extraHeaders = {}, responseMode='json') {
  const epoch=generation, credential=token, controller=new AbortController();
  projectRequests.add(controller);
  const timeout=setTimeout(() => controller.abort(),path==='/api/assets'&&data!==undefined?120000:10000);
  try {
    const headers={...extraHeaders},formData=typeof FormData!=='undefined'&&data instanceof FormData; if(authenticated) headers.Authorization='Bearer '+credential;
    if(data!==undefined&&!formData) headers['Content-Type']='application/json';
    const response=await fetch(path,{method:data===undefined?'GET':'POST',headers,body:data===undefined?undefined:formData?data:JSON.stringify(data),signal:controller.signal,cache:'no-store'});
    if(epoch!==generation) throw new Error('访问已切换');
    let result; try { result=responseMode==='blob'&&response.ok?await response.blob():await response.json(); } catch { throw new Error('服务返回了无法读取的响应'); }
    if(epoch!==generation) throw new Error('访问已切换');
    if(response.status===401){ if(authenticated){if(accountManaged && typeof window!=='undefined')window.CoopagentsAccounts.denied();else logout('网页凭据已失效，请恢复访问或重新加入。');} throw new Error(authenticated?'网页凭据已失效':(result.message || '邀请或凭据不可用')); }
    if(!response.ok) throw new Error(result.message || '操作未完成');
    return result;
  } catch(error) { if(error.name==='AbortError') throw new Error('连接超时，请重试'); throw error; }
  finally { clearTimeout(timeout); projectRequests.delete(controller); }
}
function logout(message='') {
  realtime?.close();realtime=null;syncDirty=false;generation++; token=''; snapshot=null; sessionStorage.removeItem('coopagents_web_token'); clearTimeout(pollTimer);
  projectRequests.forEach(controller=>controller.abort()); projectRequests.clear(); syncing=false;
  gitUI()?.clear(); $('git-connection')?.replaceChildren(); $('git-overlaps')?.replaceChildren();
  assetsUI()?.clear($('project-assets'));
  collaborationUI()?.clear(); lifecycleUI()?.clear(); dependencyUI()?.clear();
  renderSignature='';taskLayout='board';settingsTab='repository';document.querySelectorAll('[data-task-layout]').forEach(tab=>{if(tab.dataset.taskLayout==='board')tab.setAttribute('aria-current','page');else tab.removeAttribute('aria-current');});if($('request-search'))$('request-search').value='';if($('request-filter'))$('request-filter').value='all';setWorkspaceNavigation(false);closePrivate(); closeTaskDetail(); $('task-search').value=''; $('task-owner').value=''; if($('task-status'))$('task-status').value='active'; $('workspace').hidden=true; $('login').hidden=false; $('login-error').textContent=message;document.title='Coopagents · 同频';
  $('board-empty').hidden=true;
  if(typeof window!=='undefined'){
    window.CoopagentsSharedContext?.render($('shared-context'),null);
    window.CoopagentsCapabilities?.render($('capability-discovery'),null);
    window.CoopagentsDelivery?.render($('delivery-traceability'),null);
    window.CoopagentsDeliveryGraph?.render($('delivery-graph'),null);
  }
  ['capability-discovery','tasks','requests','contracts','overlaps','summary','board-summary'].forEach(id => $(id).replaceChildren());
  ['room-name','room-repository','identity','network-error','action-error','board-count'].forEach(id=>$(id).textContent='');
  $('form-restore').reset(); $('form-join').reset(); $('form-create').reset(); $('task-form').reset();
}
function enter(credential) { generation++; renderSignature=''; token=credential; sessionStorage.setItem('coopagents_web_token',credential); $('login').hidden=true; $('workspace').hidden=false;document.title=$('view-title').textContent+' · Coopagents'; $('action-error').textContent=''; $('sync-time').textContent='正在同步…'; $('network-error').hidden=true; lastSuccess=null; clearTimeout(pollTimer); startRealtime(); sync(); }
for(const name of ['create','join','restore']) $('form-'+name).addEventListener('submit',async e => {
  e.preventDefault(); const form=e.currentTarget, b=form.querySelector('button[type=submit]'); b.disabled=true; $('login-error').textContent='';
  const epoch=generation;
  try { const data=Object.fromEntries(new FormData(form));
    const bootstrap=data.bootstrap_secret; delete data.bootstrap_secret;
    if(name==='restore'){ const credential=data.web_token.trim(); generation++; const restoreEpoch=generation; token=credential; await api('/api/snapshot'); if(restoreEpoch!==generation)return; enter(credential); }
    else { const result=await api(name==='create'?'/api/rooms':'/api/join',data,false,name==='create'&&bootstrap?{'X-Coopagents-Bootstrap':bootstrap}:{}); if(epoch!==generation)return; enter(result.web_token); showPrivate('保存个人接入凭据',result); }
    form.reset();
  } catch(error) { if(!$('login').hidden) $('login-error').textContent=error.message; } finally { b.disabled=false; }
});
async function sync() {
  if(!token)return; if(syncing){syncDirty=true;return;}
  syncing=true; const epoch=generation;
  try { const result=await api('/api/snapshot'); if(epoch!==generation) return; snapshot=result; lastSuccess=new Date(); $('network-error').hidden=true; $('sync-time').textContent='最后同步 '+date(lastSuccess); render(); }
  catch(error){ if(epoch===generation && token){ $('network-error').hidden=false; $('network-error').textContent='连接中断：'+error.message+'。保留上次数据'+(lastSuccess?'（最后成功 '+date(lastSuccess)+'）':'')+'，可点击刷新重试。'; } }
  finally { if(epoch===generation){syncing=false; if(token){ clearTimeout(pollTimer); const followup=syncDirty;syncDirty=false;pollTimer=setTimeout(sync,followup?0:5000); }} }
}
// Keep forms, selection and keyboard focus intact when the snapshot is unchanged.
let renderSignature='';
let renderedRoom='';
function render() {
  const signature=JSON.stringify({...snapshot,server_time:null}); if(signature===renderSignature) return; renderSignature=signature;
  // Defer dynamic lists while a user edits a receiver or interacts with a record.
  if((['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName) && ['requests','contracts','tasks','task-detail','git-connection','collaboration-status','shared-context','project-assets','overview-recent-activity','delivery-graph','capability-discovery'].some(id => $(id)?.contains(document.activeElement))) || !window.getSelection().isCollapsed){ renderSignature=''; return; }
  const active=document.activeElement, activeRecord=active?.closest('.record,.task-card');
  const focus=activeRecord ? {record:activeRecord.id,tag:active.tagName,label:active.textContent} : null;
  const expanded=Array.from(document.querySelectorAll('.record details[open]')).map(d=>({record:d.closest('.record').id,label:d.querySelector('summary').textContent}));
  $('workspace-crumb-project').textContent=snapshot.room.name;
  $('workspace-crumb-team').textContent=$('workspace-switcher-team').textContent||'项目空间';
  $('room-name').textContent=snapshot.room.name; $('room-repository').textContent=snapshot.git?.binding?.repository || snapshot.room.repository || '未声明仓库'; $('identity').textContent=snapshot.me.display_name+' / '+(snapshot.me.role==='owner'?'项目创建者':'项目成员'); $('invite-button').hidden=accountManaged || snapshot.me.role!=='owner';
  if($('workspace-page-project'))$('workspace-page-project').textContent=snapshot.room.name;
  const projectName=$('workspace-project-name');if(projectName)projectName.textContent=snapshot.room.name;
  if(renderedRoom&&renderedRoom!==snapshot.me.room_id){contextTab='agreements';taskLayout='board';settingsTab='repository';}renderedRoom=snapshot.me.room_id;
  renderOverview(); renderTasks(); renderRequests(); renderContracts();renderContractsTabs();
  renderCapabilities(); renderDeliveryTraceability();
  gitUI()?.renderPanel($('git-connection'),snapshot,gitContext());
  window.CoopagentsProjectActivity?.render($('overview-recent-activity'),snapshot.activity,{openTask:openTaskDetail,compact:true,maxItems:4,viewAll:()=>setView('activity')});
  const activityLink=$('overview-recent-activity-link');if(activityLink)activityLink.onclick=()=>setView('activity');
  window.CoopagentsProjectActivity?.render($('project-activity'),snapshot.activity,{openTask:openTaskDetail});
  collaborationUI()?.renderPanel($('collaboration-status'),snapshot,gitContext());renderSettingsTabs();
  expanded.forEach(item=>{ const record=$(item.record); record?.querySelectorAll('details').forEach(d=>{if(d.querySelector('summary').textContent===item.label)d.open=true;}); });
  if(focus)restoreRecordFocus(focus);
}
function restoreRecordFocus(focus){
  const record=$(focus.record);
  const replacement=record?.tagName===focus.tag&&record.textContent===focus.label?record:Array.from(record?.querySelectorAll(focus.tag)||[]).find(e=>e.textContent===focus.label);
  if(replacement)replacement.focus({preventScroll:true});
  else if(record){if(record.tagName!=='BUTTON')record.tabIndex=-1;record.focus({preventScroll:true});}
}
function renderOverview(){
  if($('needs-attention'))dependencyUI()?.renderOverview($('needs-attention'),snapshot,{...gitContext(),openItem:item=>{
    if(item.task_id){setView('tasks');openTaskDetail(item.task_id);}
    else{setView(item.kind==='contract'?'contracts':'requests');$(item.kind+'-'+item.id)?.scrollIntoView({block:'center'});}
  }});
  if(!$('summary'))return;
  $('summary').replaceChildren(); for(const [n,label] of [[snapshot.members.length,'项目成员'],[snapshot.tasks.length,'声明任务'],[snapshot.requests.filter(r=>!r.resolved_at&&(!r.dependency_id||r.dependency_route_state==='current')).length,'待解决请求'],[snapshot.git?.delivery_graph?.items?.length||0,'交付对象']]) add($('summary'),add(text('div','','metric'),text('strong',n),text('span',label)));
  if($('overlaps')){$('overlaps').replaceChildren();if(!snapshot.overlaps.length)empty($('overlaps'),'当前没有声明范围交叠。');const reasons={'Declared scopes are equal':'两项任务声明了相同的工作范围。','One declared scope is a slash-segment prefix of the other':'一项任务的声明范围包含另一项的子路径。'};snapshot.overlaps.forEach(o=>add($('overlaps'),add(text('article','','record'),text('h3',o.task_ids.map(taskName).join(' × ')),text('p',o.scopes.join(' / '),'meta'),text('p',reasons[o.reason]||o.reason))));}
  if($('git-overlaps')){$('git-overlaps').replaceChildren();gitUI()?.renderOverlaps($('git-overlaps'),snapshot.git,taskName);if(!snapshot.git?.overlaps?.length)empty($('git-overlaps'),'当前没有新鲜观测中的实际路径重叠。');}
}
function renderCapabilities(){window.CoopagentsCapabilities?.render($('capability-discovery'),snapshot.capabilities,{roomId:snapshot.me.room_id,openTask:openTaskDetail,showMatrix:false});}

function renderSharedContext(){
  const context=gitContext();window.CoopagentsSharedContext?.render($('shared-context'),snapshot.shared_context,
    {...context,roomId:snapshot.me.room_id,tasks:snapshot.tasks,members:snapshot.members,openTask:openTaskDetail,
     query:filters=>api('/api/operations/read_context',filters)});
}

function openDeliveryNode(node){
  if(!node)return;clearDrawerError();
  const container=$('task-detail');if(!container)return;
  activeTaskId=null;activeObject=null;taskOpener=document.activeElement;container.replaceChildren();
  setDrawerKind('交付');
  const kind={branch:'分支',commit:'Commit',pr:'Pull request',release:'Release'}[node.kind]||'交付对象';
  add(container,text('p',kind,'eyebrow'),text('h2',node.label||node.value),badge(node.state||'observed'),text('p',node.title||'','detail-value'),text('p','来源：'+(node.source||'交付关联'),'meta'),text('p','分支：'+(node.branch||'未声明'),'detail-value'));
  add(container,text('p','关联任务','detail-label'));
  if(!node.task_ids?.length)empty(container,'尚无关联任务。');
  (node.task_ids||[]).forEach(id=>container.append(button('任务：'+taskName(id),()=>openTaskDetail(id),'detail-link')));
  const evidence=[...new Set((node.associations||[]).map(a=>a.evidence).filter(Boolean))];if(evidence.length)add(container,text('p','证据','detail-label'),text('p',evidence.join('\n'),'detail-value'));
  const title=container.querySelector('h2');if(title)title.id='task-detail-title';
  if(!$('task-dialog').open)$('task-dialog').showModal();
}
function renderDeliveryTraceability(){window.CoopagentsDeliveryGraph?.render($('delivery-graph'),snapshot.git?.delivery_graph,snapshot.git,{...gitContext(),openTask:openTaskDetail,openNode:(_key,node)=>openDeliveryNode(node),taskName,canManage:!!snapshot.git?.can_manage,roomId:snapshot.me.room_id});}

let contextTab='agreements',taskLayout='board',settingsTab='repository';
function renderSettingsTabs(){if($('git-connection'))$('git-connection').hidden=settingsTab!=='repository';if($('collaboration-status'))$('collaboration-status').hidden=settingsTab!=='connections';document.querySelectorAll('[data-settings-tab]').forEach(tab=>{if(tab.dataset.settingsTab===settingsTab)tab.setAttribute('aria-current','page');else tab.removeAttribute('aria-current');});}
document.querySelectorAll('[data-settings-tab]').forEach(tab=>tab.addEventListener('click',()=>{settingsTab=tab.dataset.settingsTab;renderSettingsTabs();}));
function renderContractsTabs(){
  const sections=[['agreements',$('contracts')],['files',$('project-assets')],['records',$('shared-context')]];
  for(const [tab,target] of sections)if(target)target.hidden=contextTab!==tab;
  document.querySelectorAll('[data-context-tab]').forEach(button=>{if(button.dataset.contextTab===contextTab)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  if(contextTab==='files')assetsUI()?.render($('project-assets'),assetContext());
  if(contextTab==='records')renderSharedContext();
}
document.querySelectorAll('[data-context-tab]').forEach(button=>button.addEventListener('click',()=>{contextTab=button.dataset.contextTab;renderContractsTabs();}));

async function openWorkspaceProjectSwitcher(){
  const accounts=window.CoopagentsAccounts;if(!accountManaged||!accounts?.switcherProjects)return;
  const opener=$('account-switchers'),dialog=$('workspace-project-dialog'),list=$('workspace-project-list');
  list.replaceChildren(text('p','正在读取可访问项目…','muted'));
  if(!dialog.open)dialog.showModal();
  try{
    const data=await accounts.switcherProjects();if(!dialog.open)return;
    list.replaceChildren();let team='';
    for(const project of data.projects||[]){
      if(project.team_name&&project.team_name!==team){team=project.team_name;list.append(text('p',team,'workspace-project-group'));}
      const row=button('',async()=>{if(project.room_id===snapshot?.me?.room_id){dialog.close();return;}row.disabled=true;try{dialog.close();await accounts.selectProject(project.room_id);}catch(error){$('workspace-switch-error').textContent=error.message;row.disabled=false;dialog.showModal();}},'workspace-project-option');
      row.dataset.projectId=project.room_id;row.setAttribute('role','option');row.setAttribute('aria-selected',String(project.room_id===snapshot?.me?.room_id));
      add(row,text('span',(project.name||'P').slice(0,1),'project-switch-mark'),add(text('span','','workspace-project-detail'),text('strong',project.name),text('small',project.repository||'未声明仓库','meta')),text('span',project.room_id===snapshot?.me?.room_id?'当前':'›',project.room_id===snapshot?.me?.room_id?'project-current':'project-arrow'));list.append(row);
    }
    if(!list.children.length)list.append(text('p','当前账号没有可访问的项目。','empty'));
    $('workspace-team').replaceChildren();for(const item of data.teams||[]){const option=text('option',item.name);option.value=item.team_id;$('workspace-team').append(option);} $('workspace-team').value=data.team_id||'';
    $('workspace-switch-error').textContent='';
  }catch(error){if(dialog.open){list.replaceChildren(text('p',error.message,'error'));}}
  $('close-project-switcher').focus();
}
$('account-switchers').addEventListener('click',openWorkspaceProjectSwitcher);
$('close-project-switcher').addEventListener('click',()=>$('workspace-project-dialog').close());
$('workspace-project-dialog').addEventListener('close',()=>{$('workspace-switch-error').textContent='';if($('account-switchers').isConnected)$('account-switchers').focus();});
$('workspace-team').addEventListener('change',()=>{if($('workspace-project-dialog').open)$('workspace-project-dialog').close();});

function taskLink(id) { return button('任务：'+taskName(id),()=>{setView('tasks');openTaskDetail(id);},'link-button'); }
const taskColumns = boardUI()?.columns || [
  ['open','待认领','明确意图，等待接手'],
  ['working','推进中','agent 正在推进'],
  ['blocked','遇到阻塞','需要团队协助'],
  ['review','待验收','本地完成、已推送或 PR 打开'],
  ['merged','已合并','查看卡片中的交付证据来源'],
  ['cancelled','已取消','保留历史，可重新打开']
];
let activeTaskId=null, taskOpener=null,activeObject=null;
function taskColumn(task, progress){
  if(boardUI())return boardUI().column(task,progress,snapshot,{git:gitUI(),dependencies:dependencyUI()});
  if(task.cancelled_at||task.state==='cancelled')return 'cancelled';
  if(!task.owner_member_id) return 'open';
  if(dependencyUI()?.blocked(task,snapshot))return 'blocked';
  const state=gitUI()?.state(task,progress,snapshot?.git) || progress?.state;
  if(state==='blocked')return 'blocked';
  if(state==='merged')return 'merged';
  if(['local_done','pushed','pr_open'].includes(state))return 'review';
  return 'working';
}
function matchingTasks(tasks, progress, query, owner){
  if(boardUI())return boardUI().matchingTasks(tasks,progress,query,owner);
  const needle=query.trim().toLocaleLowerCase();
  return tasks.filter(t=> (!owner || (owner==='unassigned'?!t.owner_member_id:String(t.owner_member_id)===owner)) &&
    (!needle || [t.title,t.scope,t.intent_key,progress.find(p=>p.task_id===t.id)?.summary||''].join(' ').toLocaleLowerCase().includes(needle)));
}
function boardMetrics(){
  return [[snapshot.tasks.length,'协作任务'],[snapshot.members.length,'团队成员'],
    [snapshot.requests.filter(r=>!r.resolved_at&&(!r.dependency_id||r.dependency_route_state==='current')).length,'待解决请求'],
    [snapshot.tasks.filter(t=>taskColumn(t,snapshot.progress.find(p=>p.task_id===t.id))==='merged').length,'已合并任务']];
}
function renderTasks(){
  $('board-summary').replaceChildren();
  boardMetrics().forEach(([n,label])=>add($('board-summary'),add(text('div','','metric'),text('span',label),text('strong',String(n).padStart(2,'0')))));
  const selected=$('task-owner').value;
  $('task-owner').replaceChildren();
  [['','所有成员'],['unassigned','待认领'],...snapshot.members.map(m=>[String(m.member_id),m.display_name])].forEach(([value,label])=>{const o=text('option',label);o.value=value;$('task-owner').append(o);});
  $('task-owner').value=selected;
  const filtered=matchingTasks(snapshot.tasks,snapshot.progress,$('task-search').value,$('task-owner').value).filter(t=>lifecycleUI()?.matches(t,$('task-status')?.value||'active')??true);
  $('board-count').textContent=filtered.length+' / '+snapshot.tasks.length+' 项任务';
  $('board-empty').hidden=filtered.length>0 || snapshot.tasks.length===0;
  $('tasks').replaceChildren();
  if(taskLayout==='list'&&boardUI()?.table){$('tasks').className='task-list';$('tasks').append(boardUI().table(filtered,snapshot,{git:gitUI(),dependencies:dependencyUI(),open:openTaskDetail}));}
  else {$('tasks').className='kanban-board';taskColumns.forEach(([key,label,note])=>{
    const filter=$('task-status')?.value||'active';
    if((key==='cancelled'&&filter==='active')||(key!=='cancelled'&&filter==='cancelled'))return;
    const column=text('section','','kanban-column column-'+key), list=text('div','','column-cards');
    const tasks=filtered.filter(t=>taskColumn(t,snapshot.progress.find(p=>p.task_id===t.id))===key);
    add(column,add(text('header','','column-heading'),add(text('div'),text('span','','status-dot'),text('h2',label),text('span',tasks.length,'column-count')),text('p',note)),list);
    if(!tasks.length)empty(list,snapshot.tasks.length?'此列暂无匹配任务':'等待第一项工作');
    tasks.forEach(t=>{
      if(boardUI()){list.append(boardUI().card(t,snapshot.progress.find(p=>p.task_id===t.id),snapshot,{git:gitUI(),dependencies:dependencyUI(),open:openTaskDetail}));return;}
      const p=snapshot.progress.find(p=>p.task_id===t.id), requests=snapshot.requests.filter(r=>r.task_id===t.id), card=button('',()=>openTaskDetail(t.id),'task-card');
      card.id='task-'+t.id;card.setAttribute('aria-label','查看任务 #'+t.id+'：'+t.title);
      add(card,add(text('div','','card-top'),text('span','CM-'+String(t.id).padStart(3,'0'),'task-number'),text('span','↗','card-arrow')),text('h3',t.title),text('p',p?.summary||(t.cancelled_at?'任务已取消，可在详情重新打开。':'已声明工作范围，等待 agent 推进。'),'card-summary'),text('p',t.scope,'card-scope'));
      add(card,add(text('div','','card-bottom'),add(text('span','','card-person'),text('span',(t.owner_member_id?memberName(t.owner_member_id):'?').slice(0,1),'avatar'),text('span',t.cancelled_at?'已取消':t.owner_member_id?memberName(t.owner_member_id):'待认领')),text('span',requests.length+' 请求','card-meta')),text('p',date(p?.updated_at||t.cancelled_at||t.claimed_at||t.created_at)+' · '+(t.cancelled_at?'已取消':p?'agent 自述':t.owner_member_id?'已认领':'任务声明'),'card-time'));
      const handoff=snapshot.lifecycle?.handoffs?.find(h=>h.task_id===t.id&&h.status==='pending');if(handoff)card.append(text('p','待 '+memberName(handoff.target_member_id)+' 接手 · '+handoff.summary,'card-summary'));
      const deps=(snapshot.dependencies||[]).filter(d=>d.source_task_id===t.id&&d.status==='active');if(deps.length)card.append(text('p','等待 '+deps.map(d=>d.target.title+'（'+(d.target.owner_member_id?memberName(d.target.owner_member_id):'待分派')+'）').join('、'),'card-summary'));
      const gitSummary=gitUI()?.summarize(t.id,snapshot.git);if(gitSummary)card.append(text('p',gitSummary,'card-git'));
      list.append(card);
    });
    $('tasks').append(column);
  });
  }
  if(activeTaskId!==null) renderTaskDetail();
}
function renderTaskDetail(){
  const t=snapshot?.tasks.find(t=>t.id===activeTaskId); if(!t){closeTaskDetail();return;}
  const container=$('task-detail'), p=snapshot.progress.find(p=>p.task_id===t.id);
  if(container.contains(document.activeElement)&&['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
  const active=document.activeElement,focused=container.contains(active)?{tag:active.tagName,key:active.dataset.lifecycleFocus,label:active.textContent}:null;
  container.replaceChildren();
  const title=text('h2',t.title);title.id='task-detail-title';
  add(container,text('p','CM-'+String(t.id).padStart(3,'0'),'eyebrow'),title,add(text('p','','detail-status'),badge(dependencyUI()?.blocked(t,snapshot)?'blocked':gitUI()?.state(t,p,snapshot.git)||p?.state||t.state),text('span',t.cancelled_at?'已取消，恢复后可认领':t.owner_member_id?memberName(t.owner_member_id):'等待 agent 认领')),text('p','声明范围','detail-label'),text('p',t.scope,'detail-value'),text('p','去重标识','detail-label'),text('p',t.intent_key,'detail-value'),text('p','创建 '+date(t.created_at)+(t.claimed_at?' · 认领 '+date(t.claimed_at):''),'meta'));
  if(p)add(container,text('p','最新进展','detail-label'),text('p',p.summary,'detail-value'),text('p','agent 自述 · '+memberName(p.member_id)+' · '+date(p.updated_at),'meta'),text('p','证据：'+(p.evidence||'未提供'),'detail-value'));
  gitUI()?.renderDetails(container,t,snapshot.git,gitContext());
  lifecycleUI()?.renderDetails(container,t,snapshot,gitContext());
  dependencyUI()?.renderDetails(container,t,snapshot,gitContext());
  const related=snapshot.requests.filter(r=>r.task_id===t.id);
  add(container,text('p','关联技术请求','detail-label'));
  if(!related.length)empty(container,'尚无关联请求。');
  related.forEach(r=>container.append(button('#'+r.id+' '+r.body,()=>{closeTaskDetail();setView('requests');$('request-'+r.id)?.scrollIntoView({block:'center'});},'detail-link')));
  const contracts=snapshot.contracts.filter(c=>c.versions.some(v=>related.some(r=>r.id===v.source_request_id)));
  add(container,text('p','关联公共约定','detail-label'));
  if(!contracts.length)empty(container,'尚无关联公共约定。');
  contracts.forEach(c=>container.append(button(c.contract_key+' · 生效 '+(c.effective_version?'v'+c.effective_version:'未批准'),()=>{closeTaskDetail();setView('contracts');$('contract-'+c.id)?.scrollIntoView({block:'center'});},'detail-link')));
  if(focused)Array.from(container.querySelectorAll('button,summary')).find(node=>node.tagName===focused.tag&&(focused.key?node.dataset.lifecycleFocus===focused.key:node.textContent===focused.label))?.focus({preventScroll:true});
}
function clearDrawerError(){const error=$('drawer-error');if(error)error.textContent='';}
function setDrawerKind(kind){clearDrawerError();if($('drawer-kind'))$('drawer-kind').textContent=kind+'详情';$('close-task').setAttribute?.('aria-label','关闭'+kind+'详情');}
function openTaskDetail(id){setDrawerKind('任务');activeObject=null;activeTaskId=id;taskOpener=document.activeElement;renderTaskDetail();if(!$('task-dialog').open)$('task-dialog').showModal();}
function closeTaskDetail(){clearDrawerError();activeObject=null;activeTaskId=null;if($('task-dialog').open)$('task-dialog').close();$('task-detail').replaceChildren();}
$('close-task').addEventListener('click',closeTaskDetail);
$('task-dialog').addEventListener('close',()=>{if($('task-dialog').open)return;clearDrawerError();activeObject=null;activeTaskId=null;$('task-detail').replaceChildren();const target=taskOpener?.isConnected?taskOpener:$(taskOpener?.id);if(target)target.focus();else $('task-search').focus();taskOpener=null;});
document.querySelectorAll('[data-task-layout]').forEach(tab=>tab.addEventListener('click',()=>{taskLayout=tab.dataset.taskLayout;document.querySelectorAll('[data-task-layout]').forEach(button=>{if(button===tab)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});if(snapshot)renderTasks();}));
$('task-search').addEventListener('input',()=>{if(snapshot)renderTasks();});
$('task-owner').addEventListener('change',()=>{if(snapshot)renderTasks();});
$('clear-filters').addEventListener('click',()=>{
  $('task-search').value='';$('task-owner').value='';if($('task-status'))$('task-status').value='active';
  if(snapshot)renderTasks();$('task-search').focus();
});
$('task-status')?.addEventListener('change',()=>{if(snapshot)renderTasks();});
$('new-task').addEventListener('click',()=>{$('task-create').open=true;$('task-form').querySelector('input').focus();});
function openContentDetail(label,body){clearDrawerError();activeTaskId=null;activeObject=null;taskOpener=document.activeElement;setDrawerKind('共享文件');const title=text('h2',label);title.id='task-detail-title';$('task-detail').replaceChildren(title,body);if(!$('task-dialog').open)$('task-dialog').showModal();}
function objectTitle(label,kind,id){return button(label,()=>openObjectDetail(kind,id),'object-title-button');}
function openObjectDetail(kind,id){clearDrawerError();setDrawerKind(kind==='request'?'协作请求':'约定');activeTaskId=null;activeObject={kind,id};taskOpener=document.activeElement;renderObjectDetail();if(!$('task-dialog').open)$('task-dialog').showModal();}
function renderObjectDetail(){
  if(!activeObject||!snapshot)return;const {kind,id}=activeObject,item=(kind==='request'?snapshot.requests:snapshot.contracts).find(item=>item.id===id);
  if(!item){closeTaskDetail();return;}
  const container=$('task-detail');if(container.contains(document.activeElement)&&['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
  const active=document.activeElement,recordId=(kind==='request'?'request-':'contract-')+id;
  const focus=active?.closest?.('.record')?.id===recordId?{record:recordId,tag:active.tagName,label:active.textContent}:null;
  const expanded=Array.from(container.querySelectorAll('.record details[open]')).filter(details=>details.closest('.record')?.id===recordId).map(details=>details.querySelector('summary')?.textContent);
  container.replaceChildren();const title=text('h2',kind==='request'?'协作请求 #'+id:item.contract_key);title.id='task-detail-title';container.append(title);
  const record=kind==='request'?requestRecord(item):contractRecord(item);record.id=recordId;container.append(record);
  for(const summary of expanded){const details=Array.from(record.querySelectorAll('details')).find(details=>details.querySelector('summary')?.textContent===summary);if(details)details.open=true;}
  if(focus)restoreRecordFocus(focus);
}
function requestRecord(r){
  const row=text('article','','record'); add(row,add(text('div','','record-header'),add(text('div'),badge(r.resolved_at?'已解决':'待解决'),text('span','#'+r.id+' · 上下文 v'+r.context_version,'meta')),text('span',memberName(r.sender_member_id)+' → '+memberName(r.receiver_member_id),'meta')),text('h3',r.body)); if(r.task_id) row.append(taskLink(r.task_id));
    add(row,text('p','发起 '+date(r.created_at)+' · 分派 '+date(r.assigned_at),'meta'),text('p','读取 '+date(r.read_at)+' · 处理 '+date(r.processed_at)+' · 解决 '+date(r.resolved_at),'timeline'));
    if(!r.dependency_id && !r.receiver_member_id && !r.resolved_at){ const form=text('form','','assignment'),label=text('label','分派收件人'),select=document.createElement('select'); select.name='receiver_member_id'; select.required=true; add(select,text('option','选择成员')); select.firstChild.value=''; snapshot.members.forEach(m=>{const o=text('option',m.display_name);o.value=m.member_id;select.append(o);}); label.append(select); const submit=text('button','分派');submit.type='submit'; add(form,label,submit); form.addEventListener('submit',e=>{e.preventDefault(); perform(submit,()=>api('/api/requests/'+r.id+'/assign',{receiver_member_id:select.value}));}); row.append(form); }
    if(r.dependency_id)row.append(text('p',r.dependency_route_state==='current'?'当前任务依赖：请在任务详情答复或确认满足。':r.dependency_route_state==='historical'?'历史路由：责任人已变化，原消息和回执保留。':'已关闭的任务依赖，保留处理记录。','notice'));
    r.replies.forEach(reply=>add(row,add(text('div','','reply'),text('p',memberName(reply.author_member_id)+' · 回复 · '+date(reply.created_at),'meta'),text('p',reply.body),text('p','证据：'+(reply.evidence||'未提供'),'meta'))));
    if(!r.dependency_id && !r.resolved_at && r.replies.length && r.sender_member_id===snapshot.me.member_id) row.append(button('确认请求已解决',e=>perform(e.currentTarget,()=>api('/api/requests/'+r.id+'/resolve',{context_version:r.context_version}))));
return row;
}
function contractRecord(c){
  const row=text('article','','record'); const head=c.versions.find(v=>v.version===c.current_version); add(row,add(text('div','','record-header'),text('span',c.contract_key,'eyebrow'),text('span','当前 v'+c.current_version+' / '+(c.effective_version?'生效 v'+c.effective_version:'尚未生效'),'meta')),text('h3',head?.title || c.contract_key));
    if(head){ add(row,add(text('p','','record-body'),badge(head.decision || '等待人工审核')),text('p',head.body),text('p','提出人 '+memberName(head.proposer_member_id)+' · '+date(head.created_at)+' · 提交引用 '+(head.commit_ref || '未提供'),'meta')); if(head.source_request_id) row.append(button('来源请求 #'+head.source_request_id,()=>{setView('requests');openObjectDetail('request',head.source_request_id);},'link-button'));
      if(!head.decision) ['approved','rejected'].forEach(decision=>row.append(button((decision==='approved'?'批准':'拒绝')+' v'+head.version,e=>perform(e.currentTarget,()=>api('/api/contracts/'+c.id+'/decision',{version:head.version,decision})),decision==='approved'?'primary':'danger')));
    }
    add(row,detail('版本记录 · '+c.versions.length+' 个版本',c.versions.slice().reverse().map(v=>add(text('div','','history'),text('h3','v'+v.version+' · '+v.title),badge(v.decision || '待审核'),text('p',v.body),text('p','提出 '+memberName(v.proposer_member_id)+' · '+date(v.created_at)+' / 决定 '+memberName(v.decided_by_member_id)+' · '+date(v.decided_at),'meta'),text('p','提交引用 '+(v.commit_ref||'未提供')+(v.source_request_id?' · 来源请求 #'+v.source_request_id:''),'meta')))));
    const events=snapshot.events.filter(e=>e.contract_id===c.id); if(events.length) add(row,detail('审核事件',events.map(e=>text('p','v'+e.version+' · '+({proposed:'提出',approved:'批准',rejected:'拒绝'}[e.event_type]||e.event_type)+' · '+memberName(e.actor_member_id)+' · '+date(e.created_at),'meta')))); return row;
}
function renderRequests(){
  const root=$('requests');root.replaceChildren();
  const query=($('request-search')?.value||'').trim().toLocaleLowerCase(),state=$('request-filter')?.value||'all';
  const rows=snapshot.requests.filter(r=>(!query||[r.body,memberName(r.sender_member_id),memberName(r.receiver_member_id),...r.replies.map(reply=>reply.body)].join(' ').toLocaleLowerCase().includes(query))&&(state==='all'||state==='resolved'?state==='all'||!!r.resolved_at:!r.resolved_at));
  if(!rows.length)empty(root,snapshot.requests.length?'没有匹配的协作请求，请调整筛选。':'暂时没有协作请求。');
  rows.forEach(r=>{
    const row=text('article','','request-row'),content=text('div','','request-main'),people=text('div','','request-people'),state=text('span',r.resolved_at?'已解决':r.replies.length?'已有回复 · 待确认':'等待回复','object-status '+(r.resolved_at?'good':r.replies.length?'pending':'waiting'));
    row.id='request-'+r.id;
    add(content,text('span','请求 #'+r.id,'object-reference'),objectTitle(r.body,'request',r.id));
    if(r.task_id)content.append(taskLink(r.task_id));
    const latest=r.replies[r.replies.length-1];if(latest)content.append(text('p',memberName(latest.author_member_id)+'：'+latest.body,'reply-preview'));
    add(people,text('p',memberName(r.sender_member_id)+' → '+memberName(r.receiver_member_id)),text('p',date(latest?.created_at||r.created_at),'meta'));
    add(row,content,people,state);root.append(row);
  });
  if(activeObject?.kind==='request')renderObjectDetail();
}
function renderContracts(){
  const root=$('contracts');root.replaceChildren();if(!snapshot.contracts.length)empty(root,'尚无公共约定。agent 提出的版本会在这里等待人工审核。');
  snapshot.contracts.forEach(c=>{
    const effective=c.versions.find(v=>v.version===c.effective_version),latest=c.versions.find(v=>v.version===c.current_version),current=effective||latest;
    const row=text('article','','content-row'),mark=text('span','≡','object-mark'),body=text('div','','row-content'),end=text('div','','row-end');row.id='contract-'+c.id;
    add(body,objectTitle(current?.title||c.contract_key,'contract',c.id),text('p',c.contract_key+' · '+(effective?'生效 v'+c.effective_version:'尚未生效'),'meta'),text('p',effective?.body||'等待团队审核提案。','object-summary'));
    if(latest&&!latest.decision)end.append(text('span','待审 v'+latest.version,'object-status pending'));else end.append(text('span',effective?'已生效':'已审核','object-status good'));
    end.append(button('查看详情',()=>openObjectDetail('contract',c.id),'link-button'));add(row,mark,body,end);root.append(row);
  });
  if(activeObject?.kind==='contract')renderObjectDetail();
}
['request-search','request-filter'].forEach(id=>$(id)?.addEventListener(id==='request-search'?'input':'change',()=>{if(snapshot)renderRequests();}));
async function perform(b, operation){ b.disabled=true; $('action-error').textContent='';clearDrawerError();const epoch=generation,object=activeObject?{...activeObject}:null,taskId=activeTaskId; try { await operation(); if(epoch===generation&&objectMatches(object,taskId)){ renderSignature=''; await sync(); } } catch(error){ if(epoch===generation&&objectMatches(object,taskId)){const target=$('task-dialog').open?$('drawer-error'):$('action-error');target.textContent=error.message;} } finally{if(epoch===generation&&objectMatches(object,taskId))b.disabled=false;} }
function objectMatches(object,taskId){return object?activeObject?.kind===object.kind&&activeObject?.id===object.id:activeObject===null&&activeTaskId===taskId;}
$('task-form').addEventListener('submit',e=>{e.preventDefault();const form=e.currentTarget,b=form.querySelector('button[type=submit]'),epoch=generation;perform(b,async()=>{await api('/api/tasks',Object.fromEntries(new FormData(form)));if(epoch===generation){form.reset();$('task-create').open=false;$('new-task').focus();}});});
$('retry').addEventListener('click',sync); $('logout').addEventListener('click',()=>{if(accountManaged && typeof window!=='undefined')window.CoopagentsAccounts.home();else logout();});
function configTemplate(){const url=location.origin+'/mcp'; const tool=$('connection-tool').value; $('config-template').value=tool==='codex-desktop'?'[mcp_servers.coopagents]\nurl = "'+url+'"\nhttp_headers = { Authorization = "Bearer TOKEN" }':tool==='codex-cli'?"$env:COOPAGENTS_AGENT_TOKEN = 'TOKEN'\ncodex mcp add coopagents --url "+url+' --bearer-token-env-var COOPAGENTS_AGENT_TOKEN':"claude mcp add --transport http --scope local coopagents "+url+' --header "Authorization: Bearer TOKEN"';}
async function copy(value){try{await navigator.clipboard.writeText(value);$('dialog-status').textContent='已复制，请妥善保存。';}catch{$('dialog-status').textContent='复制不可用，请选择字段并手动复制。';}}
let dialogOpener=null, privateEpoch=0;
const skillUrl=()=>location.origin+'/skills/coopagents-connect/SKILL.md';
function connectionPrompt(project,tool,credential='') {
  return '请读取并使用 Coopagents 接入 Skill：'+skillUrl()+'\n协议参考：'+location.origin+'/skills/coopagents-connect/protocol.md'+
    '\n我授权你为当前工具配置这个项目的原生 MCP，并将 Skill 安装到受支持的个人 Skill 目录（已有文件不得覆盖或删除）。不要安装 Coopagents 客户端。'+
    '\n服务：'+location.origin+'\nMCP：'+location.origin+'/mcp\n项目：'+project+'\n工具：'+tool+
    (credential?'\n个人 agent 凭据：'+credential:'\n这是无凭据预览；请在项目网页点击生成接入指令获取本人凭据。')+
    '\n凭据仅用于私有配置和同源认证请求，不要回显、写入 URL 或提交 Git。验证 /api/me 项目身份，再配置 MCP；需要重启请明确说明。';
}
function showPrivate(title, credentials={}) { clearPrivate(); $('private-title').textContent=title; $('dialog-status').textContent=''; $('connection-help').hidden=!!(credentials.invite_token||credentials.invite_url);
  for(const [key,label,expiry] of [['invite_url','邀请链接',credentials.expires_at],['invite_token','邀请令牌',credentials.expires_at],['web_token','网页恢复凭据',credentials.web_expires_at],['agent_token','个人 agent 令牌',credentials.agent_expires_at||credentials.expires_at]]) if(credentials[key]) {
    const value=credentials[key],block=text('div','','secret'),l=text('label',label),input=document.createElement('input');input.type='password';input.readOnly=true;input.value=value;input.autocomplete='off';l.append(input);
    add(block,l,button('显示 / 隐藏',()=>{input.type=input.type==='password'?'text':'password';}),button('复制',()=>copy(input.value)),text('p','有效期至 '+date(expiry)+' · 关闭后不再展示','meta')); $('private-content').append(block);
  }
  $('mcp-url').value=location.origin+'/mcp'; configTemplate(); if(!$('private-dialog').open){dialogOpener=document.activeElement;$('private-dialog').showModal();}
  if(snapshot&&!credentials.invite_token&&!credentials.invite_url)collaborationUI()?.renderSetup($('collaboration-setup'),snapshot,gitContext());
}
function clearPrivate(){ privateEpoch++; $('private-content').querySelectorAll?.('input,textarea').forEach(e=>{e.value='';});$('private-content').replaceChildren(); $('dialog-status').textContent=''; $('config-template').value=''; $('collaboration-setup')?.replaceChildren(); }
function closePrivate(){if($('private-dialog').open)$('private-dialog').close();clearPrivate();}
$('private-dialog').addEventListener('close',()=>{clearPrivate();if(dialogOpener?.isConnected)dialogOpener.focus();dialogOpener=null;});
$('close-dialog').addEventListener('click',closePrivate); $('connection-button').addEventListener('click',()=>showPrivate('接入 agent'));
$('generate-connection').addEventListener('click',async e=>{
  const epoch=generation, dialog=privateEpoch, project=snapshot?.me.room_id, tool=$('connection-tool').value, b=e.currentTarget;
  if(!project)return;
  b.disabled=true;$('dialog-status').textContent='正在生成本人项目接入指令…';
  try{
    const result=await api('/api/agent-connect',{},true,{Origin:location.origin});
    if(epoch!==generation||dialog!==privateEpoch||!$('private-dialog').open)return;
    if(result.room_id!==project||result.member_id!==snapshot.me.member_id)throw new Error('接入身份不匹配，请重新打开项目');
    const block=text('div','','secret'),label=text('label','私有接入指令（包含个人凭据）'),input=document.createElement('textarea');
    input.readOnly=true;input.rows=10;input.autocomplete='off';input.hidden=true;input.value=connectionPrompt(project,tool,result.agent_token);label.append(input);
    $('private-content').querySelectorAll?.('input,textarea').forEach(e=>{e.value='';});$('private-content').replaceChildren();
    add(block,label,button('显示 / 隐藏指令',()=>{input.hidden=!input.hidden;}),button('复制接入指令',()=>copy(input.value)),text('p','复制给自己的 agent，一次完成接入。有效期至 '+date(result.expires_at)+'。已有连接继续有效。','meta'));
    $('private-content').append(block);$('dialog-status').textContent='指令已生成，请复制给自己的 agent；关闭后清空。';
  }catch(error){if(epoch===generation&&dialog===privateEpoch&&$('private-dialog').open)$('dialog-status').textContent=error.message;}
  finally{b.disabled=false;}
});
$('copy-skill-preview').addEventListener('click',()=>copy(connectionPrompt(snapshot?.me.room_id||'请选择项目',$('connection-tool').value)));
$('copy-url').addEventListener('click',()=>copy($('mcp-url').value)); $('connection-tool').addEventListener('change',()=>{clearPrivate();configTemplate();}); $('copy-template').addEventListener('click',()=>copy($('config-template').value));
$('invite-button').addEventListener('click',e=>{const epoch=generation;perform(e.currentTarget,async()=>{const result=await api('/api/invites',{});if(epoch===generation)showPrivate('邀请一位团队成员',result);});});
$('rotate-agent').addEventListener('click',async e=>{ const b=e.currentTarget; b.disabled=true;const epoch=generation;try{const result=await api('/api/agent-token',{});if(epoch===generation){showPrivate('保存新的 agent 令牌',result);$('dialog-status').textContent='旧 agent 令牌已立即失效。请更新配置并重建连接。';}}catch(error){if(epoch===generation)$('dialog-status').textContent=error.message;}finally{b.disabled=false;} });
setView(routeView()||'tasks',{push:false});
if(typeof window!=='undefined') window.CoopagentsProject={
  enter(credential,options={}){const view=options.restoreView?(routeView()||'tasks'):'tasks';logout();accountManaged=true;sessionStorage.setItem('coopagents_account_project','1');enter(credential);setView(view,{push:false,replace:true});},
  clear(){logout();accountManaged=false;},
  private:showPrivate,
  managed(){return accountManaged;},
  updateSwitcher(data){
    const button=$('account-switchers'),dialog=$('workspace-project-dialog'),list=$('workspace-project-list');
    if(!button||!dialog||!list||!data)return;
    button.hidden=!accountManaged;
    const current=data.projects?.find(p=>p.room_id===data.current_room_id);
    $('workspace-switcher-current').textContent=current?.name||'选择项目';
    $('workspace-switcher-team').textContent=data.team?.name||current?.team_name||'';
    $('workspace-crumb-team').textContent=$('workspace-switcher-team').textContent||'项目空间';
    $('workspace-crumb-project').textContent=current?.name||'当前项目';
    list.replaceChildren();
    for(const p of data.projects||[]){
      const row=document.createElement('button');row.type='button';row.className='workspace-project-option';row.setAttribute('data-project-id',p.room_id);row.setAttribute('aria-selected',String(p.room_id===data.current_room_id));
      const mark=text('span',(p.name||'P').slice(0,1),'project-switch-mark'),copy=text('span','', 'workspace-project-detail');copy.append(text('strong',p.name||'未命名项目'),text('small',p.repository||'未声明仓库','meta'));
      row.append(mark,copy,text('span',p.room_id===data.current_room_id?'当前':'›',p.room_id===data.current_room_id?'project-current':'project-arrow'));list.append(row);
    }
    if(!$('workspace-project-list').children.length)list.append(text('p','当前团队没有已授权项目。','empty'));
  }
};
// Account-managed project credentials are reissued only after validating the cookie.
if(token && !sessionStorage.getItem('coopagents_account_project')) enter(token);
