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
