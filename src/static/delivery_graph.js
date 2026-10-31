'use strict';
(() => {
  const views=new WeakMap();
  const labels={branch:'分支',commit:'Commit',pr:'Pull request',release:'Release'};
  const stateLabels={open:'PR 已打开',closed_unmerged:'PR 已关闭 · 未合并',merged:'已合并',pushed:'已推送',unavailable:'当前不可用',pending_sync:'待同步',pending_confirmation:'待确认',historical:'历史关联',observed:'只读观测',published:'已发布',draft:'草稿',prerelease:'预发布'};
  const element=(tag,value='',cls)=>{const node=document.createElement(tag);node.textContent=value??'';if(cls)node.className=cls;return node;};
  const append=(parent,...children)=>{children.forEach(child=>{if(child)parent.append(child);});return parent;};
  const unique=items=>[...new Set(items)];

  function buildGraph(graph,git={}){
    const items=graph?.items||[],facts=git.deliveries||[],releases=git.releases||[],workspaces=git.workspaces||[];
    const nodes=new Map();
    for(const item of items){
      const kind=item.kind,key=item.object_key||kind+':'+item.value,fact=kind==='pr'?facts.find(d=>Number(d.pr_number)===Number(item.value)):kind==='commit'?facts.find(d=>(d.commit_sha||'').toLowerCase()===(String(item.value).toLowerCase())):kind==='release'?releases.find(r=>Number(r.release_id)===Number(item.value)):null;
      const release=kind==='release'?releases.find(r=>Number(r.release_id)===Number(item.value)):null;
      const observations=workspaces.filter(w=>kind==='commit'?String(w.head||'').toLowerCase()===String(item.value).toLowerCase():kind==='branch'?w.branch===item.value:false);
      const branch=kind==='branch'?String(item.value):kind==='pr'?(fact?.branch||item.associations?.find(a=>a.evidence==='GitHub PR head matches linked branch')?.branch||''):kind==='commit'?(observations[0]?.branch||''):'';
      const value=String(item.value),label=kind==='pr'?'PR #'+value:kind==='release'?(release?.tag_name||'Release '+value):kind==='commit'?value.slice(0,12):value;
      nodes.set(key,{key,object_key:key,kind,value,label,title:kind==='pr'?(fact?.title||item.title||'关联的 PR'):kind==='release'?(release?.name||release?.tag_name||item.title||'关联的 Release'):kind==='commit'?'提交 '+value.slice(0,12):'分支 '+value,branch,repository:item.repository||'',task_ids:item.task_ids||[],associations:item.associations||[],fact,release,observations,state:fact?.state||release?.state||item.associations?.find(a=>a.state)?.state||'observed',source:item.associations?.map(a=>a.source).filter(Boolean).join(' · ')||fact?.source||release?.source||'交付关联',stale:!!(fact?.stale||release?.stale||item.associations?.some(a=>a.stale)),unavailable:!!(fact?.unavailable||release?.unavailable||item.associations?.some(a=>a.unavailable))});
    }
    const branches=[...nodes.values()].filter(n=>n.kind==='branch');
    for(const node of nodes.values())if(!node.branch){
      if(node.kind==='release')node.branch='';
      else if(node.kind==='pr')node.branch=node.fact?.branch||node.associations.find(a=>a.evidence==='GitHub PR head matches linked branch')?.branch||'';
      else if(node.kind==='commit')node.branch=node.observations[0]?.branch||'';
    }
    const edges=[];
    const addEdge=(from,to,kind,label)=>{if(from!==to&&!edges.some(e=>e.from===from&&e.to===to&&e.kind===kind))edges.push({from,to,kind,label});};
    for(const branch of branches){
      for(const commit of nodes.values())if(commit.kind==='commit'){
        const match=commit.associations.find(c=>c.source==='local_git'&&c.observation_id&&branch.associations.some(b=>b.source==='local_git'&&b.observation_id===c.observation_id&&b.task_id===c.task_id));
        const workspace=commit.observations.find(w=>w.branch===branch.value&&branch.task_ids.includes(w.task_id));
        if(match||workspace)addEdge(branch.key,commit.key,'workspace-head','同一工作区 HEAD 观测');
      }
      for(const pr of nodes.values())if(pr.kind==='pr'){
        const evidence=pr.associations.find(a=>a.relationship_source==='observed'&&a.evidence==='GitHub PR head matches linked branch'&&branch.task_ids.includes(a.task_id));
        const verifiedHead=pr.fact?.source==='github_verified'&&pr.fact.branch===branch.value&&branch.task_ids.some(id=>pr.task_ids.includes(id));
        if(evidence||verifiedHead)addEdge(branch.key,pr.key,'pr-head-branch','PR head branch 匹配');
      }
    }
    for(const pr of nodes.values())if(pr.kind==='pr'&&pr.fact?.source==='github_verified'&&pr.fact.head_sha){
      for(const commit of nodes.values())if(commit.kind==='commit'&&commit.value.toLowerCase()===String(pr.fact.head_sha).toLowerCase())addEdge(pr.key,commit.key,'pr-head-sha','PR head SHA 匹配');
    }
    // A checkpoint association is explicit evidence even when its current
    // workspace observation has fallen outside the bounded workspace list.
    for(const node of nodes.values())if(node.kind==='commit'&&!node.branch){
      const related=unique(edges.filter(e=>e.kind==='workspace-head'&&e.to===node.key).map(e=>nodes.get(e.from)?.value).filter(Boolean));
      if(related.length===1)node.branch=related[0];
    }
    const grouped=new Map(),groups=[];
    const ensure=(id,title,kind='branch')=>{if(!grouped.has(id)){const group={id,title,kind,nodes:[]};grouped.set(id,group);groups.push(group);}return grouped.get(id);};
    const branchNodes=branches.slice().sort((a,b)=>(a.value==='main'?-1:b.value==='main'?1:a.value.localeCompare(b.value)));
    for(const branch of branchNodes)ensure('branch:'+branch.value,branch.value,'branch').nodes.push(branch);
    for(const node of nodes.values()){
      if(node.kind==='branch')continue;
      if(node.kind==='release')ensure('release','Release','release').nodes.push(node);
      else if(node.branch&&grouped.has('branch:'+node.branch))grouped.get('branch:'+node.branch).nodes.push(node);
      else ensure('unlinked-'+node.kind,node.kind==='pr'?'未匹配分支的 PR':node.kind==='commit'?'未匹配分支的提交':'未关联的交付对象','unlinked').nodes.push(node);
    }
    return {nodes:[...nodes.values()],edges,groups,truncated:!!graph?.truncated,source:graph?.source||'delivery_registry'};
  }

  function render(root,graph,git={},context={}){
    if(!root)return;
    let state=views.get(root);
    if(!graph){state?.resizeObserver?.disconnect();views.delete(root);root.replaceChildren();return;}
    if(state?.resizeObserver)state.resizeObserver.disconnect();if(!state||state.room!==context.roomId){state={room:context.roomId,query:'',kind:'',branch:'',selected:null};views.set(root,state);}
    const projection=buildGraph(graph,git),section=element('section','','delivery-graph');section.setAttribute('aria-label','Git 交付关系图');
    const heading=element('div','','graph-page-heading');append(heading,element('div','', 'graph-page-title'),element('p','分支、提交、PR 与 Release 按已有关系分组。连接线只表示有来源的关联，不代表完整 Git 提交历史。','meta'));
    heading.firstChild.append(element('p','05 / DELIVERY','eyebrow'),element('h2','交付关系'));
    const controls=element('div','','git-graph-controls'),search=element('label','','search-field');search.setAttribute('aria-label','搜索交付对象');const input=element('input');input.type='search';input.placeholder='搜索分支、SHA、PR 或 Release';input.value=state.query;search.append(input);const kind=element('select');kind.setAttribute('aria-label','交付类型');for(const [value,label] of [['','全部类型'],['branch','分支'],['commit','Commit'],['pr','Pull request'],['release','Release']]){const option=element('option',label);option.value=value;kind.append(option);}kind.value=state.kind;const branches=unique(projection.groups.filter(g=>g.kind==='branch').map(g=>g.title));const branch=element('select');branch.setAttribute('aria-label','分支');const all=element('option','全部分支');all.value='';branch.append(all);for(const name of branches){const option=element('option',name);option.value=name;branch.append(option);}branch.value=state.branch;const count=element('span','','result-count');append(controls,search,kind,branch,count);section.append(heading,controls);
    // Keep the full projection mounted so snapshot refreshes preserve filter recovery.
    const candidates=projection.groups;
    const legend=element('div','','branch-legend');for(const group of candidates.filter(g=>g.kind==='branch'))legend.append(element('span',group.title,'branch-chip'));section.append(legend);
    function open(node){state.selected=node.key;context.openNode?.(node.key,node,projection);}
    const graphRoot=element('div','','git-graph-groups');graphRoot.style.position='relative';const nodeElements=new Map(),rowElements=new Map(),edgeElements=[];
    for(const [laneIndex,group] of candidates.entries()){
      const lane=element('section','','git-lane');lane.setAttribute('aria-label',group.title+' 分支交付关系');lane.style.position='relative';lane.style.zIndex='1';lane.style.setProperty('--lane',String(Math.min(laneIndex,3)));const laneHead=element('header','','git-lane-head');
      append(laneHead,element('span','','git-lane-track'),append(element('div'),element('p',group.kind==='branch'?'分支轨道':group.kind==='release'?'发布记录':'其他交付','eyebrow'),element('h3',group.title)),element('span',group.nodes.length+' 个对象','meta'));lane.append(laneHead);
      const child=element('div','','git-lane-objects');
      for(const node of group.nodes){
        const article=element('article','','git-object-row'),marker=element('span','','git-object-marker kind-'+node.kind),body=element('div','','git-object-body'),top=element('div','','git-object-top'),openButton=element('button',node.label,'git-object-link');article.dataset.nodeKey=node.key;nodeElements.set(node.key,marker);rowElements.set(node.key,article);openButton.type='button';openButton.setAttribute('data-node-key',node.key);openButton.addEventListener('click',()=>open(node));
        append(top,openButton,element('span',labels[node.kind]||node.kind,'kind-chip'),element('span',stateLabels[node.state]||node.state,'git-object-state'+(node.stale?' stale':'')));
        append(body,top);if(!['branch','commit'].includes(node.kind))body.append(element('p',node.title,'git-object-title'));
        const facts=element('div','','git-object-facts');if(node.branch)facts.append(element('span','分支 '+node.branch,'mono'));if(node.repository)facts.append(element('span',node.repository,'meta'));if(node.stale||node.unavailable)facts.append(element('span',node.unavailable?'来源不可用':'证据过期','evidence-warning'));
        const evidence=projection.edges.filter(edge=>edge.from===node.key||edge.to===node.key);for(const edge of evidence)facts.append(element('span',edge.label,'relation-tag'));body.append(facts);
        if(node.task_ids.length){const tasks=element('div','','git-object-tasks');for(const id of node.task_ids){const name=context.taskName?.(id)||'任务 #'+id,button=element('button',name,'git-task-link');button.type='button';button.addEventListener('click',()=>context.openTask?.(id));tasks.append(button);}body.append(tasks);}
        if(!context.readOnly&&context.canManage&&context.api){for(const association of node.associations.filter(a=>a.relationship_source==='suggested'&&a.status==='pending'&&a.state==='pending_confirmation'&&a.suggestion_id)){const controls=element('div','','git-suggestion-actions'),feedback=element('span','','meta');for(const [decision,label] of [['confirmed','确认关联'],['rejected','拒绝建议']]){const decisionButton=element('button',label,'git-suggestion-button');decisionButton.type='button';decisionButton.addEventListener('click',async()=>{if(context.isCurrent&&!context.isCurrent())return;controls.querySelectorAll('button').forEach(b=>b.disabled=true);try{await context.api('/api/operations/decide_delivery',{suggestion_id:association.suggestion_id,decision});if(context.isCurrent&&!context.isCurrent())return;feedback.textContent=decision==='confirmed'?'已确认关联':'已拒绝建议';await context.sync?.();}catch(error){if(!context.isCurrent||context.isCurrent())feedback.textContent=error.message;}finally{controls.querySelectorAll('button').forEach(b=>b.disabled=false);}});controls.append(decisionButton);}controls.append(feedback);body.append(controls);}}
        if(node.kind==='pr'){const fact=node.fact,checks=fact?.checks||[],statuses=fact?.statuses||[],verified=fact?.checks_verified||fact?.source==='github_verified';if(verified){const checkLine=element('p','检查 '+(checks.length?checks.map(c=>c.conclusion||c.status||c.state).join(' · '):statuses.length?statuses.map(c=>c.state).join(' · '):'未知'),'meta');body.append(checkLine);}}
        article.append(marker,body);child.append(article);
      }
      lane.append(child);graphRoot.append(lane);
    }
    count.textContent=candidates.reduce((n,g)=>n+g.nodes.length,0)+' 个交付对象';
    const filterEmpty=element('p','没有匹配的交付对象。请调整搜索或筛选。','graph-filter-empty');filterEmpty.setAttribute('role','status');graphRoot.append(filterEmpty);
    if(projection.truncated)graphRoot.append(element('p','交付清单已截断；请在共享上下文按任务或对象继续查询。','meta'));
    section.append(graphRoot);
    root.replaceChildren(section);
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('git-edge-layer');svg.setAttribute('aria-hidden','true');svg.setAttribute('preserveAspectRatio','none');svg.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:0';
    for(const edge of projection.edges){const from=nodeElements.get(edge.from),to=nodeElements.get(edge.to);if(!from||!to)continue;const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('class','git-edge git-edge-'+edge.kind);path.setAttribute('data-from',edge.from);path.setAttribute('data-to',edge.to);path.setAttribute('fill','none');path.setAttribute('stroke-width','2');path.setAttribute('stroke','currentColor');const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=edge.label;path.append(title);svg.append(path);edgeElements.push({path,edge});}
    const drawEdges=()=>{const bounds=graphRoot.getBoundingClientRect();svg.setAttribute('viewBox',`0 0 ${Math.max(1,bounds.width)} ${Math.max(1,bounds.height)}`);for(const {path,edge} of edgeElements){const from=nodeElements.get(edge.from),to=nodeElements.get(edge.to);if(!from||!to||rowElements.get(edge.from)?.hidden||rowElements.get(edge.to)?.hidden){path.setAttribute('display','none');path.setAttribute('d','');continue;}path.setAttribute('display','');const a=from.getBoundingClientRect(),b=to.getBoundingClientRect(),x1=a.left-bounds.left+a.width/2,y1=a.top-bounds.top+a.height/2,x2=b.left-bounds.left+b.width/2,y2=b.top-bounds.top+b.height/2;path.setAttribute('d',`M ${x1} ${y1} C ${x1+30} ${y1}, ${x2+30} ${y2}, ${x2} ${y2}`);}};
    graphRoot.prepend(svg);
    drawEdges();if(typeof ResizeObserver!=='undefined'){state.resizeObserver=new ResizeObserver(drawEdges);state.resizeObserver.observe(graphRoot);}
    const applyFilters=()=>{
      let visible=0;
      for(const group of graphRoot.querySelectorAll('.git-lane')){
        let groupCount=0;
        for(const row of group.querySelectorAll('.git-object-row')){
          const node=projection.nodes.find(n=>n.key===row.dataset.nodeKey);
          const show=!!node&&(!state.query||[node.label,node.title,node.value,node.branch,node.repository,node.source].join(' ').toLocaleLowerCase().includes(state.query.toLocaleLowerCase()))&&(!state.kind||node.kind===state.kind)&&(!state.branch||node.branch===state.branch);
          row.hidden=!show;if(show){visible++;groupCount++;}
        }
        group.hidden=groupCount===0;
        const total=group.querySelectorAll('.meta')[0];if(total)total.textContent=groupCount+' 个对象';
      }
      filterEmpty.hidden=visible>0;count.textContent=visible+' 个交付对象';drawEdges();
    };
    input.addEventListener('input',()=>{state.query=input.value;applyFilters();});kind.addEventListener('change',()=>{state.kind=kind.value;applyFilters();});branch.addEventListener('change',()=>{state.branch=branch.value;applyFilters();});applyFilters();
  }
  const api={buildGraph,render};if(typeof module!=='undefined'&&module.exports)module.exports=api;if(typeof window!=='undefined')window.CoopagentsDeliveryGraph=api;
})();
