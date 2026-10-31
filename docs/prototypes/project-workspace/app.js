'use strict';
(() => {
  const M=window.WorkspaceModel,$=id=>document.getElementById(id),page=$('page'),toast=$('toast');
  const labels={overview:'概览',tasks:'任务',collaboration:'协作',context:'共享上下文',delivery:'交付',members:'成员与 agent',settings:'项目设置',projects:'全部项目',team:'团队管理',account:'个人账号'};
  const taskState={open:'待认领',working:'推进中',blocked:'遇到阻塞',review:'待验收',merged:'已合并'};
  const requestState={waiting:'等待回复',replied:'已有回复 · 待确认解决',resolved:'已解决'};
  const relationType={pr:'Pull request',branch:'Branch',commit:'Commit',release:'Release'};
  let route=M.parseRoute(location.hash),drawerHistory=false,mobileOpen=false,toastTimer=0;
  const viewDraft={};
  function node(tag,content='',className='') {const n=document.createElement(tag);if(content!==undefined&&content!==null)n.textContent=String(content);if(className)n.className=className;return n;}
  function append(parent,...children){for(const child of children)if(child)parent.append(child);return parent;}
  function icon(name){return window.WorkspaceIcon(name);}
  function button(title,action,className=''){const b=node('button',title,className);b.type='button';b.addEventListener('click',action);return b;}
  function link(title,href,className='link'){const a=node('a',title,className);a.href=href;return a;}
  function meta(title){return node('p',title,'meta');}
  function getProject(){return M.projects.find(p=>p.id===route.project)||M.projects[0];}
  function ownerName(project,id){return project.members.find(m=>m.id===id)?.name||'未认领';}
  function status(value,label){const s=node('span','',`status ${value||''}`);append(s,node('i','','status-dot'),node('span',label));return s;}
  function badge(text,good=false){return node('span',text,'badge'+(good?' good':''));}
  function switchRoute(next,replace=false){const url=M.routeURL({...route,...next});if(replace)history.replaceState(history.state,'',url);else location.hash=url;}
  function navigate(view,extra={}){drawerHistory=false;switchRoute({view,tab:M.tabs[view]?.[0]||'',item:'',...extra});closeMobile();}
  function updateProjectChrome(project){
    const picker=$('project-switch');picker.replaceChildren();picker.append(node('span',project.name.slice(0,1),'project-glyph '+project.color));
    const name=node('span');append(name,node('strong',project.name),node('small',project.repository||project.team,'meta'));append(picker,name,icon('switch'));
    picker.setAttribute('aria-label','切换项目，当前项目：'+project.name);
    $('project-nav').replaceChildren();
    for(const id of ['overview','tasks','collaboration','context','delivery','members']){
      const a=link(labels[id],M.routeURL({project:project.id,view:id,tab:M.tabs[id][0],item:'',mode:route.mode}),'nav-link'+(route.view===id?' active':''));
      if(route.view===id)a.setAttribute('aria-current','page');
      a.prepend(icon(id));
      const count=id==='collaboration'?project.requests.filter(r=>r.state!=='resolved').length:id==='tasks'?project.tasks.filter(t=>t.state==='blocked').length:0;
      if(count)a.append(node('span',count,'nav-count'));
      $('project-nav').append(a);
    }
    const utility=$('utility-nav');utility.replaceChildren();
    for(const id of ['settings','team','projects']){
      const a=link(id==='projects'?'全部项目':id==='team'?'团队管理':'项目设置',M.routeURL({project:project.id,view:id,tab:(M.tabs[id]||[''])[0],item:'',mode:route.mode}),'nav-link'+(['settings','team','projects'].includes(route.view)&&route.view===id?' active':''));
      if(route.view===id)a.setAttribute('aria-current','page');a.prepend(icon(id==='projects'?'overview':'settings'));utility.append(a);
    }
    const member=M.currentUser;const account=button('',()=>navigate('account'),'account-entry');append(account,node('span',member.initial,'avatar '+member.color),node('span',member.name,'account-name'),icon('switch'));$('account-menu').replaceChildren(account);
    const bread=$('breadcrumbs');bread.replaceChildren();
    if(route.view==='team'||route.view==='account'||route.view==='projects'){
      append(bread,link(project.team,M.routeURL({...route,view:'team',tab:'members',item:''})),icon('right'),node('span',labels[route.view],'current'));
    }else{
      append(bread,link(project.team,M.routeURL({...route,view:'projects',tab:'',item:''}),'team-crumb'),icon('right'),link(project.name,M.routeURL({...route,view:'overview',tab:'summary',item:''})),icon('right'),node('span',route.item?'详情':labels[route.view],'current'));
    }
    const mode=$('mode-button');mode.textContent=route.mode==='read'?'只读预览':'演示编辑';mode.className=route.mode==='read'?'read-only':'quiet';mode.title='切换编辑/只读预览';
    $('mobile-menu').setAttribute('aria-expanded',String(mobileOpen));
  }
  function pageHeading(title,sub='',actions=[]){
    const h=node('header','','page-heading'),left=node('div');append(left,node('p',getProject().name,'label'),node('h1',title));if(sub)left.append(node('p',sub,'subline'));const right=node('div','','actions');for(const a of actions)right.append(a);return append(h,left,right);
  }
  function sectionTitle(title,action,href){const h=node('div','','section-title');h.append(node('h2',title));if(action)h.append(link(action,href));return h;}
  function stat(label,value,sub=''){const d=node('div','','stat'),s=node('strong',value);append(d,s,node('span',label));if(sub)d.append(meta(sub));return d;}
  function person(project,id){const m=project.members.find(x=>x.id===id);if(!m)return node('span','未认领','muted');const p=node('span','','person');append(p,node('span',m.initial,'avatar '+m.color),node('span',m.name));return p;}
  function taskAnchor(project,task,context){return link(task.key+' · '+task.title,M.routeURL({...route,project:project.id,view:'tasks',tab:route.mode==='read'?'list':route.tab,item:'task:'+task.id}),context?'detail-link':'inline-link');}
  function openItem(item){if(route.mode==='read'&&item.startsWith('agent:')){}drawerHistory=true;switchRoute({item});}
  function openAction(title,body,submitLabel,submit){
    $('action-title').textContent=title;const content=$('action-content');content.replaceChildren();content.append(body);
    const actions=node('div','','form-actions'),cancel=button('取消',()=>$('action-dialog').close());actions.append(cancel);
    if(submitLabel){const save=button(submitLabel,()=>{const result=submit();if(result!==false){$('action-dialog').close();toastMessage('演示操作已更新：只保留在当前页面。');render();}} ,'primary');actions.append(save);}
    content.append(actions);$('action-dialog').showModal();
  }
  function toastMessage(value){toast.textContent=value;toast.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.hidden=true,2600);}
  function newTask(){
    const form=node('form');form.addEventListener('submit',e=>e.preventDefault());
    for(const [name,label,placeholder] of [['title','任务标题','例如：检查共享记录的引用范围'],['scope','声明范围','例如 src/context'],['intent_key','去重标识','例如 context-reference-review']]){const wrap=node('label',label,'form-field'),input=node('input');input.name=name;input.required=true;input.placeholder=placeholder;wrap.append(input);form.append(wrap);}
    openAction('新建任务',form,'创建任务',()=>{const data=Object.fromEntries(new FormData(form));if(!data.title||!data.scope||!data.intent_key)return false;const p=getProject(),id='new'+Date.now();p.tasks.unshift({id,key:'CP-0'+(30+p.tasks.length),title:data.title,state:'open',owner:'',scope:data.scope,summary:'刚刚创建 · 演示任务',time:'刚刚',branch:'',evidence:'仅保存在本地原型内存。'});return true;});
  }
  function renderOverview(project){
    const pending=project.requests.filter(r=>r.state!=='resolved');const blocked=project.tasks.filter(t=>t.state==='blocked');
    page.append(pageHeading('概览','项目状况与需要留意的事项'));
    if(!project.tasks.length){page.append(emptyState('项目还没有协作记录','这里会汇总任务、需要回应的事项和最近活动。先浏览空项目结构，或切换到其他演示项目。',null));return;}
    const stats=node('section','','stats');append(stats,stat('进行中的任务',project.tasks.filter(t=>t.state!=='merged').length),stat('需要回应',pending.filter(r=>r.state==='waiting').length),stat('待确认约定',project.contracts.filter(c=>c.state==='pending').length),stat('交付对象',project.deliveries.length));page.append(stats);
    const grid=node('div','','overview-grid'),main=node('div','','overview-main'),side=node('div');
    main.append(sectionTitle('需要关注','查看协作',M.routeURL({...route,view:'collaboration',tab:'open',item:''})));
    const attention=node('div','','list');
    for(const r of pending.filter(x=>x.state==='waiting').slice(0,3)){const row=link('',M.routeURL({...route,view:'collaboration',tab:'open',item:'request:'+r.id}),'attention-row');append(row,node('i','','status-dot'),append(node('div'),node('h3',r.title),meta(`${ownerName(project,r.from)} → ${ownerName(project,r.to)} · ${r.key}`)),icon('right'));attention.append(row);}
    for(const t of blocked.slice(0,2)){const row=link('',M.routeURL({...route,view:'tasks',tab:'list',item:'task:'+t.id}),'attention-row');append(row,node('i','','status-dot'),append(node('div'),node('h3',t.title),meta(`${ownerName(project,t.owner)} · 等待协作回应`)),icon('right'));attention.append(row);}
    if(!attention.children.length)attention.append(emptyState('暂时没有需要处理的事项','新活动出现时会在这里提供直达入口。'));
    main.append(attention);
    const recent=project.activity.slice(0,4),recentBox=node('div','','list');for(const e of recent){const config={task:['tasks','list'],request:['collaboration','all'],contract:['context','agreements'],file:['context','files'],delivery:['delivery','all']}[e.type]||['overview','activity'],href=M.routeURL({...route,view:config[0],tab:config[1],item:e.target||''});const row=link('',href,'activity-row');append(row,icon(({task:'tasks',request:'collaboration',contract:'context',file:'file',delivery:'delivery'}[e.type]||'overview')),append(node('div'),node('h3',e.title),meta(e.detail)),node('time',e.time));recentBox.append(row);}
    side.append(sectionTitle('最近变化','完整活动',M.routeURL({...route,tab:'activity',view:'overview',item:''})),recentBox);
    const facts=node('section','','project-facts');facts.append(sectionTitle('项目信息'));append(facts,append(node('div','','fact'),node('span','代码仓库'),node('span',project.repository||'尚未绑定')) ,append(node('div','','fact'),node('span','项目成员'),node('span',project.members.length+' 人')),append(node('div','','fact'),node('span','Agent 会话'),node('span',project.members.reduce((n,m)=>n+m.agents.length,0)+' 个')));side.append(facts);
    grid.append(main,side);page.append(grid);
  }
  function taskFilters(project,compact=false){
    const state=viewDraft[project.id]?.taskState||'active',owner=viewDraft[project.id]?.taskOwner||'',query=viewDraft[project.id]?.query||'';const bar=node('div','','toolbar');
    const search=node('label','','search-field');append(search,icon('search'));const input=node('input');input.type='search';input.placeholder='搜索标题、范围与进展';input.value=query;input.addEventListener('input',()=>{viewDraft[project.id]={...viewDraft[project.id],query:input.value};update();});search.append(input);bar.append(search);
    const statuses=node('select');statuses.setAttribute('aria-label','任务状态');for(const [v,l] of [['active','进行中的任务'],['all','全部任务'],['blocked','遇到阻塞']]){const o=node('option',l);o.value=v;statuses.append(o);}statuses.value=state;statuses.addEventListener('change',()=>{viewDraft[project.id]={...viewDraft[project.id],taskState:statuses.value};update();});bar.append(statuses);
    const owners=node('select');owners.setAttribute('aria-label','负责人');const all=node('option','所有成员');all.value='';owners.append(all);for(const m of project.members){const o=node('option',m.name);o.value=m.id;owners.append(o);}owners.value=owner;owners.addEventListener('change',()=>{viewDraft[project.id]={...viewDraft[project.id],taskOwner:owners.value};update();});bar.append(owners);
    const count=node('span','','result-count');bar.append(count);let update=()=>{};
    return {bar,count,state,owner,query,bind(fn){update=fn;}};
  }
  function taskRows(project,rows){
    const wrap=node('div','','table-wrap'),table=node('table','','task-table'),thead=node('thead'),hr=node('tr');
    for(const [label,cls] of [['工作项','task-col'],['状态','state-col'],['负责人','owner-col'],['更新时间','time-col'],['','end-col']])hr.append(node('th',label,cls));thead.append(hr);const body=node('tbody');
    for(const t of rows){const tr=node('tr');
      const title=node('td'),a=link('',M.routeURL({...route,project:project.id,view:'tasks',tab:route.tab||'list',item:'task:'+t.id}),'title-link');append(a,node('span',t.key,'task-ref'),node('strong',t.title),meta(t.summary));title.append(a);
      const state=node('td');state.append(status(t.state,taskState[t.state]||t.state));
      const owner=node('td');owner.append(person(project,t.owner));const time=node('td',t.time,'time-cell muted');const more=node('td','','end-cell');more.append(link('查看',a.href,'inline-link'));
      append(tr,title,state,owner,time,more);body.append(tr);
    }
    if(!rows.length){const tr=node('tr'),td=node('td');td.colSpan=5;td.append(emptyState('没有匹配的任务','修改搜索或筛选条件。'));tr.append(td);body.append(tr);}
    append(table,thead,body);wrap.append(table);return wrap;
  }
  function renderTasks(project){
    const remembered=page.scrollTop;page.replaceChildren();const actions=route.mode==='edit'?[button('新建任务',newTask,'primary')]:[node('span','只读','read-only')];
    page.append(pageHeading('任务','按负责人和当前状态查看项目工作',actions));
    const tabs=node('nav','','tabs');for(const tab of M.tabs.tasks){const a=link(tab==='list'?'列表':'看板',M.routeURL({...route,tab,item:''}),'tab');if(route.tab===tab)a.setAttribute('aria-current','page');tabs.append(a);}page.append(tabs);
    if(route.tab==='board'){const board=node('div','','board');for(const [state,label] of [['open','待认领'],['working','推进中'],['blocked','遇到阻塞'],['review','待验收'],['merged','已合并']]){const col=node('section','','board-column'),head=node('h3','','column-heading'),items=project.tasks.filter(t=>t.state===state);append(head,node('span',label),node('span',items.length,'meta'));col.append(head);for(const t of items){const a=link('',M.routeURL({...route,item:'task:'+t.id}),'task-card');append(a,node('span',t.key,'task-ref'),node('h3',t.title),meta(t.summary),append(node('div','','card-foot'),person(project,t.owner),status(t.state,taskState[t.state])));col.append(a);}board.append(col);}page.append(board);return;}
    const filters=taskFilters(project),results=node('div');page.append(filters.bar,results);const update=()=>{const draft=viewDraft[project.id]||{},rows=M.filterTasks(project,draft.query||'',draft.taskState||'active',draft.taskOwner||'');filters.count.textContent=rows.length+' / '+project.tasks.length+' 项';results.replaceChildren(taskRows(project,rows));};filters.bind(update);update();page.scrollTop=remembered;
  }
  function requestRow(project,r){
    const a=link('',M.routeURL({...route,view:'collaboration',tab:route.tab,item:'request:'+r.id}),'request-row');a.append(icon('collaboration'));
    const main=node('div','','request-main');append(main,node('h3',r.title),node('p',r.body,'request-body'),meta(`${r.key} · ${r.time}`));if(r.reply)main.append(node('div',r.reply,'reply-preview'));
    const people=node('div','','request-people');append(people,node('p',ownerName(project,r.from)+' → '+ownerName(project,r.to),'people-line'),meta('发送人 → 接收人'));const state=node('div','','request-status');state.append(status(r.state,requestState[r.state]));
    append(a,main,people,state);return a;
  }
  function renderCollaboration(project){
    page.append(pageHeading('协作','问题、答复与处理状态各自独立。'));const tabs=node('nav','','tabs');
    for(const [id,label] of [['open','未解决'],['all','全部请求']]){const a=link(label,M.routeURL({...route,tab:id,item:''}),'tab');if(route.tab===id)a.setAttribute('aria-current','page');if(id==='open'){const n=project.requests.filter(r=>r.state!=='resolved').length;if(n)a.append(node('span',n,'count'));}tabs.append(a);}page.append(tabs);
    const list=node('section','','list'),items=route.tab==='open'?project.requests.filter(r=>r.state!=='resolved'):project.requests;
    if(!items.length)page.append(emptyState(route.tab==='open'?'目前没有等待回应的请求':'项目还没有请求','请求不会关闭任务流程；可以单独查看或使用。'));
    else for(const r of items)list.append(requestRow(project,r));if(items.length)page.append(list);
  }
  function contractRow(project,c){
    const row=node('article','','content-row'),mark=node('span','','object-mark');mark.append(icon('file'));row.append(mark);
    const body=node('div','','row-content');append(body,node('h3',c.title),meta(`${c.key} · v${c.effective} 生效`),node('p',c.body,'summary'));
    const sub=node('div','','links');if(c.sourceRequest){const r=project.requests.find(x=>x.id===c.sourceRequest);if(r)sub.append(link('来源请求 '+r.key,M.routeURL({...route,view:'collaboration',tab:'all',item:'request:'+r.id}),'inline-link'));}body.append(sub);
    const end=node('div','','row-end');end.append(badge('v'+c.effective+' 生效',true));if(c.latest>c.effective)end.append(badge('v'+c.latest+' 待审核'));const open=button('查看版本',()=>openItem('contract:'+c.id));end.append(open);append(row,body,end);return row;
  }
  function fileRow(project,f){const row=node('article','','content-row'),mark=node('span','','object-mark');mark.append(icon('file'));const body=node('div','','row-content');append(body,node('h3',f.name),meta(`${f.kind} · ${f.size} · ${ownerName(project,f.owner)} 分享 · ${f.time}`),node('p','来源：'+f.source,'summary'));if(f.taskId){const t=project.tasks.find(x=>x.id===f.taskId);if(t)body.append(link('相关任务 '+t.key,M.routeURL({...route,view:'tasks',tab:'list',item:'task:'+t.id}),'inline-link'));}const end=node('div','','row-end'),download=button('查看文件',()=>openItem('file:'+f.id));download.prepend(icon('file'));end.append(download);append(row,mark,body,end);return row;}
  function contextRecord(project,item){const row=node('article','','content-row'),mark=node('span','','object-mark');mark.append(icon('overview'));const body=node('div','','row-content'),event=item;append(body,node('h3',event.title),meta(`${event.time} · ${event.detail}`));const target=project.activity.find(e=>e.id===event.id);if(target){const ref=target.target,kind=ref.split(':')[0],paths={task:['tasks','list'],request:['collaboration','all'],contract:['context','agreements'],file:['context','files'],delivery:['delivery','all']};const linkTo=kind==='task'?project.tasks.find(t=>t.id===ref.split(':')[1]):kind==='request'?project.requests.find(r=>r.id===ref.split(':')[1]):kind==='contract'?project.contracts.find(c=>c.id===ref.split(':')[1]):kind==='file'?project.files.find(f=>f.id===ref.split(':')[1]):project.deliveries.find(d=>d.id===ref.split(':')[1]);if(linkTo){const label=kind==='task'?linkTo.key:kind==='request'?linkTo.key:kind==='file'?linkTo.name:kind==='delivery'?linkTo.label:linkTo.title;body.append(link(label,M.routeURL({...route,view:paths[kind][0],tab:paths[kind][1],item:ref}),'inline-link'));}}
    append(row,mark,body);return row;}
  function renderContext(project){
    page.append(pageHeading('共享上下文','约定、明确分享的文件与跨对象查询。'));
    const tabs=node('nav','','tabs'),labels2={agreements:'约定',files:'文件',records:'共享记录'};
    for(const tab of M.tabs.context){const a=link(labels2[tab],M.routeURL({...route,tab,item:''}),'tab');if(route.tab===tab)a.setAttribute('aria-current','page');const n=tab==='agreements'?project.contracts.length:tab==='files'?project.files.length:project.activity.length;if(n)a.append(node('span',n,'count'));tabs.append(a);}page.append(tabs);
    if(route.tab==='agreements'){
      const note=node('p','当前生效版本保持不变；新提案单独审核。','note');page.append(note);const list=node('div','','list');for(const c of project.contracts)list.append(contractRow(project,c));if(!project.contracts.length)list.append(emptyState('还没有共享约定','团队可以根据需要共享技术决策，不必先完成某个固定流程。'));page.append(list);
    }else if(route.tab==='files'){
      const list=node('div','','list');for(const f of project.files)list.append(fileRow(project,f));if(!project.files.length)page.append(emptyState('还没有共享文件','这里只展示成员明确分享的项目文件。'));else page.append(list);
    }else{
      const bar=node('div','','toolbar'),search=node('label','','search-field');search.append(icon('search'));const input=node('input');input.type='search';input.placeholder='搜索共享记录的标题与描述';input.value=viewDraft[project.id]?.records||'';search.append(input);bar.append(search);const all=node('select');for(const [v,l] of [['','全部类型'],['task','任务'],['request','请求'],['contract','约定'],['delivery','交付'],['file','文件']]){const o=node('option',l);o.value=v;all.append(o);}all.value=viewDraft[project.id]?.recordType||'';bar.append(all);page.append(bar);
      const list=node('div','','list'),draw=()=>{list.replaceChildren();const q=input.value.toLocaleLowerCase(),type=all.value;for(const e of project.activity.filter(x=>(!type||x.type===type)&&(!q||(x.title+' '+x.detail).toLocaleLowerCase().includes(q))))list.append(contextRecord(project,e));if(!list.children.length)list.append(emptyState('没有匹配的共享记录','调整搜索条件，或切换至约定和文件。'));};input.addEventListener('input',()=>{viewDraft[project.id]={...viewDraft[project.id],records:input.value};draw();});all.addEventListener('change',()=>{viewDraft[project.id]={...viewDraft[project.id],recordType:all.value};draw();});draw();page.append(list);
    }
  }
  function deliveryRow(project,d){
    const row=node('article','','content-row');const mark=node('span','','object-mark');mark.append(icon('delivery'));const body=node('div','','row-content');
    append(body,node('h3',d.title),node('p',d.label+' · '+d.branch,'mono'),meta(`${d.source} · ${d.time}`),status(d.state,d.stateText));
    const refs=node('div','','links');for(const id of d.taskIds){const t=project.tasks.find(x=>x.id===id);if(t)refs.append(link('任务 '+t.key,M.routeURL({...route,view:'tasks',tab:'list',item:'task:'+t.id}),'inline-link'));}body.append(refs);
    const end=node('div','','row-end'),view=button('详情',()=>openItem('delivery:'+d.id));end.append(view);
    if(route.mode==='edit'&&d.state==='pending'){const confirm=button('确认关联',()=>openAction('确认交付关联',node('p','确认将 '+d.label+' 与任务 '+d.taskIds.map(id=>project.tasks.find(t=>t.id===id)?.key).join('、')+' 关联？这只记录关联，不会改变任务状态。','subline'),'确认',()=>{d.state='working';d.stateText='明确关联';d.source='成员确认 · 演示中';return true;}),'primary');end.append(confirm);}
    append(row,mark,body,end);return row;
  }
  function renderDelivery(project){
    page.append(pageHeading('交付','提交沿着分支汇聚到 PR 与发布；每个节点都能返回相关任务。'));
    const tabs=node('nav','','tabs');const labels2={all:'全部',pr:'Pull request',branch:'分支',commit:'Commit',release:'Release'};
    for(const t of M.tabs.delivery){const a=link(labels2[t],M.routeURL({...route,tab:t,item:''}),'tab');if(route.tab===t)a.setAttribute('aria-current','page');tabs.append(a);}page.append(tabs);
    const items=project.gitGraph.filter(d=>route.tab==='all'||d.kind===route.tab);
    if(!items.length){page.append(emptyState('没有该类型的交付节点','分支、Commit、PR 与 Release 都有各自的关联入口。'));return;}
    const surface=node('section','','graph-surface'),caption=node('div','','graph-caption'),branches=node('div','','branch-legend');
    for(const [lane,name,color] of [[0,'main','main'],[1,'feat/shared-context','shared'],[2,'feat/delivery-evidence','delivery'],[3,'docs/onboarding','docs']]){const chip=node('span',name,'branch-chip '+color);branches.append(chip);}
    append(caption,node('p','提交关系 · 演示数据','meta'),node('span',items.length+' 个交付节点','meta'));surface.append(append(node('div','','graph-top'),caption,branches));
    const graph=node('div','','git-graph'),laneWidth=24,railWidth=112,rowHeight=68,svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`0 0 ${railWidth} ${items.length*rowHeight}`);svg.setAttribute('width',railWidth);svg.setAttribute('height',items.length*rowHeight);svg.setAttribute('aria-hidden','true');svg.classList.add('graph-lines');
    const positions=new Map(items.map((entry,index)=>[entry.id,{row:index,lane:entry.lane}]));
    for(const edge of M.graphEdges(project)){const from=positions.get(edge.from),to=positions.get(edge.to);if(!from||!to)continue;const path=document.createElementNS('http://www.w3.org/2000/svg','path');const x1=12+from.lane*laneWidth,y1=from.row*rowHeight+32,x2=12+to.lane*laneWidth,y2=to.row*rowHeight+32;path.setAttribute('d',`M ${x1} ${y1} C ${x1} ${y1+24}, ${x2} ${y2-24}, ${x2} ${y2}`);path.setAttribute('class','edge edge-'+to.lane);svg.append(path);}
    graph.append(svg);
    items.forEach((entry,index)=>{
      const row=node('article','','git-row');row.style.setProperty('--row',index);const rail=node('div','','git-rail');rail.style.setProperty('--lane',entry.lane);const marker=node('span','','git-marker '+entry.kind);marker.setAttribute('aria-hidden','true');rail.append(marker);
      const content=node('div','','git-node');const primary=entry.taskIds.map(id=>project.tasks.find(t=>t.id===id)).filter(Boolean);const heading=link('',M.routeURL({...route,item:'graph:'+entry.id}),'git-node-title');append(heading,node('span',entry.label,'mono'),node('strong',entry.title));
      const branchMeta=node('div','','git-node-meta');append(branchMeta,node('span',entry.branch,'branch-name'),status(entry.state,entry.status),node('span',entry.time,'meta'),node('span',ownerName(project,entry.owner),'meta'));content.append(heading,branchMeta);
      if(primary.length){const refs=node('div','','git-task-links');for(const t of primary){refs.append(link(t.key+' · '+t.title,M.routeURL({...route,project:project.id,view:'tasks',tab:'list',item:'task:'+t.id}),'inline-link'));}content.append(refs);}
      const source=node('p',entry.source,'meta');content.append(source);row.append(rail,content);graph.append(row);
    });
    surface.append(graph);page.append(surface);
  }
  function agentRow(project,member,agent){
    const row=node('div','','agent-row'),identity=node('div');append(identity,node('h4',agent.name),meta(`${agent.tool} · ${agent.platform} · ${agent.version}`),meta(`${agent.branch} · 登记 ${agent.registered}`));
    const tasks=node('div'),first=agent.taskIds.map(id=>project.tasks.find(t=>t.id===id)).filter(Boolean);tasks.append(node('p',first.length?'关联工作':'尚无关联工作','meta'));for(const t of first.slice(0,2))tasks.append(link(t.key+' · '+t.title,M.routeURL({...route,view:'tasks',tab:'list',item:'task:'+t.id}),'inline-link'));
    const actions=node('div','','agent-actions');actions.append(link('能力与连接详情',M.routeURL({...route,tab:'people',item:'agent:'+agent.id}),'link'));append(row,identity,tasks,actions);return row;
  }
  function renderMembers(project){
    page.append(pageHeading('成员与 agent','队友使用哪些工具、关联哪些工作，以及相应能力证据。'));
    const tabs=node('nav','','tabs');for(const t of M.tabs.members){const a=link('项目成员与 agent',M.routeURL({...route,tab:t,item:''}),'tab');if(route.tab===t)a.setAttribute('aria-current','page');a.append(node('span',project.members.length,'count'));tabs.append(a);}page.append(tabs);
    const list=node('div','','members-list');for(const m of project.members){const row=node('section','','member-section'),profile=node('div','','member-profile');append(profile,node('span',m.initial,'avatar '+m.color),append(node('div'),node('h3',m.name),meta(m.role)));const agents=node('div');if(!m.agents.length)agents.append(meta('尚无 agent 登记；项目成员与 agent 会话相互独立。'));for(const agent of m.agents)agents.append(agentRow(project,m,agent));append(row,profile,agents);list.append(row);}page.append(list);
  }
  function renderSettings(project){
    page.append(pageHeading('项目设置','连接与项目级配置。日常协作页面不会混入这些设置。'));
    const tabs=node('nav','','tabs');for(const tab of M.tabs.settings){const title={repository:'仓库',connection:'Agent 接入',diagnostics:'连接诊断'}[tab],a=link(title,M.routeURL({...route,tab,item:''}),'tab');if(route.tab===tab)a.setAttribute('aria-current','page');tabs.append(a);}page.append(tabs);
    const layout=node('div','','settings-layout'),main=node('div'),help=node('aside','','settings-help');
    const section=node('section','','settings-section');
    if(route.tab==='repository'){append(section,node('h2','代码仓库'),node('p',project.repository||'尚未绑定代码仓库。'));section.append(route.mode==='read'?node('span','只读','read-only'):button(project.repository?'管理仓库关联':'绑定仓库',()=>toastMessage('本原型不连接真实 GitHub。')));section.append(node('div','','project-facts'));section.append(link('在项目内查看交付',M.routeURL({...route,view:'delivery',tab:'all',item:''}),'inline-link'));}
    else if(route.tab==='connection'){append(section,node('h2','Agent 接入'),node('p','接入自己的 agent；凭据只在创建时临时展示。关闭后需重新生成。'),node('p','连接模板包含个人凭据。原型中不会生成或存储真实 token。','note'));if(route.mode!=='read')section.append(button('查看接入说明',()=>toastMessage('结构原型不会请求真实凭据。'),'primary'));}
    else{append(section,node('h2','连接诊断'),node('p','连接、事件送达与模型处理分别记录。未知状态保持未知。'));for(const m of project.members)for(const a of m.agents){const row=node('article','','agent-row');append(row,append(node('div'),node('h4',m.name+' · '+a.name),meta(a.platform+' · '+a.version)),append(node('div'),status('working',a.connection),meta(a.delivery)),append(node('div'),meta(a.processing)));section.append(row);}section.append(link('查看成员与完整能力矩阵',M.routeURL({...route,view:'members',tab:'people',item:''}),'inline-link'));}
    main.append(section);append(help,node('h3','项目范围'),node('p',project.members.length+' 位项目成员可以访问这里的协作记录。','meta'),link('管理成员与能力',M.routeURL({...route,view:'members',tab:'people',item:''}),'inline-link'));layout.append(main,help);page.append(layout);
  }
  function renderProjects(){
    page.append(pageHeading('全部项目','当前账号拥有访问权限的项目。'));
    const list=node('div','','project-list');for(const p of M.projects){const a=link('',M.routeURL({project:p.id,view:'overview',tab:'summary',item:'',mode:route.mode}),'project-card');append(a,node('span',p.name.slice(0,1),'project-glyph '+p.color),append(node('div'),node('h2',p.name),meta(p.team+' · '+(p.repository||'尚未绑定仓库')),node('p',p.description,'subline')) ,icon('right'));list.append(a);}page.append(list);
  }
  function renderTeam(){
    const project=getProject(),team=M.teams.find(t=>t.name===project.team)||M.teams[0];page.append(pageHeading(team.name,'团队管理与项目访问属于团队范围；项目协作内容仍保留在各项目中。'));
    const section=node('section','','section'),head=sectionTitle('团队成员',route.mode==='edit'?'邀请成员':null,'#');section.append(head);
    const list=node('div','','members-list');for(const tm of team.members){const m=project.members.find(x=>x.id===tm.id)||M.projects.flatMap(p=>p.members).find(x=>x.id===tm.id);if(!m)continue;const row=node('div','','member-section');const profile=append(node('div','','member-profile'),node('span',m.initial,'avatar '+m.color),append(node('div'),node('h3',m.name),meta(tm.role)));const access=node('div');access.append(meta('可访问项目'));for(const pid of tm.projects){const p=M.projects.find(x=>x.id===pid);if(p)access.append(link(p.name,M.routeURL({project:p.id,view:'overview',tab:'summary',item:'',mode:route.mode}),'inline-link'));}append(row,profile,access);list.append(row);}section.append(list);page.append(section);
    const projectSection=node('section','','section');projectSection.append(sectionTitle('团队项目'));const projects=node('div','','project-list');for(const id of team.projects){const p=M.projects.find(x=>x.id===id);if(!p)continue;const a=link('',M.routeURL({project:p.id,view:'overview',tab:'summary',item:'',mode:route.mode}),'project-card');append(a,node('span',p.name.slice(0,1),'project-glyph '+p.color),append(node('div'),node('h3',p.name),meta(p.repository||'尚未绑定仓库')),icon('right'));projects.append(a);}projectSection.append(projects);page.append(projectSection);
    if(route.mode==='edit')page.append(button('邀请成员',()=>toastMessage('原型中的邀请不会签发或保存凭据。')));
  }
  function renderAccount(){const m=M.currentUser;page.append(pageHeading('个人账号','个人身份与团队权限分开管理。'));const box=node('section','','settings-section');append(box,node('h2',m.name),meta('演示身份 · '+m.username),node('p','真实账号设置和安全凭据不包含在这个原型中。'));box.append(button('退出演示',()=>toastMessage('只读原型不保存登录状态。')));page.append(box);}
  function emptyState(title,description,action){const e=node('section','','empty');e.append(icon('overview'),node('h2',title),node('p',description));if(action)e.append(action);return e;}
  function render(){
    route=M.parseRoute(location.hash);const project=getProject();updateProjectChrome(project);page.replaceChildren();
    if(route.view==='overview'){if(route.tab==='activity'){page.append(pageHeading('项目活动','完整事件记录。每条记录保留关联对象和来源。'));const list=node('div','','list');for(const e of project.activity)list.append(contextRecord(project,e));page.append(list);}else renderOverview(project);}
    else if(route.view==='tasks')renderTasks(project);else if(route.view==='collaboration')renderCollaboration(project);else if(route.view==='context')renderContext(project);else if(route.view==='delivery')renderDelivery(project);else if(route.view==='members')renderMembers(project);else if(route.view==='settings')renderSettings(project);else if(route.view==='projects')renderProjects();else if(route.view==='team')renderTeam();else if(route.view==='account')renderAccount();
    if(route.item)showDetail(project,route.item);else if($('detail').open)$('detail').close();
    document.title=project.name==='Coopagents'?'Coopagents · '+labels[route.view]:'Coopagents · '+project.name+' · '+labels[route.view];
  }
  function showDetail(project,item){
    const obj=M.findObject(project,item);if(!obj)return;
    const [type]=item.split(':');const dialog=$('detail'),host=$('detail-content');host.replaceChildren();const top=node('header','','drawer-top');
    const back=button('返回 '+labels[route.view],()=>closeDetail());back.prepend(icon('back'));const readonly=route.mode==='read'?node('span','只读预览 · 合成数据','read-only'):node('span','项目范围','read-only');append(top,back,readonly);host.append(top);
    const body=node('div','','drawer-body');host.append(body);
    if(type==='task')taskDetail(project,obj,body);else if(type==='request')requestDetail(project,obj,body);else if(type==='contract')contractDetail(project,obj,body);else if(type==='file')fileDetail(project,obj,body);else if(type==='delivery')deliveryDetail(project,obj,body);else if(type==='agent')agentDetail(project,obj,body);else if(type==='graph')graphDetail(project,obj,body);
    if(!dialog.open)dialog.showModal();
  }
  function headingDetail(key,title,st,owner){append(pageDummy(),'');const k=node('p',key,'drawer-key'),h=node('h2',title);append($('detail-content').querySelector('.drawer-body'),k,h);const s=status(st.label,st.text);$('detail-content').querySelector('.drawer-body').append(s);if(owner)$('detail-content').querySelector('.drawer-body').append(meta(owner));}
  function pageDummy(){return document.createDocumentFragment();}
  function detailSection(title,...children){const s=node('section','','detail-section');s.append(node('h3',title));append(s,...children);return s;}
  function taskDetail(project,t,body){append(body,node('p',t.key,'drawer-key'),node('h2',t.title),status(t.state,taskState[t.state]),person(project,t.owner));
    body.append(detailSection('当前进展',node('p',t.summary),meta('更新时间 '+t.time+' · '+t.evidence)));
    body.append(detailSection('声明范围',node('p',t.scope,'mono')));
    const rel=M.relations(project,t.id),linked=node('div');
    for(const r of rel.requests)linked.append(link(r.key+' · '+r.title,M.routeURL({...route,view:'collaboration',tab:'all',item:'request:'+r.id}),'detail-link'));
    for(const d of rel.deliveries)linked.append(link(d.label+' · '+d.title,M.routeURL({...route,view:'delivery',tab:'all',item:'delivery:'+d.id}),'detail-link'));
    for(const dep of project.tasks.filter(x=>x.id!==t.id&&x.state==='blocked'))if(t.id==='t3')linked.append(link('依赖请求 R-12 · '+dep.title,M.routeURL({...route,view:'collaboration',tab:'all',item:'request:r1'}),'detail-link'));
    if(!linked.children.length)linked.append(meta('尚无相关请求、依赖或交付关联。'));body.append(detailSection('相关协作与交付',linked));
    body.append(detailSection('状态含义',meta('推进状态、agent 自述、代码合并和人的验收是不同信息。原型不自动更改它们。')));
  }
  function requestDetail(project,r,body){append(body,node('p',r.key,'drawer-key'),node('h2',r.title),status(r.state,requestState[r.state]));const people=node('div','','detail-section');append(people,node('h3','发送与接收'),node('p',ownerName(project,r.from)+' → '+ownerName(project,r.to),'people-line'));body.append(people);body.append(detailSection('问题',node('p',r.body)));if(r.reply)body.append(detailSection('最新回复',node('p',r.reply),meta('回复人 '+ownerName(project,r.to)+' · 明确提交的答复')));
    const refs=node('div');for(const id of [r.taskId,r.relatedTask].filter(Boolean)){const t=project.tasks.find(x=>x.id===id);if(t)refs.append(taskAnchor(project,t,true));}if(r.contractId){const c=project.contracts.find(x=>x.id===r.contractId);if(c)refs.append(link('相关约定 · '+c.title,M.routeURL({...route,view:'context',tab:'agreements',item:'contract:'+c.id}),'detail-link'));}
    body.append(detailSection('相关对象',refs));if(route.mode==='edit'&&r.state==='waiting')body.append(button('回复请求',()=>toastMessage('回复操作为演示数据。')));
  }
  function contractDetail(project,c,body){append(body,node('p',c.key,'drawer-key'),node('h2',c.title),badge('v'+c.effective+' 生效',true));body.append(detailSection('当前生效版本 v'+c.effective,node('p',c.body),meta('维护者 '+ownerName(project,c.owner)+' · '+c.time)));
    if(c.latest>c.effective)body.append(detailSection('待审新提案 v'+c.latest,node('p',c.proposal),meta('尚未审核 · 当前生效内容未被替换')));if(c.sourceRequest){const r=project.requests.find(x=>x.id===c.sourceRequest);if(r)body.append(detailSection('来源',link(r.key+' · '+r.title,M.routeURL({...route,view:'collaboration',tab:'all',item:'request:'+r.id}),'detail-link')));}}
  function fileDetail(project,f,body){append(body,node('p','项目文件','drawer-key'),node('h2',f.name),badge('成员明确分享'));body.append(detailSection('文件信息',meta(`${f.kind} · ${f.size} · 分享人 ${ownerName(project,f.owner)} · ${f.time}`),node('p','来源：'+f.source)));
    const preview=node('pre',f.body);preview.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f8fa;border:1px solid var(--line);border-radius:6px;padding:16px;font:12px/1.8 Consolas,monospace';body.append(detailSection('预览（合成内容）',preview));if(f.taskId){const t=project.tasks.find(x=>x.id===f.taskId);if(t)body.append(detailSection('关联工作',taskAnchor(project,t,true)));}}
  function deliveryDetail(project,d,body){append(body,node('p',relationType[d.kind],'drawer-key'),node('h2',d.label+' · '+d.title),status(d.state,d.stateText));body.append(detailSection('来源与更新时间',meta(d.source+' · '+d.time),node('p',d.detail),node('p',d.branch,'mono')));
    const rel=node('div');for(const id of d.taskIds){const t=project.tasks.find(x=>x.id===id);if(t)rel.append(taskAnchor(project,t,true));}body.append(detailSection('关联任务',rel));
    if(route.mode==='edit'&&d.state==='pending'){const actions=node('div','','form-actions'),confirm=button('确认建议',()=>openAction('确认交付关联',node('p','只记录人工确认的关联，不会更改任务状态。','subline'),'确认',()=>{d.state='working';d.stateText='明确关联';d.source='成员确认 · 演示中';switchRoute({item:''});return true;}),'primary');actions.append(button('拒绝建议',()=>{d.state='open';d.stateText='未关联';switchRoute({item:''});toastMessage('建议已在演示状态中拒绝。');}),confirm);body.append(detailSection('待确认的建议',meta('确认交付对象与任务之间的关联。'),actions));}}
  function graphDetail(project,g,body){append(body,node('p',relationType[g.kind]||'Git 图节点','drawer-key'),node('h2',g.title),status(g.state,g.status));body.append(detailSection('对象与来源',node('p',g.label,'mono'),node('p',g.branch,'mono'),meta(g.source+' · '+g.time)));
    const parents=node('div');for(const id of g.parents){const p=project.gitGraph.find(x=>x.id===id);if(p)parents.append(link(p.label+' · '+p.title,M.routeURL({...route,view:'delivery',tab:'all',item:'graph:'+p.id}),'detail-link'));}body.append(detailSection('父级对象',parents.children.length?parents:meta('当前节点没有父级提交。')));
    const tasks=node('div');for(const id of g.taskIds){const t=project.tasks.find(x=>x.id===id);if(t)tasks.append(taskAnchor(project,t,true));}body.append(detailSection('关联任务',tasks.children.length?tasks:meta('尚无任务关联。')));
    const delivery=project.deliveries.find(d=>d.kind===g.kind&&(d.label===g.label||d.branch===g.branch));if(delivery)body.append(detailSection('关联交付详情',link(delivery.label+' · '+delivery.title,M.routeURL({...route,view:'delivery',tab:'all',item:'delivery:'+delivery.id}),'detail-link')));
  }
  function agentDetail(project,a,body){const member=project.members.find(m=>m.agents.some(x=>x.id===a.id));if(!member)return;append(body,node('p','成员与 agent','drawer-key'),node('h2',member.name+' · '+a.name),badge(a.tool));body.append(detailSection('会话登记',meta(`${a.platform} · ${a.version} · 最近登记 ${a.registered}`),node('p',a.branch,'mono')));body.append(detailSection('状态与来源',node('p',a.presence),node('p',a.connection),node('p',a.delivery),node('p',a.processing),meta('不同状态彼此独立；未知信息保持未知。')));const caps=node('div');for(const [name,label] of a.capabilities)caps.append(append(node('div','','fact'),node('span',name),node('span',badge(label,label==='已验证支持'))));body.append(detailSection('能力证据',caps));const work=node('div');for(const id of a.taskIds){const t=project.tasks.find(x=>x.id===id);if(t)work.append(taskAnchor(project,t,true));}body.append(detailSection('关联工作',work));}
  function closeDetail(){if(drawerHistory&&history.state?.iaDrawer){drawerHistory=false;history.back();return;}drawerHistory=false;if(!route.item)return;route={...route,item:''};history.replaceState(history.state,'',M.routeURL(route));render();}
  function fillProjectOptions(){const list=$('project-options');list.replaceChildren();const selected=M.projects.find(p=>p.id===route.project),lead=node('div','','switcher-lead');append(lead,node('span',selected.name.slice(0,1),'project-glyph '+selected.color),append(node('div'),node('strong','当前项目：'+selected.name),node('p',selected.repository||selected.description)));list.append(lead);let current='';for(const p of M.projects){if(current!==p.team){current=p.team;list.append(node('p',current,'option-team'));}const a=link('',M.routeURL({project:p.id,view:'overview',tab:'summary',item:'',mode:route.mode}),'project-option');if(p.id===route.project)a.setAttribute('aria-current','page');append(a,node('span',p.name.slice(0,1),'project-glyph '+p.color),append(node('div'),node('strong',p.name),node('small',p.repository||p.description,'meta')),p.id===route.project?badge('当前项目',true):icon('right'));list.append(a);}const foot=node('div','','switcher-foot');foot.append(link('团队管理',M.routeURL({...route,view:'team',tab:'members',item:''}),'inline-link'),link('全部项目',M.routeURL({...route,view:'projects',tab:'',item:''}),'inline-link'));list.append(foot);}
  function closeMobile(){mobileOpen=false;document.body.classList.remove('menu-open');$('menu-scrim').hidden=true;$('mobile-menu').setAttribute('aria-expanded','false');}
  $('project-switch').addEventListener('click',()=>{fillProjectOptions();$('switcher').showModal();});$('project-options').addEventListener('click',event=>{if(event.target.closest('a'))$('switcher').close();});$('mobile-menu').append(icon('menu'));$('mobile-menu').addEventListener('click',()=>{mobileOpen=!mobileOpen;document.body.classList.toggle('menu-open',mobileOpen);$('menu-scrim').hidden=!mobileOpen;$('mobile-menu').setAttribute('aria-expanded',String(mobileOpen));});$('menu-scrim').addEventListener('click',closeMobile);
  $('mode-button').addEventListener('click',()=>switchRoute({mode:route.mode==='read'?'edit':'read',item:''}));
  for(const b of document.querySelectorAll('[data-close]'))b.addEventListener('click',()=>$(b.dataset.close).close());
  for(const d of document.querySelectorAll('dialog'))d.addEventListener('click',e=>{if(e.target===d)d.close();});
  $('detail').addEventListener('close',()=>{if(route.item)closeDetail();});
  $('switcher').addEventListener('close',()=>{$('project-switch').focus();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&mobileOpen)closeMobile();});
  document.querySelectorAll('#project-nav a,#utility-nav a').forEach(a=>a.addEventListener('click',closeMobile));
  window.addEventListener('hashchange',()=>{const previous=route;route=M.parseRoute(location.hash);if(previous.project!==route.project)delete viewDraft[previous.project];if(!route.item)drawerHistory=false;closeMobile();render();if(route.item&&history.state?.iaDrawer)drawerHistory=true;});
  const originalSwitch=switchRoute;
  function guardedSwitch(next,replace=false){if(next.item&&!replace){history.pushState({iaDrawer:true},'',M.routeURL({...route,...next}));route=M.parseRoute(location.hash);render();drawerHistory=true;}else originalSwitch(next,replace);}
  switchRoute=guardedSwitch;
  render();
})();
