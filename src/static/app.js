'use strict';
const $ = id => document.getElementById(id);
let token = sessionStorage.getItem('crewmesh_web_token') || '';
let generation = 0, snapshot = null, pollTimer = null, syncing = false, lastSuccess = null;
let accountManaged = false;
const projectRequests = new Set();
const gitUI = () => typeof window!=='undefined' ? window.CrewmeshGit : null;
const lifecycleUI = () => typeof window!=='undefined' ? window.CrewmeshTaskLifecycle : null;
const collaborationUI = () => typeof window!=='undefined' ? window.CrewmeshCollaboration : null;
function gitContext(){const epoch=generation;return {api,sync,me:snapshot.me,memberName,origin:location.origin,isCurrent:()=>epoch===generation};}
const states = {cancelled:'已取消',open:'待认领', claimed:'已认领', working:'推进中', blocked:'受阻', local_done:'本地完成', pushed:'已推送', pr_open:'PR 已打开', merged:'已合并', approved:'已批准', rejected:'已拒绝'};
const views = {overview:['01 / TEAM FIELD','团队现场','理解每个人正在推进的工作。'],tasks:['TEAM OPERATIONS / 任务协作','任务看板','每一项工作，都有清晰的去向。'],requests:['03 / TECHNICAL REQUESTS','技术请求','让依赖有去处，让答复有记录。'],contracts:['04 / SHARED AGREEMENTS','公共约定','把技术共识变成明确生效的版本。'],repository:['05 / REPOSITORY','仓库接入','让实际开发和远端交付成为可追溯的协作证据。']};
const text = (tag, value, cls) => { const e = document.createElement(tag); e.textContent = value == null ? '' : String(value); if(cls) e.className = cls; return e; };
const add = (parent, ...children) => { children.forEach(c => parent.append(c)); return parent; };
const button = (label, action, cls) => { const b = text('button', label, cls); b.type = 'button'; b.addEventListener('click', action); return b; };
const date = value => { if(!value) return '—'; const d = new Date(value); return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}); };
const memberName = id => snapshot?.members.find(m => m.member_id === id)?.display_name || (id ? '成员 ' + id : '待分派');
const taskName = id => snapshot?.tasks.find(t => t.id === id)?.title || '任务 #' + id;
const empty = (target, message) => target.append(text('p',message,'empty'));
const badge = value => text('span',states[value] || value,'badge');
const detail = (title, children) => add(document.createElement('details'),text('summary',title),...children);
function setView(view) {
  for(const key of Object.keys(views)) $('view-'+key).hidden = key !== view;
  document.querySelectorAll('[data-view]').forEach(b => { if(b.dataset.view === view) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current'); });
  [$('view-kicker').textContent,$('view-title').textContent,$('view-description').textContent] = views[view];
}
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click',() => setView(b.dataset.view)));
const tabs = Array.from(document.querySelectorAll('[data-entry]'));
function entryTab(b) { if(b.hidden)return;tabs.forEach(t => { const active=t===b; t.setAttribute('aria-selected',String(active)); t.tabIndex=active?0:-1; $('form-'+t.dataset.entry).hidden=!active; }); }
tabs.forEach((b,i) => { b.tabIndex=i? -1:0; b.addEventListener('click',() => entryTab(b)); b.addEventListener('keydown',e => { if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){ e.preventDefault(); const visible=tabs.filter(t=>!t.hidden),current=visible.indexOf(b); const next=e.key==='Home'?0:e.key==='End'?visible.length-1:(current+(e.key==='ArrowRight'?1:visible.length-1))%visible.length; entryTab(visible[next]); visible[next].focus(); } }); });
async function api(path, data, authenticated = true, extraHeaders = {}) {
  const epoch=generation, credential=token, controller=new AbortController();
  projectRequests.add(controller);
  const timeout=setTimeout(() => controller.abort(),10000);
  try {
    const headers={...extraHeaders}; if(authenticated) headers.Authorization='Bearer '+credential;
    if(data!==undefined) headers['Content-Type']='application/json';
    const response=await fetch(path,{method:data===undefined?'GET':'POST',headers,body:data===undefined?undefined:JSON.stringify(data),signal:controller.signal,cache:'no-store'});
    if(epoch!==generation) throw new Error('访问已切换');
    let result; try { result=await response.json(); } catch { throw new Error('服务返回了无法读取的响应'); }
    if(epoch!==generation) throw new Error('访问已切换');
    if(response.status===401){ if(authenticated){if(accountManaged && typeof window!=='undefined')window.CrewmeshAccounts.denied();else logout('网页凭据已失效，请恢复访问或重新加入。');} throw new Error(authenticated?'网页凭据已失效':(result.message || '邀请或凭据不可用')); }
    if(!response.ok) throw new Error(result.message || '操作未完成');
    return result;
  } catch(error) { if(error.name==='AbortError') throw new Error('连接超时，请重试'); throw error; }
  finally { clearTimeout(timeout); projectRequests.delete(controller); }
}
function logout(message='') {
  generation++; token=''; snapshot=null; sessionStorage.removeItem('crewmesh_web_token'); clearTimeout(pollTimer);
  projectRequests.forEach(controller=>controller.abort()); projectRequests.clear(); syncing=false;
  gitUI()?.clear(); $('git-connection')?.replaceChildren(); $('git-overlaps')?.replaceChildren();
  collaborationUI()?.clear(); lifecycleUI()?.clear();
  renderSignature=''; closePrivate(); closeTaskDetail(); $('task-search').value=''; $('task-owner').value=''; if($('task-status'))$('task-status').value='active'; $('workspace').hidden=true; $('login').hidden=false; $('login-error').textContent=message;
  ['members','tasks','requests','contracts','overlaps','summary'].forEach(id => $(id).replaceChildren());
  ['room-name','room-repository','identity','network-error','action-error','board-count'].forEach(id=>$(id).textContent='');
  $('form-restore').reset(); $('form-join').reset(); $('form-create').reset(); $('task-form').reset();
}
function enter(credential) { generation++; renderSignature=''; token=credential; sessionStorage.setItem('crewmesh_web_token',credential); $('login').hidden=true; $('workspace').hidden=false; $('action-error').textContent=''; $('sync-time').textContent='正在同步…'; $('network-error').hidden=true; lastSuccess=null; clearTimeout(pollTimer); sync(); }
for(const name of ['create','join','restore']) $('form-'+name).addEventListener('submit',async e => {
  e.preventDefault(); const form=e.currentTarget, b=form.querySelector('button[type=submit]'); b.disabled=true; $('login-error').textContent='';
  const epoch=generation;
  try { const data=Object.fromEntries(new FormData(form));
    const bootstrap=data.bootstrap_secret; delete data.bootstrap_secret;
    if(name==='restore'){ const credential=data.web_token.trim(); generation++; const restoreEpoch=generation; token=credential; await api('/api/snapshot'); if(restoreEpoch!==generation)return; enter(credential); }
    else { const result=await api(name==='create'?'/api/rooms':'/api/join',data,false,name==='create'&&bootstrap?{'X-Crewmesh-Bootstrap':bootstrap}:{}); if(epoch!==generation)return; enter(result.web_token); showPrivate('保存个人接入凭据',result); }
    form.reset();
  } catch(error) { if(!$('login').hidden) $('login-error').textContent=error.message; } finally { b.disabled=false; }
});
async function sync() {
  if(!token || syncing) return;
  syncing=true; const epoch=generation;
  try { const result=await api('/api/snapshot'); if(epoch!==generation) return; snapshot=result; lastSuccess=new Date(); $('network-error').hidden=true; $('sync-time').textContent='最后同步 '+date(lastSuccess); render(); }
  catch(error){ if(epoch===generation && token){ $('network-error').hidden=false; $('network-error').textContent='连接中断：'+error.message+'。保留上次数据'+(lastSuccess?'（最后成功 '+date(lastSuccess)+'）':'')+'，可点击刷新重试。'; } }
  finally { if(epoch===generation){syncing=false; if(token){ clearTimeout(pollTimer); pollTimer=setTimeout(sync,5000); }} }
}
// Keep forms, selection and keyboard focus intact when the snapshot is unchanged.
let renderSignature='';
function render() {
  const signature=JSON.stringify({...snapshot,server_time:null}); if(signature===renderSignature) return; renderSignature=signature;
  // Defer dynamic lists while a user edits a receiver or interacts with a record.
  if((['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName) && ['requests','contracts','tasks','task-detail','git-connection','collaboration-status'].some(id => $(id)?.contains(document.activeElement))) || !window.getSelection().isCollapsed){ renderSignature=''; return; }
  const active=document.activeElement, activeRecord=active?.closest('.record,.task-card');
  const focus=activeRecord ? {record:activeRecord.id,tag:active.tagName,label:active.textContent} : null;
  const expanded=Array.from(document.querySelectorAll('.record details[open]')).map(d=>({record:d.closest('.record').id,label:d.querySelector('summary').textContent}));
  $('room-name').textContent=snapshot.room.name; $('room-repository').textContent=snapshot.git?.binding?.repository || snapshot.room.repository || '未声明仓库'; $('identity').textContent=snapshot.me.display_name+' / '+(snapshot.me.role==='owner'?'项目创建者':'项目成员'); $('invite-button').hidden=accountManaged || snapshot.me.role!=='owner';
  renderOverview(); renderTasks(); renderRequests(); renderContracts();
  gitUI()?.renderPanel($('git-connection'),snapshot,gitContext());
  collaborationUI()?.renderPanel($('collaboration-status'),snapshot,gitContext());
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
  $('summary').replaceChildren(); for(const [n,label] of [[snapshot.members.length,'团队成员'],[snapshot.tasks.length,'声明任务'],[snapshot.requests.filter(r=>!r.resolved_at).length,'待解决请求']]) add($('summary'),add(text('div','','metric'),text('strong',n),text('span',label)));
  $('members').replaceChildren(); snapshot.members.forEach(m => {
    const row=text('article','','member-row'), profile=add(text('div'),text('h3',m.display_name),text('p',m.role==='owner'?'团队创建者':'团队成员','meta')), activity=text('div');
    const sessions=snapshot.sessions.filter(s=>s.member_id===m.member_id), tasks=snapshot.tasks.filter(t=>t.owner_member_id===m.member_id);
    if(!sessions.length) activity.append(text('p','尚无 agent 会话登记','muted'));
    sessions.forEach(s => add(activity,add(text('div','','session'),badge(s.tool),text('span',s.branch || '未声明分支'),text('p',(s.repository || '未声明仓库')+' · 会话 '+s.session_key,'meta'),text('p',(s.task_id?'任务：'+taskName(s.task_id)+' · ':'')+'最后登记 '+date(s.updated_at),'meta'))));
    tasks.forEach(t => { const p=snapshot.progress.find(p=>p.task_id===t.id); const line=add(text('p'),badge(p?.state||t.state),text('span',t.title)); if(p) add(line,text('span',' · agent 自述 · '+date(p.updated_at),'meta')); add(activity,line); if(p) add(activity,text('p',p.summary,'progress-summary')); });
    add($('members'),add(row,profile,activity));
  });
  $('overlaps').replaceChildren(); if(!snapshot.overlaps.length) empty($('overlaps'),'当前没有声明范围交叠。');
  const reasons={'Declared scopes are equal':'两项任务声明了相同的工作范围。','One declared scope is a slash-segment prefix of the other':'一项任务的声明范围包含另一项的子路径。'};
  snapshot.overlaps.forEach(o => add($('overlaps'),add(text('article','','record'),text('h3',o.task_ids.map(taskName).join(' × ')),text('p',o.scopes.join(' / '),'meta'),text('p',reasons[o.reason] || o.reason))));
  if($('git-overlaps')){$('git-overlaps').replaceChildren();gitUI()?.renderOverlaps($('git-overlaps'),snapshot.git,taskName);if(!snapshot.git?.overlaps?.length)empty($('git-overlaps'),'当前没有新鲜观测中的实际路径重叠。');}
}
function taskLink(id) { return button('任务：'+taskName(id),()=>{setView('tasks');openTaskDetail(id);},'link-button'); }
const taskColumns = [
  ['open','待认领','明确意图，等待接手'],
  ['working','推进中','agent 正在推进'],
  ['blocked','遇到阻塞','需要团队协助'],
  ['review','待验收','本地完成、已推送或 PR 打开'],
  ['merged','已合并','查看卡片中的交付证据来源'],
  ['cancelled','已取消','保留历史，可重新打开']
];
let activeTaskId=null, taskOpener=null;
function taskColumn(task, progress){
  if(task.cancelled_at||task.state==='cancelled')return 'cancelled';
  if(!task.owner_member_id) return 'open';
  const state=gitUI()?.state(task,progress,snapshot?.git) || progress?.state;
  if(state==='blocked')return 'blocked';
  if(state==='merged')return 'merged';
  if(['local_done','pushed','pr_open'].includes(state))return 'review';
  return 'working';
}
function matchingTasks(tasks, progress, query, owner){
  const needle=query.trim().toLocaleLowerCase();
  return tasks.filter(t=> (!owner || (owner==='unassigned'?!t.owner_member_id:String(t.owner_member_id)===owner)) &&
    (!needle || [t.title,t.scope,t.intent_key,progress.find(p=>p.task_id===t.id)?.summary||''].join(' ').toLocaleLowerCase().includes(needle)));
}
function renderTasks(){
  const selected=$('task-owner').value;
  $('task-owner').replaceChildren();
  [['','所有成员'],['unassigned','待认领'],...snapshot.members.map(m=>[String(m.member_id),m.display_name])].forEach(([value,label])=>{const o=text('option',label);o.value=value;$('task-owner').append(o);});
  $('task-owner').value=selected;
  const filtered=matchingTasks(snapshot.tasks,snapshot.progress,$('task-search').value,$('task-owner').value).filter(t=>lifecycleUI()?.matches(t,$('task-status')?.value||'active')??true);
  $('board-count').textContent=filtered.length+' / '+snapshot.tasks.length+' 项任务';
  $('tasks').replaceChildren();
  taskColumns.forEach(([key,label,note])=>{
    const filter=$('task-status')?.value||'active';
    if((key==='cancelled'&&filter==='active')||(key!=='cancelled'&&filter==='cancelled'))return;
    const column=text('section','','kanban-column column-'+key), list=text('div','','column-cards');
    const tasks=filtered.filter(t=>taskColumn(t,snapshot.progress.find(p=>p.task_id===t.id))===key);
    add(column,add(text('header','','column-heading'),add(text('div'),text('span','','status-dot'),text('h2',label),text('span',tasks.length,'column-count')),text('p',note)),list);
    if(!tasks.length)empty(list,snapshot.tasks.length?'此列暂无匹配任务':'等待第一项工作');
    tasks.forEach(t=>{
      const p=snapshot.progress.find(p=>p.task_id===t.id), requests=snapshot.requests.filter(r=>r.task_id===t.id), card=button('',()=>openTaskDetail(t.id),'task-card');
      card.id='task-'+t.id;card.setAttribute('aria-label','查看任务 #'+t.id+'：'+t.title);
      add(card,add(text('div','','card-top'),text('span','CM-'+String(t.id).padStart(3,'0'),'task-number'),text('span','↗','card-arrow')),text('h3',t.title),text('p',p?.summary||(t.cancelled_at?'任务已取消，可在详情重新打开。':'已声明工作范围，等待 agent 推进。'),'card-summary'),text('p',t.scope,'card-scope'));
      add(card,add(text('div','','card-bottom'),add(text('span','','card-person'),text('span',(t.owner_member_id?memberName(t.owner_member_id):'?').slice(0,1),'avatar'),text('span',t.cancelled_at?'已取消':t.owner_member_id?memberName(t.owner_member_id):'待认领')),text('span',requests.length+' 请求','card-meta')),text('p',date(p?.updated_at||t.cancelled_at||t.claimed_at||t.created_at)+' · '+(t.cancelled_at?'已取消':p?'agent 自述':t.owner_member_id?'已认领':'任务声明'),'card-time'));
      const handoff=snapshot.lifecycle?.handoffs?.find(h=>h.task_id===t.id&&h.status==='pending');if(handoff)card.append(text('p','待 '+memberName(handoff.target_member_id)+' 接手 · '+handoff.summary,'card-summary'));
      const gitSummary=gitUI()?.summarize(t.id,snapshot.git);if(gitSummary)card.append(text('p',gitSummary,'card-git'));
      list.append(card);
    });
    $('tasks').append(column);
  });
  if(activeTaskId!==null) renderTaskDetail();
}
function renderTaskDetail(){
  const t=snapshot?.tasks.find(t=>t.id===activeTaskId); if(!t){closeTaskDetail();return;}
  const container=$('task-detail'), p=snapshot.progress.find(p=>p.task_id===t.id);
  if(container.contains(document.activeElement)&&['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
  const focused=container.contains(document.activeElement)?document.activeElement.textContent:null;
  container.replaceChildren();
  const title=text('h2',t.title);title.id='task-detail-title';
  add(container,text('p','CM-'+String(t.id).padStart(3,'0'),'eyebrow'),title,add(text('p','','detail-status'),badge(gitUI()?.state(t,p,snapshot.git)||p?.state||t.state),text('span',t.cancelled_at?'已取消，恢复后可认领':t.owner_member_id?memberName(t.owner_member_id):'等待 agent 认领')),text('p','声明范围','detail-label'),text('p',t.scope,'detail-value'),text('p','去重标识','detail-label'),text('p',t.intent_key,'detail-value'),text('p','创建 '+date(t.created_at)+(t.claimed_at?' · 认领 '+date(t.claimed_at):''),'meta'));
  if(p)add(container,text('p','最新进展','detail-label'),text('p',p.summary,'detail-value'),text('p','agent 自述 · '+memberName(p.member_id)+' · '+date(p.updated_at),'meta'),text('p','证据：'+(p.evidence||'未提供'),'detail-value'));
  gitUI()?.renderDetails(container,t,snapshot.git,gitContext());
  lifecycleUI()?.renderDetails(container,t,snapshot,gitContext());
  const related=snapshot.requests.filter(r=>r.task_id===t.id);
  add(container,text('p','关联技术请求','detail-label'));
  if(!related.length)empty(container,'尚无关联请求。');
  related.forEach(r=>container.append(button('#'+r.id+' '+r.body,()=>{closeTaskDetail();setView('requests');$('request-'+r.id)?.scrollIntoView({block:'center'});},'detail-link')));
  const contracts=snapshot.contracts.filter(c=>c.versions.some(v=>related.some(r=>r.id===v.source_request_id)));
  add(container,text('p','关联公共约定','detail-label'));
  if(!contracts.length)empty(container,'尚无关联公共约定。');
  contracts.forEach(c=>container.append(button(c.contract_key+' · 生效 '+(c.effective_version?'v'+c.effective_version:'未批准'),()=>{closeTaskDetail();setView('contracts');$('contract-'+c.id)?.scrollIntoView({block:'center'});},'detail-link')));
  if(focused)Array.from(container.querySelectorAll('button')).find(b=>b.textContent===focused)?.focus({preventScroll:true});
}
function openTaskDetail(id){activeTaskId=id;taskOpener=document.activeElement;renderTaskDetail();if(!$('task-dialog').open)$('task-dialog').showModal();}
function closeTaskDetail(){activeTaskId=null;if($('task-dialog').open)$('task-dialog').close();$('task-detail').replaceChildren();}
$('close-task').addEventListener('click',closeTaskDetail);
$('task-dialog').addEventListener('close',()=>{activeTaskId=null;$('task-detail').replaceChildren();const target=taskOpener?.isConnected?taskOpener:$(taskOpener?.id);if(target)target.focus();else $('task-search').focus();taskOpener=null;});
$('task-search').addEventListener('input',()=>{if(snapshot)renderTasks();});
$('task-owner').addEventListener('change',()=>{if(snapshot)renderTasks();});
$('task-status')?.addEventListener('change',()=>{if(snapshot)renderTasks();});
$('new-task').addEventListener('click',()=>{$('task-create').open=true;$('task-form').querySelector('input').focus();});
function renderRequests(){
  $('requests').replaceChildren(); if(!snapshot.requests.length) empty($('requests'),'尚无技术请求。让 agent 在 MCP 入口发送需要协作的具体问题。');
  snapshot.requests.forEach(r => { const row=text('article','','record'); row.id='request-'+r.id; add(row,add(text('div','','record-header'),add(text('div'),badge(r.resolved_at?'已解决':'待解决'),text('span','#'+r.id+' · 上下文 v'+r.context_version,'meta')),text('span',memberName(r.sender_member_id)+' → '+memberName(r.receiver_member_id),'meta')),text('h3',r.body)); if(r.task_id) row.append(taskLink(r.task_id));
    add(row,text('p','发起 '+date(r.created_at)+' · 分派 '+date(r.assigned_at),'meta'),text('p','读取 '+date(r.read_at)+' · 处理 '+date(r.processed_at)+' · 解决 '+date(r.resolved_at),'timeline'));
    if(!r.receiver_member_id && !r.resolved_at){ const form=text('form','','assignment'),label=text('label','分派收件人'),select=document.createElement('select'); select.name='receiver_member_id'; select.required=true; add(select,text('option','选择成员')); select.firstChild.value=''; snapshot.members.forEach(m=>{const o=text('option',m.display_name);o.value=m.member_id;select.append(o);}); label.append(select); const submit=text('button','分派');submit.type='submit'; add(form,label,submit); form.addEventListener('submit',e=>{e.preventDefault(); perform(submit,()=>api('/api/requests/'+r.id+'/assign',{receiver_member_id:select.value}));}); row.append(form); }
    r.replies.forEach(reply=>add(row,add(text('div','','reply'),text('p',memberName(reply.author_member_id)+' · 回复 · '+date(reply.created_at),'meta'),text('p',reply.body),text('p','证据：'+(reply.evidence||'未提供'),'meta'))));
    if(!r.resolved_at && r.replies.length && r.sender_member_id===snapshot.me.member_id) row.append(button('确认请求已解决',e=>perform(e.currentTarget,()=>api('/api/requests/'+r.id+'/resolve',{context_version:r.context_version}))));
    $('requests').append(row);
  });
}
function renderContracts(){
  $('contracts').replaceChildren(); if(!snapshot.contracts.length) empty($('contracts'),'尚无公共约定。agent 提出的版本会在这里等待人工审核。');
  snapshot.contracts.forEach(c => { const row=text('article','','record'); row.id='contract-'+c.id; const head=c.versions.find(v=>v.version===c.current_version); add(row,add(text('div','','record-header'),text('span',c.contract_key,'eyebrow'),text('span','当前 v'+c.current_version+' / '+(c.effective_version?'生效 v'+c.effective_version:'尚未生效'),'meta')),text('h3',head?.title || c.contract_key));
    if(head){ add(row,add(text('p','','record-body'),badge(head.decision || '等待人工审核')),text('p',head.body),text('p','提出人 '+memberName(head.proposer_member_id)+' · '+date(head.created_at)+' · 提交引用 '+(head.commit_ref || '未提供'),'meta')); if(head.source_request_id) row.append(button('来源请求 #'+head.source_request_id,()=>{setView('requests'); $('request-'+head.source_request_id)?.scrollIntoView({block:'center'});},'link-button'));
      if(!head.decision) ['approved','rejected'].forEach(decision=>row.append(button((decision==='approved'?'批准':'拒绝')+' v'+head.version,e=>perform(e.currentTarget,()=>api('/api/contracts/'+c.id+'/decision',{version:head.version,decision})),decision==='approved'?'primary':'danger')));
    }
    add(row,detail('版本记录 · '+c.versions.length+' 个版本',c.versions.slice().reverse().map(v=>add(text('div','','history'),text('h3','v'+v.version+' · '+v.title),badge(v.decision || '待审核'),text('p',v.body),text('p','提出 '+memberName(v.proposer_member_id)+' · '+date(v.created_at)+' / 决定 '+memberName(v.decided_by_member_id)+' · '+date(v.decided_at),'meta'),text('p','提交引用 '+(v.commit_ref||'未提供')+(v.source_request_id?' · 来源请求 #'+v.source_request_id:''),'meta')))));
    const events=snapshot.events.filter(e=>e.contract_id===c.id); if(events.length) add(row,detail('审核事件',events.map(e=>text('p','v'+e.version+' · '+({proposed:'提出',approved:'批准',rejected:'拒绝'}[e.event_type]||e.event_type)+' · '+memberName(e.actor_member_id)+' · '+date(e.created_at),'meta')))); $('contracts').append(row);
  });
}
async function perform(b, operation){ b.disabled=true; $('action-error').textContent=''; const epoch=generation; try { await operation(); if(epoch===generation){ renderSignature=''; await sync(); } } catch(error){ if(epoch===generation) $('action-error').textContent=error.message; } finally{b.disabled=false;} }
$('task-form').addEventListener('submit',e=>{e.preventDefault();const form=e.currentTarget,b=form.querySelector('button[type=submit]'),epoch=generation;perform(b,async()=>{await api('/api/tasks',Object.fromEntries(new FormData(form)));if(epoch===generation)form.reset();});});
$('retry').addEventListener('click',sync); $('logout').addEventListener('click',()=>{if(accountManaged && typeof window!=='undefined')window.CrewmeshAccounts.home();else logout();});
function configTemplate(){const url=location.origin+'/mcp'; const tool=$('connection-tool').value; $('config-template').value=tool==='desktop'?'[mcp_servers.crewmesh]\nurl = "'+url+'"\nhttp_headers = { Authorization = "Bearer TOKEN" }':tool==='cli'?"$env:CREWMESH_AGENT_TOKEN = 'TOKEN'\ncodex mcp add crewmesh --url "+url+' --bearer-token-env-var CREWMESH_AGENT_TOKEN':"claude mcp add --transport http --scope local crewmesh "+url+' --header "Authorization: Bearer TOKEN"';}
async function copy(value){try{await navigator.clipboard.writeText(value);$('dialog-status').textContent='已复制，请妥善保存。';}catch{$('dialog-status').textContent='复制不可用，请选择字段并手动复制。';}}
let dialogOpener=null;
function showPrivate(title, credentials={}) { $('private-content').replaceChildren(); $('private-title').textContent=title; $('dialog-status').textContent=''; $('connection-help').hidden=!!credentials.invite_token;
  for(const [key,label,expiry] of [['invite_token','邀请令牌',credentials.expires_at],['web_token','网页恢复凭据',credentials.web_expires_at],['agent_token','个人 agent 令牌',credentials.agent_expires_at||credentials.expires_at]]) if(credentials[key]) {
    const value=credentials[key],block=text('div','','secret'),l=text('label',label),input=document.createElement('input');input.type='password';input.readOnly=true;input.value=value;input.autocomplete='off';l.append(input);
    add(block,l,button('显示 / 隐藏',()=>{input.type=input.type==='password'?'text':'password';}),button('复制',()=>copy(input.value)),text('p','有效期至 '+date(expiry)+' · 关闭后不再展示','meta')); $('private-content').append(block);
  }
  $('mcp-url').value=location.origin+'/mcp'; configTemplate(); if(!$('private-dialog').open){dialogOpener=document.activeElement;$('private-dialog').showModal();}
  if(snapshot&&!credentials.invite_token)collaborationUI()?.renderSetup($('collaboration-setup'),snapshot,gitContext());
}
function clearPrivate(){ $('private-content').replaceChildren(); $('dialog-status').textContent=''; $('config-template').value=''; $('collaboration-setup')?.replaceChildren(); }
function closePrivate(){if($('private-dialog').open)$('private-dialog').close();clearPrivate();}
$('private-dialog').addEventListener('close',()=>{clearPrivate();if(dialogOpener?.isConnected)dialogOpener.focus();dialogOpener=null;});
$('close-dialog').addEventListener('click',closePrivate); $('connection-button').addEventListener('click',()=>showPrivate('接入自己的 agent'));
$('copy-url').addEventListener('click',()=>copy($('mcp-url').value)); $('connection-tool').addEventListener('change',configTemplate); $('copy-template').addEventListener('click',()=>copy($('config-template').value));
$('invite-button').addEventListener('click',e=>{const epoch=generation;perform(e.currentTarget,async()=>{const result=await api('/api/invites',{});if(epoch===generation)showPrivate('邀请一位团队成员',result);});});
$('rotate-agent').addEventListener('click',async e=>{ const b=e.currentTarget; b.disabled=true;const epoch=generation;try{const result=await api('/api/agent-token',{});if(epoch===generation){showPrivate('保存新的 agent 令牌',result);$('dialog-status').textContent='旧 agent 令牌已立即失效。请更新配置并重建连接。';}}catch(error){if(epoch===generation)$('dialog-status').textContent=error.message;}finally{b.disabled=false;} });
setView('tasks');
if(typeof window!=='undefined') window.CrewmeshProject={
  enter(credential){logout();accountManaged=true;sessionStorage.setItem('crewmesh_account_project','1');enter(credential);},
  clear(){logout();accountManaged=false;},
  private:showPrivate,
  managed(){return accountManaged;}
};
// Account-managed project credentials are reissued only after validating the cookie.
if(token && !sessionStorage.getItem('crewmesh_account_project')) enter(token);
