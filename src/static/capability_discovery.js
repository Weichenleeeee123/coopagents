'use strict';
(() => {
  const labels={supported:'已验证支持',unsupported:'不支持',unknown:'未验证',unavailable:'当前不可用',stale:'证据已过期'};
  const names={mcp:'MCP',project_context:'项目上下文',session_lifecycle:'会话生命周期',native_hook:'原生 hook',idle_wake:'空闲唤醒'};
  const time=value=>value?new Date(value).toLocaleString('zh-CN'):'未知';
  const el=(tag,value='',cls)=>{const n=document.createElement(tag);n.textContent=value??'';if(cls)n.className=cls;return n;};
  function render(root,data,context={}){
    if(!root)return;root.replaceChildren();if(!data)return;
    const section=el('section','','capability-discovery');section.setAttribute('aria-label','成员与 Harness 能力');
    section.append(el('h2','成员与 Harness 能力'),el('p','会话登记、连接、事件送达和模型处理分别记录。登记可用于发现队友，响应能力以实际证据为准。','muted'));
    (data.members||[]).forEach(member=>{
      const row=el('article','','member-row');row.append(el('h3',member.display_name),el('p',(member.agent_count||0)+' 个 agent 会话','meta'));
      (member.agents||[]).forEach(agent=>{
        const session=el('div','','session');
        session.append(el('strong',(agent.harness||agent.tool)+' · '+({registered:'最近登记',stale:'登记已过期',unavailable:'当前不可用'}[agent.status]||'未知')),
          el('p',(agent.version||'unknown')+' · '+(agent.platform||'unknown')+' · '+(agent.repository||'未声明仓库')+' · '+(agent.branch||'未声明分支'),'meta'),
          el('p','最后登记 '+time(agent.updated_at)+' · '+(agent.evidence_source||'session_registry'),'meta'));
        if(agent.task_id&&context.openTask){const b=el('button','任务 #'+agent.task_id);b.type='button';b.addEventListener('click',()=>context.openTask(agent.task_id));session.append(b);}
        Object.entries(agent.capabilities||{}).forEach(([key,value])=>{
          if(!names[key])return;
          const evidence=agent.capability_evidence?.[key];
          session.append(el('p',names[key]+'：'+(labels[value]||'未验证')+(evidence?' · '+evidence.evidence+' · '+time(evidence.verified_at):''),'meta'));
        });
        Object.entries(agent.reported_capabilities||{}).forEach(([key,value])=>{
          if(names[key])session.append(el('p','agent 自报 '+names[key]+'：'+value+' · 待验证','muted'));
        });
        row.append(session);
      });
      section.append(row);
    });
    const matrix=el('details');matrix.append(el('summary','查看 Harness 版本与平台支持矩阵'));
    (data.harnesses||[]).forEach(h=>{
      const row=el('article','','record'),e=h.evidence||{};
      row.append(el('h3',h.name+' · '+(e.version||'unknown')+' · '+(e.platform||'unknown')));
      Object.entries(h.capabilities||{}).forEach(([key,value])=>{if(names[key])row.append(el('p',names[key]+'：'+(labels[value]||'未验证'),'meta'));});
      row.append(el('p','来源 '+(e.source||'unknown')+' · '+time(e.verified_at),'meta'),el('p',e.constraints||'','muted'));
      Object.values(h.capability_evidence||{}).forEach(v=>row.append(el('p','证据：'+v.evidence+' · 确认成员 '+v.verified_by+' · '+time(v.verified_at),'meta')));
      matrix.append(row);
    });
    section.append(matrix);if(data.verification_truncated)section.append(el('p','验证记录超出展示范围，请按具体 Harness 查询。','muted'));root.append(section);
  }
  const api={render};if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.CoopagentsCapabilities=api;
})();
