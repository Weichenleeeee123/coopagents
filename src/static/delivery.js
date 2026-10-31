'use strict';
(() => {
  const el=(tag,value='',cls)=>{const n=document.createElement(tag);n.textContent=value??'';if(cls)n.className=cls;return n;};
  const time=v=>v?new Date(v).toLocaleString('zh-CN'):'尚未同步';
  const sources={explicit:'明确关联',suggested:'待确认建议',observed:'只读观测'};
  const states={pending_confirmation:'待确认',pending_sync:'待同步',unavailable:'当前不可用',stale:'证据已过期',merged:'已合并',open:'打开',closed_unmerged:'已关闭未合并',released:'已发布',confirmed:'已确认',rejected:'已拒绝',observed:'只读观测'};
  function render(root,graph,context={}){
    if(!root)return;root.replaceChildren();if(!graph)return;
    const section=el('section','','delivery-traceability');section.setAttribute('aria-label','交付关联');
    section.append(el('h2','交付关联'),el('p','合并、发布与任务验收分别记录','meta'));
    const objects=(graph.items||[]).filter(o=>!context.taskId||(o.task_ids||[]).includes(context.taskId));
    if(!objects.length)section.append(el('p','暂无交付关联。','muted'));
    objects.forEach(o=>{
      const row=el('article','','delivery-item');row.append(el('h3',({branch:'分支',commit:'Commit',pr:'PR',release:'Release'}[o.kind]||o.kind)+' · '+o.value),el('p',o.repository||'未绑定仓库','meta'));
      (o.task_ids||[]).forEach(id=>{const b=el(context.openTask?'button':'span','任务 #'+id);if(context.openTask){b.type='button';b.addEventListener('click',()=>context.openTask(id));}row.append(b);});
      (o.associations||[]).forEach(a=>{
        row.append(el('p',(sources[a.relationship_source]||a.relationship_source)+' · 任务 #'+a.task_id+' · '+(states[a.state]||a.state),'detail-value'),
          el('p','建立者 '+(context.memberName?.(a.linked_by)||a.linked_by||'授权来源')+' · '+time(a.linked_at)+' · '+(a.source||'未知来源'),'meta'),
          el('p','状态同步 '+time(a.sync_at)+(a.stale?' · 证据已过期':'')+(a.unavailable?' · 当前不可用':''),'meta'));
        if(a.evidence)row.append(el('p','依据：'+a.evidence,'meta'));
        if(a.relationship_source==='suggested'&&a.status==='pending'&&a.state==='pending_confirmation'&&context.canManage&&context.api){
          const feedback=el('p','','meta');const buttons=[];
          for(const [decision,label] of [['confirmed','确认关联'],['rejected','拒绝建议']]){
            const b=el('button',label);b.type='button';buttons.push(b);
            b.addEventListener('click',async()=>{
              if(context.isCurrent&&!context.isCurrent())return;buttons.forEach(n=>n.disabled=true);
              try{await context.api('/api/operations/decide_delivery',{suggestion_id:a.suggestion_id,decision});
                if(context.isCurrent&&!context.isCurrent())return;
                await context.sync?.();
              }catch(e){if(!context.isCurrent||context.isCurrent())feedback.textContent=e.message;}
              finally{buttons.forEach(n=>n.disabled=false);}
            });row.append(b);
          }
          row.append(feedback);
        }
      });section.append(row);
    });
    if(graph.truncated)section.append(el('p','交付数据已截断，请按任务或交付对象查询。','muted'));root.append(section);
  }
  const api={render};if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.CoopagentsDelivery=api;
})();
