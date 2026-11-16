'use strict';
(()=>{
  let project=null,epoch=0,selectedTool='codex-cli',setupExpanded=false;
  const roots=new Set();
  const element=(tag,value='',cls='')=>{const node=document.createElement(tag);node.textContent=String(value??'');if(cls)node.className=cls;return node;};
  const add=(node,...children)=>{node.append(...children);return node;};
  const when=value=>value?new Date(value).toLocaleString('zh-CN'):'—';
  function clear(){epoch++;project=null;selectedTool='codex-cli';setupExpanded=false;roots.forEach(root=>root.replaceChildren());roots.clear();}
  function prepare(root,snapshot){
    if(!root)return false;
    const key=snapshot.me.room_id+':'+snapshot.me.member_id;
    if(project!==key){clear();project=key;}
    roots.add(root);root.replaceChildren();return true;
  }
  function renderSetup(root,snapshot,context){
    if(!prepare(root,snapshot))return;
    const select=element('select'),commands=element('pre','','collaboration-commands'),settings=element('p','','meta');
    for(const [value,label] of [['codex-cli','Codex CLI'],['codex-desktop','Codex 桌面（本地执行）'],['claude-code','Claude Code']]){
      const option=element('option',label);option.value=value;select.append(option);
    }
    select.value=selectedTool;select.setAttribute('aria-label','自动检查点接入工具');
    const quote=value=>"'"+String(value).replaceAll("'","''")+"'";
    function update(){
      const tool=select.value;selectedTool=tool;
      commands.textContent='# PowerShell · 使用已安装 Coopagents 的 Python 环境\n'+
        '$env:COOPAGENTS_SERVICE_URL = '+quote(context.origin)+'\n'+
        '$env:COOPAGENTS_PROJECT_ID = '+quote(snapshot.me.room_id)+'\n'+
        "$env:COOPAGENTS_AGENT_TOKEN = 'YOUR_PERSONAL_AGENT_TOKEN'\n"+
        'python -I -m coopagents.checkpoint_hook --tool '+tool+' --config-preview\n'+
        'python -I -m coopagents.checkpoint_hook --tool '+tool+' --doctor';
      settings.textContent=tool==='claude-code'?
        '审阅生成片段后，手动合并到 .claude/settings.local.json；保留原有 hooks。重新启动 Claude Code。':
        '审阅生成片段后，手动合并到 .codex/hooks.json；保留原有 hooks。在原生工具 /hooks 中审阅并批准准确的配置版本。';
    }
    select.addEventListener('change',update);update();
    add(root,element('h3','让 agent 在工作节点读取协作上下文'),
      element('p','1. 在启动 agent 的进程环境设置项目地址与个人 agent 令牌。环境变量须被原生工具继承。'),
      add(element('label','2. 选择原生工具'),select),commands,settings,
      element('p','3. 先运行 doctor 验证挑战写入与读回，再启动真实会话、提交新提示，并回到此页刷新接入结果。'),
      element('p','SessionStart、UserPromptSubmit 和 PostToolUse 会返回协作摘要；工具结束事件每个会话最多每 30 秒一次。失败只显示警告，不阻塞工作。','muted'),
      element('p','配置预览不代表 agent 已接入。可以用 --export NEW_FILE 创建新片段，现有文件会被保留。不要把个人令牌或本机配置提交到 Git。','muted'));
  }
  const visibleLimit=6;
  const identifier=value=>Number.isSafeInteger(value)&&value>0;
  const excerpt=value=>{const text=String(value??'');return text.length>180?text.slice(0,180)+'…':text;};
  const list=value=>Array.isArray(value)?value:[];
  function workflowSection(root,id,title){const section=add(element('section'),element('h3',title));section.id=id;root.append(section);return section;}
  function navigation(root,label,target,context,renderEpoch){
    if(typeof context.openWorkflowItem!=='function')return;
    const link=element('button',label,'link-button');link.type='button';
    link.addEventListener('click',()=>{if(renderEpoch===epoch&&(!context.isCurrent||context.isCurrent()))context.openWorkflowItem(target);});root.append(link);
  }
  function taskNavigation(root,id,context,renderEpoch){if(identifier(id))navigation(root,'查看任务 #'+id,{kind:'task',id},context,renderEpoch);}
  function renderWorkflow(root,snapshot,context,renderEpoch){
    const workflow=snapshot.workflow;
    if(!workflow){root.append(element('p','当前服务尚未提供工作流摘要，可在协作与共享上下文查看原始记录。','muted'));return;}
    const onboarding=workflow.onboarding||{},first=workflowSection(root,'workflow-onboarding','第一次有效协作');
    add(first,element('p','当前项目身份：'+(onboarding.identity_verified===true?'已验证（网页读取）':'暂无验证记录'),'meta'),
      element('p','网页身份读取不证明原生 agent 已加载。','muted'));
    const exchange=onboarding.addressed_exchange;
    if(exchange&&identifier(exchange.request_id)&&exchange.sender_member_id&&exchange.receiver_member_id&&exchange.sender_member_id!==exchange.receiver_member_id&&[exchange.sender_member_id,exchange.receiver_member_id].includes(snapshot.me.member_id)){
      add(first,element('p','交流 #'+exchange.request_id+' · '+context.memberName(exchange.sender_member_id)+' → '+context.memberName(exchange.receiver_member_id),'meta'),
        element('p','定向问题投递：'+(exchange.delivered===true?'已记录':'暂无记录')+' · 责任人答复：'+(exchange.replied===true?'已记录':'暂无记录')+' · 发起者显式读回：'+(exchange.requester_reply_read===true?'已记录':'暂无记录'),'meta'));
      if(exchange.delivered===true&&exchange.replied===true&&exchange.requester_reply_read===true)first.append(element('p','双人交流记录已齐备；可在原请求中查看具体答复。'));
      navigation(first,'查看交流 #'+exchange.request_id,{kind:'request',id:exchange.request_id},context,renderEpoch);
    }else first.append(element('p','尚无定向双人交流记录。向明确负责人提出具体问题后，可在此查看投递、答复和读回。','muted'));
    first.append(element('p','显式读回只记录读操作，不证明模型理解，也不代表任务进展。','muted'));

    const allRequests=list(workflow.requests),requests=allRequests.filter(item=>!item.resolved&&!item.resolved_at&&['ordinary','current'].includes(item.route_state));
    const ownerQuestions=list(workflow.owner_questions).filter(item=>['queued','blocked'].includes(item.status));
    const waiting=workflowSection(root,'workflow-requests','当前协作等待');
    const waits={awaiting_assignment:'等待明确收件人',awaiting_recipient_read:'等待收件人读取记录',read:'已记录收件人读取，等待答复',processing:'已记录处理确认，等待答复',reply_waiting_for_sender_read:'答复已到达，等待发起者显式读回',awaiting_requester_resolution:'等待发起者确认处理结果'};
    if(!requests.length&&!ownerQuestions.length)waiting.append(element('p','本页暂无待处理请求。','muted'));
    for(const question of ownerQuestions.slice(0,visibleLimit)){
      const row=add(element('article','','record workflow-owner-question'),element('h4','负责人问题 · '+excerpt(question.body)),
        element('p',question.wait_reason==='target_cancelled'?'目标任务已取消，问题保留等待恢复。':'等待目标任务分配负责人；问题已保存，尚未投递。','meta'));
      taskNavigation(row,question.target_task_id,context,renderEpoch);waiting.append(row);
    }
    for(const request of requests.slice(0,visibleLimit)){
      const row=add(element('article','','record workflow-request'),element('h4','请求 #'+request.id+' · '+excerpt(request.body)),
        element('p',context.memberName(request.sender_member_id)+' → '+context.memberName(request.receiver_member_id)+' · '+(request.route_state==='current'?'当前任务依赖路由':'普通请求'),'meta'),
        element('p',waits[request.wait_reason]||'等待更多协作记录'),
        element('p','投递：'+(request.delivered===true?'已记录':'暂无记录')+' · 收件人读取：'+(request.recipient_read===true?'已记录':'暂无记录')+' · 答复：'+(request.replied===true?'已记录':'暂无记录')+' · 发起者读回：'+(request.sender_reply_read===true?'已记录':'暂无记录'),'meta'));
      if(identifier(request.id)){row.id='workflow-request-'+request.id;navigation(row,'查看请求 #'+request.id,{kind:'request',id:request.id},context,renderEpoch);}
      taskNavigation(row,request.task_id,context,renderEpoch);waiting.append(row);
    }
    if(allRequests.some(item=>item.resolved||item.resolved_at||['historical','closed'].includes(item.route_state)))waiting.append(element('p','历史路由与已解决请求不计入当前等待，原始记录保留在协作详情。','muted'));

    const changes=list(workflow.agreement_changes).filter(item=>item.review_required===true),agreements=workflowSection(root,'workflow-agreements','已用约定的变化');
    if(!changes.length)agreements.append(element('p','本页没有待复核的已用约定。','muted'));
    for(const change of changes.slice(0,visibleLimit)){
      const row=add(element('article','','record workflow-agreement'),element('h4',excerpt(change.title)||'约定 #'+change.contract_id),
        element('p','任务 #'+change.task_id+' · 基线 v'+change.baseline_version+' → 当前批准 v'+change.effective_version+' · 待复核','meta'));
      if(identifier(change.contract_id)){row.id='workflow-agreement-'+change.task_id+'-'+change.contract_id;navigation(row,'查看约定 #'+change.contract_id,{kind:'contract',id:change.contract_id},context,renderEpoch);}
      taskNavigation(row,change.task_id,context,renderEpoch);agreements.append(row);
    }
    if(changes.length)agreements.append(element('p','阅读新版本不会自动批准或采用；当前任务执行者需要明确记录所用版本。','muted'));

    const decisionLabels={contract:'约定审核',handoff:'责任交接',delivery:'交付关联建议',unassigned_task:'待认领任务',agreement_review:'约定版本复核'};
    const decisions=list(workflow.decisions).filter(item=>Object.hasOwn(decisionLabels,item.kind)),pending=workflowSection(root,'workflow-decisions','需要确认的事项');
    const authority={contract:'需要人工网页身份处理；当前身份不能执行此决定。',handoff:'仅拟接收成员可在网页确认；当前身份不符合。',delivery:'仅项目管理员可在网页确认；当前身份不符合。',unassigned_task:'由自己的 agent 认领；网页只显示任务入口。',agreement_review:'由当前任务执行者在 agent 中明确记录；网页只显示约定与任务入口。'};
    if(!decisions.length)pending.append(element('p','本页暂无待确认事项。','muted'));
    for(const card of decisions.slice(0,visibleLimit)){
      const payload=card.payload||{},human=['contract','handoff','delivery'].includes(card.kind);
      const row=add(element('article','','record workflow-decision'),element('h4',decisionLabels[card.kind]+' · '+excerpt(card.title||card.summary||'#'+card.id)),
        element('p',human?'需要人工决定':'需要个人 agent 操作','meta'));
      if(identifier(card.id))row.id='workflow-decision-'+card.kind+'-'+card.id+(identifier(card.task_id)?'-'+card.task_id:'');
      if(card.title&&card.summary)row.append(element('p',excerpt(card.summary)));
      if(card.kind==='contract')row.append(element('p','约定 #'+card.id+' · 待审 v'+payload.version,'meta'));
      if(card.kind==='handoff')row.append(element('p','任务 #'+payload.task_id+' · 当前修订 r'+payload.expected_revision,'meta'));
      if(card.kind==='delivery')row.append(element('p','建议 #'+card.id+' · '+excerpt(card.object_key),'meta'));
      row.append(element('p',human&&card.eligible===true?'当前网页身份可前往已有详情处理。':authority[card.kind],'muted'));
      if(['contract','agreement_review'].includes(card.kind)&&identifier(card.id))navigation(row,'查看约定 #'+card.id,{kind:'contract',id:card.id},context,renderEpoch);
      if(card.kind==='handoff')taskNavigation(row,payload.task_id,context,renderEpoch);
      if(card.kind==='unassigned_task')taskNavigation(row,card.id,context,renderEpoch);
      if(card.kind==='agreement_review')taskNavigation(row,card.task_id,context,renderEpoch);
      if(card.kind==='delivery')navigation(row,'查看交付建议 #'+card.id,{kind:'delivery'},context,renderEpoch);
      pending.append(row);
    }

    const activity=list(workflow.member_activity);
    if(activity.length){
      const observations=workflowSection(root,'workflow-observations','最近协作观测');
      for(const member of activity.slice(0,visibleLimit))observations.append(element('p',context.memberName(member.member_id)+' · 检查点 '+when(member.last_checkpoint_at)+' · 会话 '+when(member.last_session_at)+' · 响应状态：未知','meta'));
    }
    if(workflow.truncated||workflow.has_more||[requests,changes,decisions,activity].some(items=>items.length>visibleLimit)){
      root.append(element('p','这里只显示部分工作流记录；请打开协作、约定或任务详情查看完整信息。','muted'));
      navigation(root,'查看协作详情',{kind:'requests'},context,renderEpoch);
    }
  }
  function renderPanel(root,snapshot,context){
    if(!prepare(root,snapshot))return;
    const collaboration=snapshot.collaboration||{},records=collaboration.checkpoints||[],diagnostics=collaboration.diagnostics||[];
    const own=records.filter(record=>record.member_id===snapshot.me.member_id);
    const hook=own.filter(record=>record.last_hook_at).sort((a,b)=>Date.parse(b.last_hook_at)-Date.parse(a.last_hook_at))[0];
    const latest=diagnostics[0];
    add(root,element('h2','自动协作检查点'),element('p','网页连接：最近一次项目读取成功 · '+when(snapshot.server_time),'meta'),
      element('p',latest?.status==='completed'?'诊断已完成：个人 agent 凭据已完成挑战写入与读回 · '+when(latest.completed_at):latest?'诊断尚未完成：'+(latest.status==='sent'?'已发送挑战，等待读回':'已读回，等待确认'):'尚无真实诊断，请在启动 agent 的环境中运行 doctor。'),
      element('p',hook?'收到入口报告的 hook 检查点 · '+(hook.hook_stale?'已过期（超过 5 分钟）':'最近 5 分钟内收到')+' · '+when(hook.last_hook_at):'尚未收到个人 agent 入口报告的 hook 检查点。'),
      element('p','检查点记录说明服务收到了个人 agent 的调用。它不代表在线状态，也不能单独证明模型已消费上下文。诊断结果与实际会话报告分开记录。','muted'));
    const refresh=element('button','刷新接入结果'),feedback=element('p','','meta');refresh.type='button';feedback.setAttribute('role','status');
    const renderEpoch=epoch;
    refresh.addEventListener('click',async()=>{refresh.disabled=true;try{await context.sync();}catch(error){if(renderEpoch===epoch&&context.isCurrent())feedback.textContent=error.message;}finally{if(renderEpoch===epoch&&context.isCurrent())refresh.disabled=false;}});
    add(root,refresh,feedback);
    renderWorkflow(root,snapshot,context,renderEpoch);
    const setup=add(element('details'),element('summary','查看接入步骤')),body=element('div');setup.append(body);root.append(setup);renderSetup(body,snapshot,context);roots.delete(body);
    setup.open=setupExpanded;setup.addEventListener('toggle',()=>{if(renderEpoch===epoch)setupExpanded=setup.open;});
    if(records.length){
      root.append(element('h3','最近会话检查点'));
      const sources={hook:'入口报告的 hook',manual:'手动调用',tool:'工具调用'};
      for(const record of records){
        add(root,add(element('article','','record collaboration-session'),
          element('h4',context.memberName(record.member_id)+' · '+record.tool),
          element('p','会话 '+record.session_key+' · '+(sources[record.source]||'未知来源')),
          element('p',record.event+' · '+when(record.updated_at)+' · '+(record.stale?'已过期':'最近 5 分钟内收到'),'meta')));
      }
    }
  }
  const api={renderPanel,renderSetup,clear};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.CoopagentsCollaboration=api;
})();
