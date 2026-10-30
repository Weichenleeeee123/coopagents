'use strict';
(() => {
  const sessions=new WeakMap();
  const labels={supported:'已验证支持',unsupported:'不支持',unknown:'未验证',unavailable:'当前不可用',stale:'证据已过期'};
  const names={mcp:'MCP',project_context:'项目上下文',session_lifecycle:'会话生命周期',native_hook:'原生 hook',idle_wake:'空闲唤醒'};
  const time=value=>value?new Date(value).toLocaleString('zh-CN'):'未知';
  const el=(tag,value='',cls)=>{const n=document.createElement(tag);n.textContent=value??'';if(cls)n.className=cls;return n;};
  function render(root,data,context={}){
    if(!root)return;
    if(!data){sessions.delete(root);root.replaceChildren();return;}
    let state=sessions.get(root);
    const sameRoom=state?.room===context.roomId;
    if(!state||state.room!==context.roomId){state={room:context.roomId,expanded:new Set()};sessions.set(root,state);}
    if(sameRoom&&root.contains?.(document.activeElement)&&['SUMMARY','BUTTON'].includes(document.activeElement?.tagName))return;
    root.replaceChildren();
    function disclosure(key,label){
      const panel=el('details','','capability-evidence');panel.append(el('summary',label));panel.open=state.expanded.has(key);
      panel.addEventListener('toggle',()=>{if(panel.isConnected!==false&&sessions.get(root)===state){if(panel.open)state.expanded.add(key);else state.expanded.delete(key);}});
      return panel;
    }
    const section=el('section','','capability-discovery');section.setAttribute('aria-label','成员与 Harness 能力');
    section.append(el('h2','成员与 agent'));
    (data.members||[]).forEach(member=>{
      const row=el('article','','capability-member'),profile=el('header','','capability-profile'),agents=el('div','','capability-agents');
      profile.append(el('h3',member.display_name),el('p',(member.agent_count??member.agents?.length??0)+' 个会话','meta'));row.append(profile,agents);
      if(!(member.agents||[]).length)agents.append(el('p','尚无 agent 会话登记','muted'));
      (member.agents||[]).forEach(agent=>{
        const session=el('div','','capability-session');
        session.append(el('strong',(agent.harness||agent.tool)+' · '+({registered:'最近登记',stale:'登记已过期',unavailable:'当前不可用'}[agent.status]||'未知')),
          el('p',(agent.version||'unknown')+' · '+(agent.platform||'unknown')+' · '+(agent.repository||'未声明仓库')+' · '+(agent.branch||'未声明分支'),'meta'),
          el('p','最后登记 '+time(agent.updated_at),'meta'));
        const evidence=disclosure(JSON.stringify([member.member_id,agent.session_key,agent.tool]),'能力与连接证据');
        evidence.append(el('p','登记来源 '+(agent.evidence_source||'session_registry'),'meta'),
          el('p','最近出现 '+time(agent.last_seen_at)+' · '+(agent.recent_presence==='recent'?'检查点在最近 15 分钟内':agent.recent_presence==='stale'?'检查点已过期':'未知'),'meta'),
          el('p','事件送达 '+(agent.event_delivery_status||'unknown')+' · agent 处理 '+(agent.model_status||'unknown'),'meta'),
          el('p','连接状态 '+(agent.connection_status||'unknown')+' · 凭据 '+(agent.credential_status||'unknown'),'meta'));
        if(agent.task_id&&context.openTask){const b=el('button','任务 #'+agent.task_id);b.type='button';b.addEventListener('click',()=>context.openTask(agent.task_id));session.append(b);}
        Object.entries(agent.capabilities||{}).forEach(([key,value])=>{
          if(!names[key])return;
          const record=agent.capability_evidence?.[key];
          evidence.append(el('p',names[key]+'：'+(labels[value]||'未验证')+(record?' · '+record.evidence+' · '+time(record.verified_at):''),'meta'));
        });
        Object.entries(agent.reported_capabilities||{}).forEach(([key,value])=>{
          if(names[key])evidence.append(el('p','agent 自报 '+names[key]+'：'+({supported:'支持',unsupported:'不支持',unknown:'未知'}[value]||value)+' · 待验证','muted'));
        });
        session.append(evidence);agents.append(session);
      });
      section.append(row);
    });
    const matrix=disclosure('matrix','Harness 支持矩阵');
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
