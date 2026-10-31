'use strict';
(() => {
  const $=id=>document.getElementById(id),board=window.CoopagentsBoard;
  const adapters={git:window.CoopagentsGit,dependencies:window.CoopagentsDependencies,open:openTask};
  let token='',snapshot=null,active=null,opener=null,poll=null,stream=null,stopped=false,busy=false,dirty=false,generation=0;
  const requests=new Set();
  const node=(tag,value='',cls)=>{const n=document.createElement(tag);n.textContent=value??'';if(cls)n.className=cls;return n;};
  const time=value=>value?new Date(value).toLocaleString('zh-CN'):'—';
  function status(value){$('transport-status').textContent=value==='online'?'实时连接在线 · 事件更新不代表模型已读取':value==='denied'?'查看会话已失效，请由主机重新打开看板':'实时连接中断 · 每 5 秒轮询恢复';}
  async function request(path,body){
    const epoch=generation,controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
    requests.add(controller);
    try{
      const headers={};if(token)headers.Authorization='Bearer '+token;if(body)headers['Content-Type']='application/json';
      const response=await fetch(path,{method:body?'POST':'GET',headers,body:body?JSON.stringify(body):undefined,signal:controller.signal,cache:'no-store'});
      if(epoch!==generation)throw new Error('查看会话已切换');
      if([401,403].includes(response.status)){stopped=true;token='';clearTimeout(poll);stream?.close();status('denied');throw new Error('查看会话无效，请重新打开');}
      if(!response.ok)throw new Error('连接失败（'+response.status+'）');
      const result=await response.json();if(epoch!==generation)throw new Error('查看会话已切换');return result;
    }finally{clearTimeout(timeout);requests.delete(controller);}
  }
  async function refresh(){
    if(!token||stopped)return;dirty=true;if(busy)return;busy=true;const epoch=generation;
    try{while(dirty&&!stopped&&epoch===generation){dirty=false;try{const result=await request('/board/snapshot');if(stopped||epoch!==generation)return;snapshot=result;$('board-error').textContent='';render();}catch(error){if(!stopped&&epoch===generation){status('degraded');$('board-error').textContent=error.message+'。保留上次数据。';}}}}
    finally{if(epoch===generation){busy=false;if(!stopped){clearTimeout(poll);poll=setTimeout(()=>{if(epoch===generation)refresh();},5000);}}}
  }
  function render(){
    $('room-name').textContent=snapshot.room.name;
    $('readonly-project-name').textContent=snapshot.room.name;
    renderNavigation();
    const owner=$('task-owner').value;$('task-owner').replaceChildren();
    [['','所有成员'],['unassigned','待认领'],...snapshot.members.map(m=>[String(m.member_id),m.display_name])].forEach(([value,label])=>{const n=node('option',label);n.value=value;$('task-owner').append(n);});$('task-owner').value=owner;
    renderTasks();$('members').replaceChildren();
    snapshot.members.forEach(m=>{const row=node('article','','member-row');row.append(node('h3',m.display_name));snapshot.sessions.filter(s=>s.member_id===m.member_id).forEach(s=>row.append(node('p',s.tool+' · '+(s.branch||'未声明分支')+' · 最后登记 '+time(s.updated_at),'meta')));snapshot.tasks.filter(t=>t.owner_member_id===m.member_id).forEach(t=>{const p=snapshot.progress.find(p=>p.task_id===t.id);row.append(node('p',t.title+' · '+(p?.summary||'尚无进展')+' · agent 自述 '+time(p?.updated_at)));});$('members').append(row);});
    $('requests').replaceChildren(...snapshot.requests.map(r=>board.request(r,snapshot)));$('contracts').replaceChildren(...snapshot.contracts.map(board.contract));
    const epoch=generation,links={overview:'概览',tasks:'任务',requests:'协作',contracts:'共享上下文',delivery:'交付',members:'成员与 agent',settings:'项目设置',activity:'活动'};
    window.CoopagentsSharedContext?.render($('shared-context'),snapshot.shared_context,{roomId:snapshot.me.room_id,tasks:snapshot.tasks,members:snapshot.members,openTask,isCurrent:()=>epoch===generation&&!stopped,query:filters=>request('/board/context?'+new URLSearchParams(filters))});
    window.CoopagentsDeliveryGraph?.render($('delivery-traceability'),snapshot.git?.delivery_graph,{roomId:snapshot.me.room_id,readOnly:true,git:snapshot.git,openTask,taskName:id=>snapshot.tasks.find(t=>t.id===id)?.title||'任务 #'+id});
    window.CoopagentsCapabilities?.render($('capability-discovery'),snapshot.capabilities,{roomId:snapshot.me.room_id,openTask});
    window.CoopagentsProjectActivity?.render($('project-activity'),snapshot.activity);
    renderOverview();
  }
  function showView(view){
    const nav=$('board-navigation');if(!nav)return;
    for(const key of ['overview','tasks','requests','contracts','delivery','members','settings','activity']){const target=$('readonly-page-'+key);if(target)target.hidden=key!==view;}
    nav.querySelectorAll('button').forEach(button=>{if(button.dataset.view===view)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  }
  function renderNavigation(){
    const nav=$('board-navigation');if(!nav)return;
    nav.replaceChildren();for(const [view,label] of Object.entries({overview:'概览',tasks:'任务',requests:'协作',contracts:'共享上下文',delivery:'交付',members:'成员与 agent',settings:'项目设置',activity:'活动'})){const b=node('button',label);b.type='button';b.dataset.view=view;b.addEventListener('click',()=>showView(view));nav.append(b);}showView('overview');
  }
  function renderOverview(){const root=$('readonly-page-overview');if(!root)return;root.replaceChildren();const tasks=snapshot.tasks.length,requests=snapshot.requests.filter(r=>!r.resolved_at).length,assets=snapshot.assets?.length||0;const stats=node('div','','summary-strip');for(const [value,label] of [[tasks,'项目任务'],[requests,'未解决请求'],[assets,'共享文件'],[snapshot.members.length,'项目成员']]){const card=node('div','','metric');card.append(node('strong',String(value)),node('span',label));stats.append(card);}root.append(stats,node('h2','当前项目'),node('p',snapshot.room.repository||snapshot.room.name,'view-note'));for(const [view,label,items]of [['tasks','查看任务',tasks],['requests','查看协作',requests],['delivery','查看交付',snapshot.git?.delivery_graph?.items?.length||0],['members','查看成员与 agent',snapshot.members.length]]){const b=node('button',label+' · '+items);b.type='button';b.addEventListener('click',()=>showView(view));root.append(b);}}
  function renderTasks(){
    if(!snapshot)return;
    const focused=document.activeElement?.id,filter=$('task-status').value;
    const tasks=board.matchingTasks(snapshot.tasks,snapshot.progress,$('task-search').value,$('task-owner').value).filter(t=>filter==='all'||((!!t.cancelled_at||t.state==='cancelled')===(filter==='cancelled')));
    $('board-count').textContent=tasks.length+' / '+snapshot.tasks.length+' 项任务';$('tasks').replaceChildren();
    board.columns.forEach(([key,label,note])=>{
      if(filter==='active'&&key==='cancelled'||filter==='cancelled'&&key!=='cancelled')return;
      const column=node('section','','kanban-column column-'+key),heading=node('header','','column-heading'),list=node('div','','column-cards'),items=tasks.filter(t=>board.column(t,snapshot.progress.find(p=>p.task_id===t.id),snapshot,adapters)===key);
      heading.append(node('h2',label+' · '+items.length),node('p',note));column.append(heading,list);items.forEach(t=>list.append(board.card(t,snapshot.progress.find(p=>p.task_id===t.id),snapshot,adapters)));if(!items.length)list.append(node('p','此列暂无任务','empty'));$('tasks').append(column);
    });
    if(focused?.startsWith('task-')&&focused!=='task-search')$(focused)?.focus({preventScroll:true});if(active!==null)renderDetail();
  }
  function renderDetail(){const t=snapshot.tasks.find(t=>t.id===active);if(!t){$('task-dialog').close();return;}$('task-detail').replaceChildren(board.readonlyDetail(t,snapshot.progress.find(p=>p.task_id===t.id),snapshot,adapters));}
  function openTask(id){active=id;opener=document.activeElement;renderDetail();if(!$('task-dialog').open)$('task-dialog').showModal();}
  $('close-task').addEventListener('click',()=>$('task-dialog').close());$('task-dialog').addEventListener('close',()=>{active=null;$('task-detail').replaceChildren();(opener?.isConnected?opener:$(opener?.id)||$('task-search')).focus();opener=null;});
  ['task-search','task-owner','task-status'].forEach(id=>$(id).addEventListener(id==='task-search'?'input':'change',renderTasks));$('refresh').addEventListener('click',refresh);
  function retire(){generation++;stopped=true;token='';clearTimeout(poll);stream?.close();stream=null;requests.forEach(controller=>controller.abort());requests.clear();}
  window.addEventListener('pagehide',retire);
  window.addEventListener('hashchange',()=>{if(location.hash.length>1)start();});
  async function start(){
    const ticket=location.hash.slice(1);history.replaceState(null,'',location.pathname);
    if(!ticket){$('board-error').textContent='请由主机 agent 使用 board 命令打开一次性看板地址。';return;}
    retire();const epoch=generation;stopped=false;busy=false;dirty=false;snapshot=null;active=null;
    if($('task-dialog').open)$('task-dialog').close();
    ['tasks','members','requests','contracts','task-detail','project-activity','shared-context','capability-discovery','delivery-traceability'].forEach(id=>$(id).replaceChildren());
    $('room-name').textContent='团队协作';$('board-count').textContent='';$('board-error').textContent='';$('transport-status').textContent='正在连接…';
    try{
      const result=await request('/board/session',{ticket});if(epoch!==generation||stopped)return;token=result.token;
      status('degraded');stream=window.CoopagentsRealtime.connect({token,refresh:()=>epoch===generation?refresh():Promise.resolve(),status:value=>{if(epoch===generation)status(value);}});await refresh();
    }catch(error){if(epoch===generation)$('board-error').textContent=error.message;}
  }
  start();
})();
