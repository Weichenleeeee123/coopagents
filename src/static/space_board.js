'use strict';
(() => {
  const $=id=>document.getElementById(id),board=window.CoopagentsBoard;
  const adapters={git:window.CoopagentsGit,dependencies:window.CoopagentsDependencies,open:openTask};
  let token='',snapshot=null,active=null,opener=null,poll=null,stream=null,stopped=false,busy=false,dirty=false,generation=0;
  const requests=new Set();
  let currentView='tasks',contextTab='agreements',taskLayout='board',objectDetail=null;
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
    $('readonly-project-name').textContent=snapshot.room.name;$('readonly-page-project').textContent=snapshot.room.name;$('readonly-repository').textContent=snapshot.room.repository||'未声明仓库';
    renderNavigation();
    const owner=$('task-owner').value;$('task-owner').replaceChildren();
    [['','所有成员'],['unassigned','待认领'],...snapshot.members.map(m=>[String(m.member_id),m.display_name])].forEach(([value,label])=>{const n=node('option',label);n.value=value;$('task-owner').append(n);});$('task-owner').value=owner;
    renderTasks();$('members').replaceChildren();
    snapshot.members.forEach(m=>{const row=node('article','','member-row');row.append(node('h3',m.display_name));snapshot.sessions.filter(s=>s.member_id===m.member_id).forEach(s=>row.append(node('p',s.tool+' · '+(s.branch||'未声明分支')+' · 最后登记 '+time(s.updated_at),'meta')));snapshot.tasks.filter(t=>t.owner_member_id===m.member_id).forEach(t=>{const p=snapshot.progress.find(p=>p.task_id===t.id);row.append(node('p',t.title+' · '+(p?.summary||'尚无进展')+' · agent 自述 '+time(p?.updated_at)));});$('members').append(row);});
    $('requests').replaceChildren(...snapshot.requests.map(r=>board.requestSummary?board.requestSummary(r,snapshot,{open:()=>openObject('request',r.id)}):board.request(r,snapshot)));$('contracts').replaceChildren(...snapshot.contracts.map(c=>board.contractSummary?board.contractSummary(c,{open:()=>openObject('contract',c.id)}):board.contract(c)));renderContextTab();renderAssets();renderSettings();
    const epoch=generation,links={overview:'概览',tasks:'任务',requests:'协作',contracts:'共享上下文',delivery:'交付',members:'成员与 agent',settings:'项目设置',activity:'活动'};
    window.CoopagentsSharedContext?.render($('shared-context'),snapshot.shared_context,{roomId:snapshot.me.room_id,tasks:snapshot.tasks,members:snapshot.members,openTask,isCurrent:()=>epoch===generation&&!stopped,query:filters=>request('/board/context?'+new URLSearchParams(filters))});
    window.CoopagentsDeliveryGraph?.render($('delivery-traceability'),snapshot.git?.delivery_graph,snapshot.git,{roomId:snapshot.me.room_id,readOnly:true,openNode:(_key,node)=>openDelivery(node),openTask,taskName:id=>snapshot.tasks.find(t=>t.id===id)?.title||'任务 #'+id});
    window.CoopagentsCapabilities?.render($('capability-discovery'),snapshot.capabilities,{roomId:snapshot.me.room_id,openTask,showMatrix:false});
    window.CoopagentsProjectActivity?.render($('project-activity'),snapshot.activity);
    renderOverview();if(objectDetail)renderObject();
  }
  function showView(view,closeNavigation=true){
    const nav=$('board-navigation');if(!nav)return;currentView=view;if(closeNavigation)setNavigation(false);
    $('readonly-crumb-page').textContent=({overview:'概览',tasks:'任务',requests:'协作',contracts:'共享上下文',delivery:'交付',members:'成员与 agent',settings:'项目设置',activity:'项目活动'})[view];
    const filters=$('readonly-task-filters');if(filters)filters.hidden=view!=='tasks';
    const title=$('readonly-view-title');if(title)title.textContent=({overview:'概览',tasks:'任务',requests:'协作',contracts:'共享上下文',delivery:'交付',members:'成员与 agent',settings:'项目设置',activity:'项目活动'})[view];
    for(const key of ['overview','tasks','requests','contracts','delivery','members','settings','activity']){const target=$('readonly-page-'+key);if(target)target.hidden=key!==view;}
    nav.querySelectorAll('button').forEach(button=>{if(button.dataset.view===view)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  }
  function renderNavigation(){
    const nav=$('board-navigation');if(!nav)return;
    nav.replaceChildren();for(const [view,label] of Object.entries({overview:'概览',tasks:'任务',requests:'协作',contracts:'共享上下文',delivery:'交付',members:'成员与 agent',settings:'项目设置'})){const b=node('button',label);b.type='button';b.dataset.view=view;if(document.createElementNS){const paths={overview:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',tasks:'M4 5h4v4H4zM12 6h9M12 13h9M12 20h9M3 18l2 2 4-5',requests:'M3 3h15v11H8l-5 5zM12 18h6l3 3V9',contracts:'M4 3v18M9 7v14M14 5v16M19 7l3 14',delivery:'M6 3v18M9 6h8v9M6 3a3 3 0 1 0 0 6 3 3 0 1 0 0-6M17 15a3 3 0 1 0 0 6 3 3 0 1 0 0-6',members:'M3 21v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3M9 3a4 4 0 1 0 0 8 4 4 0 1 0 0-8M18 14a4 4 0 0 1 3 4v3',settings:'M3 7h18M3 17h18M7 4v6M17 14v6'};const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');for(const [key,value]of Object.entries({viewBox:'0 0 24 24',width:'18',height:'18',fill:'none',stroke:'currentColor','stroke-width':'1.6','aria-hidden':'true'}))svg.setAttribute(key,value);path.setAttribute('d',paths[view]);svg.append(path);b.textContent='';b.append(svg,node('span',label));}b.addEventListener('click',()=>showView(view));nav.append(b);}showView(currentView,false);
  }
  function renderOverview(){const root=$('readonly-page-overview');if(!root)return;root.replaceChildren();const tasks=snapshot.tasks.length,requests=snapshot.requests.filter(r=>!r.resolved_at).length,assets=snapshot.assets?.length||0;const stats=node('div','','summary-strip');for(const [value,label] of [[tasks,'项目任务'],[requests,'未解决请求'],[assets,'共享文件'],[snapshot.members.length,'项目成员']]){const card=node('div','','metric');card.append(node('strong',String(value)),node('span',label));stats.append(card);}root.append(stats,node('h2','当前项目'),node('p',snapshot.room.repository||snapshot.room.name,'view-note'));for(const [view,label,items]of [['tasks','查看任务',tasks],['requests','查看协作',requests],['delivery','查看交付',snapshot.git?.delivery_graph?.items?.length||0],['members','查看成员与 agent',snapshot.members.length]]){const b=node('button',label+' · '+items);b.type='button';b.addEventListener('click',()=>showView(view));root.append(b);}}
  function renderTasks(){
    if(!snapshot)return;
    const focused=document.activeElement?.id,filter=$('task-status').value;
    const tasks=board.matchingTasks(snapshot.tasks,snapshot.progress,$('task-search').value,$('task-owner').value).filter(t=>filter==='all'||((!!t.cancelled_at||t.state==='cancelled')===(filter==='cancelled')));
    $('board-count').textContent=tasks.length+' / '+snapshot.tasks.length+' 项任务';$('tasks').replaceChildren();
    if(taskLayout==='list'&&board.table){$('tasks').className='task-list';$('tasks').append(board.table(tasks,snapshot,adapters));}
    else {$('tasks').className='kanban-board';board.columns.forEach(([key,label,note])=>{
      if(filter==='active'&&key==='cancelled'||filter==='cancelled'&&key!=='cancelled')return;
      const column=node('section','','kanban-column column-'+key),heading=node('header','','column-heading'),list=node('div','','column-cards'),items=tasks.filter(t=>board.column(t,snapshot.progress.find(p=>p.task_id===t.id),snapshot,adapters)===key);
      heading.append(node('h2',label+' · '+items.length),node('p',note));column.append(heading,list);items.forEach(t=>list.append(board.card(t,snapshot.progress.find(p=>p.task_id===t.id),snapshot,adapters)));if(!items.length)list.append(node('p','此列暂无任务','empty'));$('tasks').append(column);
    });
    }
    if(focused?.startsWith('task-')&&focused!=='task-search')$(focused)?.focus({preventScroll:true});if(active!==null)renderDetail();
  }
  function renderDetail(){const t=snapshot.tasks.find(t=>t.id===active);if(!t){$('task-dialog').close();return;}$('task-detail').replaceChildren(board.readonlyDetail(t,snapshot.progress.find(p=>p.task_id===t.id),snapshot,adapters));}
  function openTask(id){objectDetail=null;active=id;opener=document.activeElement;renderDetail();if(!$('task-dialog').open)$('task-dialog').showModal();}
  function setNavigation(open){$('readonly-shell')?.setAttribute('data-navigation-open',String(open));$('readonly-mobile-menu')?.setAttribute('aria-expanded',String(open));}
  $('readonly-mobile-menu')?.addEventListener('click',()=>setNavigation($('readonly-mobile-menu').attributes?.['aria-expanded']!=='true'&&$('readonly-mobile-menu').getAttribute?.('aria-expanded')!=='true'));
  $('readonly-sidebar')?.addEventListener('keydown',event=>{if(event.key==='Escape'){setNavigation(false);$('readonly-mobile-menu').focus();}});
  function renderContextTab(){for(const [tab,id] of [['agreements','contracts'],['files','readonly-assets'],['records','shared-context']]){$(id).hidden=contextTab!==tab;const button=$('readonly-context-'+tab);if(contextTab===tab)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');}}
  for(const tab of ['agreements','files','records'])$('readonly-context-'+tab)?.addEventListener('click',()=>{contextTab=tab;renderContextTab();});
  for(const layout of ['board','list'])$('readonly-layout-'+layout)?.addEventListener('click',()=>{taskLayout=layout;for(const key of ['board','list']){if(key===layout)$('readonly-layout-'+key).setAttribute('aria-current','page');else $('readonly-layout-'+key).removeAttribute('aria-current');}renderTasks();});
  function openObject(kind,id){active=null;objectDetail={kind,id};opener=document.activeElement;renderObject();if(!$('task-dialog').open)$('task-dialog').showModal();}
  function renderObject(){if(!objectDetail)return;const {kind,id}=objectDetail,item=(kind==='request'?snapshot.requests:snapshot.contracts).find(n=>n.id===id);if(!item){$('task-dialog').close();return;}const title=node('h2',kind==='request'?'协作请求 #'+id:item.contract_key);title.id='task-detail-title';$('task-detail').replaceChildren(title,kind==='request'?board.request(item,snapshot):board.contract(item));}
  function openDelivery(item){active=null;objectDetail=null;opener=document.activeElement;const title=node('h2',item.label);title.id='task-detail-title';const root=$('task-detail');root.replaceChildren(title,node('p',item.title,'detail-value'),node('p','来源 '+item.source,'meta'));for(const id of item.task_ids||[]){const b=node('button','任务 #'+id,'detail-link');b.type='button';b.addEventListener('click',()=>openTask(id));root.append(b);}for(const a of item.associations||[])root.append(node('p',a.evidence||a.source,'meta'));if(!$('task-dialog').open)$('task-dialog').showModal();}
  function renderAssets(){const root=$('readonly-assets');root.replaceChildren();for(const asset of snapshot.assets||[]){const row=node('article','','content-row'),body=node('div','','row-content');body.append(node('h3',asset.filename),node('p',(asset.media_type||'文件')+' · '+asset.size_bytes+' bytes','meta'),node('p',asset.source_ref||'成员上传','meta'));row.append(body);root.append(row);}if(!root.children.length)root.append(node('p','暂时没有共享文件。','empty'));}
  function renderSettings(){const root=$('readonly-settings');root.replaceChildren(node('h2','代码仓库'),node('p',snapshot.git?.binding?.repository||snapshot.room.repository||'尚未绑定仓库','git-repository'),node('p','当前为只读查看会话。连接配置由主机或项目管理者维护。','meta'));const activity=node('button','查看项目活动','link-button');activity.type='button';activity.addEventListener('click',()=>showView('activity'));root.append(activity);}
  $('close-task').addEventListener('click',()=>$('task-dialog').close());$('task-dialog').addEventListener('close',()=>{active=null;objectDetail=null;$('task-detail').replaceChildren();(opener?.isConnected?opener:$(opener?.id)||$('task-search')).focus();opener=null;});
  ['task-search','task-owner','task-status'].forEach(id=>$(id).addEventListener(id==='task-search'?'input':'change',renderTasks));$('refresh').addEventListener('click',refresh);
  function retire(){generation++;stopped=true;token='';clearTimeout(poll);stream?.close();stream=null;requests.forEach(controller=>controller.abort());requests.clear();}
  window.addEventListener('pagehide',retire);
  window.addEventListener('hashchange',()=>{if(location.hash.length>1)start();});
  async function start(){
    const ticket=location.hash.slice(1);history.replaceState(null,'',location.pathname);
    if(!ticket){$('board-error').textContent='请由主机 agent 使用 board 命令打开一次性看板地址。';return;}
    retire();const epoch=generation;stopped=false;busy=false;dirty=false;snapshot=null;active=null;objectDetail=null;currentView='tasks';contextTab='agreements';taskLayout='board';
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
