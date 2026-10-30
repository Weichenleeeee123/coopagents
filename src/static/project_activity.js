'use strict';
(() => {
  const types={delivery_association:'交付关联',task_created:'任务创建',progress_reported:'进度汇报',claim_task:'认领任务',release_task:'释放任务',
    propose_handoff:'提出交接',accept_handoff:'接受交接',reject_handoff:'拒绝交接',force_handoff:'管理员交接',
    cancel_task:'取消任务',reopen_task:'恢复任务',session_registered:'Agent 会话登记',request_sent:'发送协作请求',
    request_read:'读取协作请求',request_processed:'确认处理请求',request_resolved:'解决协作请求',reply_sent:'发送协作回复',
    contract_proposed:'提出约定',contract_approved:'批准约定',contract_rejected:'拒绝约定',git_observed:'本地 Git 检查点',
    github_delivery_verified:'GitHub 交付核验',release_verified:'GitHub Release 核验'};
  const sources={task:'任务',agent_report:'Agent 自述',task_lifecycle:'任务记录',session_registry:'会话登记',
    collaboration_request:'协作请求',collaboration_reply:'协作回复',contract_event:'公共约定',local_git:'本地 Git',github_verified:'GitHub 验证'};
  const el=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text??'';if(cls)n.className=cls;return n;};
  const filters={type:'',source:'',task:''};
  function safeReleaseURL(value){try{const u=new URL(value);return u.protocol==='https:'&&u.hostname==='github.com'&&!u.username&&!u.password&&!u.port&&/^\/[\w.-]+\/[\w.-]+\/releases\/tag\/[\w.%+-]+$/.test(u.pathname)&&!u.search&&!u.hash?u.href:null;}catch{return null;}}
  function referenceText(reference){
    if(!reference||typeof reference!=='object')return '';
    return ['tag_name','state','branch','head','commit_sha','release_id','pr_number'].filter(key=>['string','number'].includes(typeof reference[key]))
      .map(key=>String(reference[key]).slice(0,250)).join(' · ');
  }
  function render(root,activity,context={}){
    if(!root)return;
    root.replaceChildren();
    const section=el('section','','project-activity');section.setAttribute('aria-label','项目活动');
    section.append(el('h2','项目活动'));
    if(!activity||!Array.isArray(activity.items)){section.append(el('p','暂无结构化活动。','muted'));root.append(section);return;}
    const valid=activity.items.filter(item=>item&&typeof item==='object'&&types[item.type]&&typeof item.summary==='string'&&typeof item.occurred_at==='string');
    const addFilter=(name,label,values)=>{
      const control=el('label',label,'activity-filter');const select=document.createElement('select');
      const all=el('option','全部');all.value='';select.append(all);
      values.forEach(([value,text])=>{const option=el('option',text);option.value=value;select.append(option);});
      select.value=filters[name];select.addEventListener('change',()=>{filters[name]=select.value;render(root,activity,context);});
      control.append(select);return control;
    };
    const taskIds=[...new Set(valid.map(item=>item.task_id).filter(id=>Number.isInteger(id)&&id>0))].sort((a,b)=>a-b);
    const toolbar=el('div','','activity-filters');
    toolbar.append(addFilter('type','类型',Object.entries(types)),addFilter('source','来源',Object.entries(sources)),
      addFilter('task','任务',taskIds.map(id=>[String(id),'任务 #'+id])));section.append(toolbar);
    const filtered=valid.filter(item=>(!filters.type||item.type===filters.type)&&(!filters.source||item.source===filters.source)
      &&(!filters.task||item.task_id===Number(filters.task)));
    const items=filtered
      .map((item,index)=>({item,index,time:Date.parse(item.occurred_at)})).filter(entry=>Number.isFinite(entry.time))
      .sort((a,b)=>b.time-a.time||a.index-b.index).slice(0,100);
    if(!items.length)section.append(el('p','暂无结构化活动。','muted'));
    items.forEach(({item})=>{
      const row=el('article','','activity-item');
      const heading=el('p',types[item.type]+' · '+item.summary.slice(0,280),'activity-summary');
      const time=new Date(item.occurred_at).toLocaleString('zh-CN');
      row.append(heading,el('p',time+' · '+(sources[item.source]||'协作记录')+(Number.isInteger(item.task_id)&&item.task_id>0?' · 任务 #'+item.task_id:''),'meta'));
      const reference=referenceText(item.reference);if(reference)row.append(el('p',reference,'meta'));
      if(item.reference?.stale===true)row.append(el('p','远端证据已过期，需重新同步。','activity-freshness stale'));
      if(item.reference?.unavailable===true)row.append(el('p','远端对象当前不可用。','activity-freshness unavailable'));
      const url=safeReleaseURL(item.reference?.url);if(item.type==='release_verified'&&url){const link=el('a','查看 Release ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';row.append(link);}
      if(Number.isInteger(item.task_id)&&item.task_id>0&&typeof context.openTask==='function'){
        const task=el('button','打开任务');task.type='button';task.addEventListener('click',()=>context.openTask(item.task_id));row.append(task);
      }
      section.append(row);
    });
    if(activity.truncated===true)section.append(el('p','仅显示最近 '+items.length+' 条活动。','muted'));
    root.append(section);
  }
  const api={render};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.CoopagentsProjectActivity=api;
})();
