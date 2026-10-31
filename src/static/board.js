'use strict';
(() => {
  const columns=[['open','待认领','明确意图，等待接手'],['working','推进中','agent 正在推进'],['blocked','遇到阻塞','需要团队协助'],['review','待验收','本地完成、已推送或 PR 打开'],['merged','已合并','查看卡片中的交付证据来源'],['cancelled','已取消','保留历史']];
  const node=(tag,value='',cls)=>{const n=document.createElement(tag);n.textContent=value??'';if(cls)n.className=cls;return n;};
  const add=(n,...children)=>{children.forEach(c=>n.append(c));return n;};
  const date=v=>v?new Date(v).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';
  const member=(s,id)=>s.members.find(m=>m.member_id===id)?.display_name||(id?'成员 '+id:'待分派');
  function column(task,progress,snapshot,adapters={}){
    if(task.cancelled_at||task.state==='cancelled')return 'cancelled';
    if(!task.owner_member_id)return 'open';
    if(adapters.dependencies?.blocked(task,snapshot))return 'blocked';
    const state=adapters.git?.state(task,progress,snapshot?.git)||progress?.state;
    if(state==='blocked')return 'blocked';
    if(state==='merged')return 'merged';
    if(['local_done','pushed','pr_open'].includes(state))return 'review';
    return 'working';
  }
  function matchingTasks(tasks,progress,query,owner){
    const needle=query.trim().toLocaleLowerCase();
    return tasks.filter(t=>(!owner||(owner==='unassigned'?!t.owner_member_id:String(t.owner_member_id)===owner))&&
      (!needle||[t.title,t.scope,t.intent_key,progress.find(p=>p.task_id===t.id)?.summary||''].join(' ').toLocaleLowerCase().includes(needle)));
  }
  function card(t,p,s,adapters={}){
    const name=id=>member(s,id),requests=s.requests.filter(r=>r.task_id===t.id),card=node('button','','task-card');
    card.type='button';card.id='task-'+t.id;card.setAttribute('aria-label','查看任务 #'+t.id+'：'+t.title);
    card.addEventListener('click',()=>adapters.open?.(t.id));
    add(card,add(node('div','','card-top'),node('span','CM-'+String(t.id).padStart(3,'0'),'task-number'),node('span','↗','card-arrow')),node('h3',t.title),node('p',p?.summary||(t.cancelled_at?'任务已取消。':'已声明工作范围，等待 agent 推进。'),'card-summary'),node('p',t.scope,'card-scope'));
    add(card,add(node('div','','card-bottom'),add(node('span','','card-person'),node('span',(t.owner_member_id?name(t.owner_member_id):'?').slice(0,1),'avatar'),node('span',t.cancelled_at?'已取消':t.owner_member_id?name(t.owner_member_id):'待认领')),node('span',requests.length+' 请求','card-meta')),node('p',date(p?.updated_at||t.cancelled_at||t.claimed_at||t.created_at)+' · '+(t.cancelled_at?'已取消':p?'agent 自述':t.owner_member_id?'已认领':'任务声明'),'card-time'));
    const handoff=s.lifecycle?.handoffs?.find(h=>h.task_id===t.id&&h.status==='pending');if(handoff)card.append(node('p','待 '+name(handoff.target_member_id)+' 接手 · '+handoff.summary,'card-summary'));
    const deps=(s.dependencies||[]).filter(d=>d.source_task_id===t.id&&d.status==='active');if(deps.length)card.append(node('p','等待 '+deps.map(d=>d.target.title+'（'+(d.target.owner_member_id?name(d.target.owner_member_id):'待分派')+'）').join('、'),'card-summary'));
    const git=adapters.git?.summarize(t.id,s.git);if(git)card.append(node('p',git,'card-git'));
    return card;
  }
  function request(r,s){
    const row=node('article','','record');
    add(row,node('h3','#'+r.id+' '+r.body),node('p',member(s,r.sender_member_id)+' → '+member(s,r.receiver_member_id),'meta'),node('p','模型读取 '+date(r.read_at)+' · 已处理 '+date(r.processed_at)+' · 请求解决 '+date(r.resolved_at),'meta'));
    (r.replies||[]).forEach(reply=>add(row,node('p',reply.body),node('p',(reply.evidence||'无附加证据')+' · '+date(reply.created_at),'meta')));
    return row;
  }
  function contract(c){
    const row=node('article','','record');add(row,node('h3',c.contract_key),node('p','当前 v'+c.current_version+' · 生效 '+(c.effective_version?'v'+c.effective_version:'尚未批准'),'meta'));
    (c.versions||[]).forEach(v=>add(row,node('h4','v'+v.version+' '+v.title),node('p',v.body),node('p',v.commit_ref||'','meta')));return row;
  }
  function readonlyDetail(t,p,s,adapters={}){
    const root=node('div'),title=node('h2',t.title);title.id='task-detail-title';
    add(root,node('p','CM-'+String(t.id).padStart(3,'0'),'eyebrow'),title,node('p',columns.find(c=>c[0]===column(t,p,s,adapters))[1]+' · '+member(s,t.owner_member_id),'detail-status'),node('p','声明范围','detail-label'),node('p',t.scope,'detail-value'),node('p','去重标识：'+t.intent_key,'meta'),node('p','创建 '+date(t.created_at)+' · 认领 '+date(t.claimed_at),'meta'));
    if(p)add(root,node('p','agent 自述 · '+date(p.updated_at),'detail-label'),node('p',p.summary),node('p','证据：'+(p.evidence||'未提供'),'meta'));
    const git=adapters.git?.summarize(t.id,s.git);if(git)add(root,node('p','Git 证据来源','detail-label'),node('p',git));
    (s.git?.workspaces||[]).filter(w=>w.task_id===t.id).forEach(w=>add(root,node('p','本地 Git · '+(w.branch||'detached HEAD')+' · '+(w.head||'无提交')+' · '+date(w.captured_at)+(w.stale?' · 已过期':''),'meta'),node('p',(w.paths||[]).join('、'))));
    (s.git?.deliveries||[]).filter(d=>d.task_id===t.id).forEach(d=>add(root,node('p',(d.source==='github_verified'?'GitHub 验证':'协作记录')+' · '+(d.pr_number?'PR #'+d.pr_number:d.branch||d.commit_sha||'交付')+' · '+d.state+' · '+date(d.sync_at||d.verified_at)+(d.stale?' · 同步过期':''),'meta')));
    const trace=node('div');root.append(trace);window.CoopagentsDelivery?.render(trace,s.git?.delivery_graph,{taskId:t.id,openTask:adapters.open});
    (s.dependencies||[]).filter(d=>d.source_task_id===t.id||d.target_task_id===t.id).forEach(d=>add(root,node('p','依赖 #'+d.id+' · '+d.status+' · '+(d.need||'')+' · '+(d.source?.title||d.source_task_id)+' → '+(d.target?.title||d.target_task_id),'meta')));
    (s.lifecycle?.handoffs||[]).filter(h=>h.task_id===t.id).forEach(h=>add(root,node('p','交接 · '+h.status+' · '+member(s,h.target_member_id)+' · '+h.summary,'meta')));
    const related=s.requests.filter(r=>r.task_id===t.id);add(root,node('p','关联技术请求','detail-label'));related.forEach(r=>root.append(request(r,s)));
    s.contracts.filter(c=>c.versions.some(v=>related.some(r=>r.id===v.source_request_id))).forEach(c=>root.append(contract(c)));
    return root;
  }
  window.CoopagentsBoard={columns,column,matchingTasks,card,readonlyDetail,request,contract};
})();
