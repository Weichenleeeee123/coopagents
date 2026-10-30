'use strict';
(() => {
  const labels={local_git:'本地 Git 观测',github_verified:'GitHub 验证',agent_report:'agent 自述'};
  const caption=value=>labels[value?.source]||'协作记录';
  function connected(git){return git?.connection && (git.connection.active===true||git.connection.status==='active');}
  function deliveries(taskId,git){return connected(git)?(git.deliveries||[]).filter(d=>d.task_id===taskId&&d.source==='github_verified'&&!d.stale):[];}
  function state(task,progress,git){
    if(task.cancelled_at||task.state==='cancelled')return 'cancelled';
    if(progress?.state==='blocked')return 'blocked';
    const all=deliveries(task.id,git),phase=all.filter(d=>!d.commit_sha);
    const rows=phase.length?phase:all;
    if(rows.length){
      if(rows.every(d=>d.state==='merged'))return 'merged';
      if(rows.some(d=>['open','pr_open'].includes(d.state)))return 'pr_open';
      if(rows.some(d=>d.state==='pushed'))return 'pushed';
      return 'working';
    }
    return progress?.state;
  }
  function safeURL(value){
    try {const u=new URL(value);return u.protocol==='https:'&&u.hostname==='github.com'&&!u.username&&!u.password&&!u.port&&/^\/[\w.-]+\/[\w.-]+\/(pull\/\d+|commit\/[a-f0-9]{40,64})$/.test(u.pathname)&&!u.search&&!u.hash?u.href:null;}catch{return null;}
  }
  function safeReleaseURL(value){
    try {const u=new URL(value);return u.protocol==='https:'&&u.hostname==='github.com'&&!u.username&&!u.password&&!u.port&&/^\/[\w.-]+\/[\w.-]+\/releases\/tag\/[^/]+$/.test(u.pathname)&&!u.search&&!u.hash?u.href:null;}catch{return null;}
  }
  function checks(delivery){
    const head=delivery.head_sha||delivery.head;
    if(!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(head||'')||delivery.checks_truncated||delivery.statuses_truncated)return '检查未知';
    const runs=(delivery.checks||[]).filter(c=>c.head_sha===head);
    const statuses=(delivery.statuses||[]).filter(c=>c.head_sha===head);
    if(!runs.length&&!statuses.length)return '检查未知';
    if(runs.some(c=>['failure','timed_out','cancelled','action_required','startup_failure'].includes(c.conclusion))||statuses.some(c=>['failure','error'].includes(c.state)))return '检查未通过';
    if(runs.some(c=>c.status!=='completed')||statuses.some(c=>c.state==='pending'))return '检查进行中';
    if(runs.every(c=>['success','neutral','skipped'].includes(c.conclusion))&&statuses.every(c=>c.state==='success'))return '检查通过';
    return '检查未知';
  }
  const element=(tag,value,cls)=>{const node=document.createElement(tag);node.textContent=value??'';if(cls)node.className=cls;return node;};
  const append=(parent,...children)=>{children.forEach(c=>parent.append(c));return parent;};
  const when=value=>value?new Date(value).toLocaleString('zh-CN'):'—';
  function summarize(taskId,git){
    const rows=(git?.deliveries||[]).filter(d=>d.task_id===taskId&&d.source==='github_verified');
    const local=(git?.workspaces||[]).filter(w=>w.task_id===taskId);
    return [...local.map(w=>(w.branch||'detached HEAD')+(w.stale?' · 观测过期':' · 本地 Git')),
      ...rows.map(d=>'GitHub 验证 · '+(d.pr_number?'PR #'+d.pr_number:(d.commit_sha?'提交 '+d.commit_sha.slice(0,8):(d.branch||'远端分支')))+' · '+checks(d)+(d.stale?' · 同步过期':'')+(!connected(git)?' · 授权不可用':''))].join(' / ');
  }
  function renderDetails(container,task,git,context){
    append(container,element('p','Git 开发与交付','detail-label'));
    const local=(git?.workspaces||[]).filter(w=>w.task_id===task.id);
    if(!local.length)append(container,element('p','尚无本地 Git 检查点。','muted'));
    local.forEach(w=>append(container,append(element('article','','git-evidence'),
      element('p',(w.branch||'detached HEAD')+' · '+(w.head?w.head.slice(0,12):'尚无提交')),
      element('p',caption(w)+' · '+context.memberName(w.member_id)+' · '+when(w.captured_at)+(w.stale?' · 已过期':''),'meta'),
      element('p',w.paths.length?'变更路径：'+w.paths.join('、')+(w.paths_truncated?'（显示部分，共 '+w.path_count+' 条）':''):'工作区没有已跟踪文件的待提交变更。','detail-value'))));
    const remote=(git?.deliveries||[]).filter(d=>d.task_id===task.id);
    remote.forEach(d=>{
      const row=element('article','','git-evidence');
      const isRelease=d.release_id!==undefined&&d.release_id!==null;
      const label=isRelease?'GitHub Release '+(d.tag_name||'')+' · '+({draft:'草稿',prerelease:'预发布',published:'已发布',unavailable:'关联不可用'}[d.state]||d.state):(d.pr_number?'PR #'+d.pr_number:(d.commit_sha?'提交 '+d.commit_sha.slice(0,12):(d.branch||'分支')))+' · '+({open:'PR 已打开',closed_unmerged:'PR 已关闭，未合并',merged:'已合并',pushed:'已推送',unavailable:'关联不可用'}[d.state]||d.state);
      const url=isRelease?safeReleaseURL(d.url):safeURL(d.url); const heading=element(url?'a':'p',label);
      if(url){heading.href=url;heading.target='_blank';heading.rel='noopener noreferrer';}
      append(row,heading,...(isRelease?[element('p',(d.name||d.tag_name||'')+' · '+(d.assets?.length||0)+' 项资产元数据'+(d.assets_truncated?'（仅显示部分）':''),'detail-value')]:[element('p',checks(d)+' · HEAD '+(d.head_sha||d.head||'').slice(0,12),'meta')]),
        element('p',caption(d)+' · '+when(d.sync_at||d.verified_at)+(d.stale?' · 同步过期':'')+(!connected(git)?' · 仓库授权不可用':''),'meta'));
      container.append(row);
    });
    const events=(git?.events||[]).filter(e=>e.task_id===task.id).sort((a,b)=>Date.parse(b.captured_at)-Date.parse(a.captured_at)||b.id-a.id).slice(0,12);
    if(events.length){const history=element('details');append(history,element('summary','Git 检查点记录 · '+events.length));events.forEach(e=>append(history,element('p',when(e.captured_at)+' · '+(e.branch||'detached HEAD')+' · '+(e.head||'无提交').slice(0,12),'meta')));container.append(history);}
    if(!task.cancelled_at&&git?.binding&&connected(git)&&git.can_manage){
      const form=element('form','','git-link-form'),branch=element('input'),pr=element('input'),commit=element('input'),release=element('select'),submit=element('button','关联交付'),feedback=element('p','','meta');
      branch.name='branch';branch.placeholder='分支，例如 feature/login';pr.name='pr_number';pr.type='number';pr.min='1';pr.placeholder='或 PR 编号';submit.type='submit';
      commit.name='commit_sha';commit.placeholder='或完整提交 SHA';commit.maxLength=64;
      release.name='release_id';const emptyRelease=element('option','选择已发现的 Release');emptyRelease.value='';release.append(emptyRelease);
      (git.releases||[]).slice(0,20).forEach(item=>{const option=element('option',item.tag_name+' · '+(item.name||item.tag_name));option.value=String(item.release_id);release.append(option);});
      append(form,append(element('label','分支'),branch),append(element('label','PR 编号'),pr),append(element('label','独立提交 SHA'),commit),append(element('label','GitHub Release'),release),submit,feedback);
      form.addEventListener('submit',async e=>{e.preventDefault();submit.disabled=true;try{const payload={task_id:task.id};if(branch.value)payload.branch=branch.value;if(pr.value)payload.pr_number=Number(pr.value);if(commit.value)payload.commit_sha=commit.value;if(release.value)payload.release_id=Number(release.value);await context.api('/api/git/github/link',payload);if(!context.isCurrent())return;document.activeElement?.blur();await context.sync();feedback.textContent='关联已保存，下次远端核对后显示证据。';}catch(error){feedback.textContent=error.message;}finally{submit.disabled=false;}});
      container.append(form);
    }
    append(container,element('p','合并记录属于交付证据；任务验收仍由团队确认。','muted'));
    if(task.owner_member_id===context.me.member_id)append(container,element('p','自己的 agent 可用 link_delivery(task_id, branch / pr_number / commit_sha / release_id) 明确关联交付。','muted'));
  }
  let room=null,authorization=null;
  function clear(){room=null;authorization=null;}
  function renderAuthorization(root,status,snapshot,context){
    if(!authorization||authorization.room!==snapshot.me.room_id)return;
    const pending=element('div','','git-authorization'),a=element('a','打开 GitHub 完成授权 ↗'),finish=element('button','我已授权，完成连接');
    a.href=authorization.url;a.target='_blank';a.rel='noopener noreferrer';finish.type='button';
    finish.addEventListener('click',async()=>{if(!authorization||authorization.room!==snapshot.me.room_id)return;finish.disabled=true;try{await context.api('/api/git/github/finish',{state:authorization.state});if(!context.isCurrent())return;authorization=null;document.activeElement?.blur();await context.sync();}catch(error){status.textContent=error.message;}finally{finish.disabled=false;}});
    append(pending,a,finish);root.append(pending);
  }
  function renderPanel(root,snapshot,context){
    if(!root)return;
    if(room!==snapshot.me.room_id){room=snapshot.me.room_id;authorization=null;}
    if(root.contains(document.activeElement)&&['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
    const panel=root;
    panel.replaceChildren();const git=snapshot.git||{};
    root=element('section','','git-block');root.setAttribute('aria-label','共同仓库');
    append(root,element('p','01 / SHARED REPOSITORY','eyebrow'));panel.append(root);
    append(root,element('h2','把仓库连接到协作现场'),element('p','本地检查点发现开发中的交叠，GitHub 同步核对远端交付。','muted'));
    if(!git.binding){
      if(!git.can_manage){append(root,element('p','请项目管理者先绑定仓库。'));return;}
      const form=element('form','','git-bind-form'),input=element('input'),submit=element('button','绑定仓库','primary'),feedback=element('p','','error');
      input.required=true;input.name='repository';input.placeholder='https://github.com/owner/repository';submit.type='submit';
      append(form,append(element('label','共同仓库地址'),input),submit,feedback);
      form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{await context.api('/api/git/binding',{repository:input.value});document.activeElement?.blur();await context.sync();}catch(error){feedback.textContent=error.message;}finally{submit.disabled=false;}});root.append(form);return;
    }
    append(root,element('p',git.binding.repository,'git-repository'),element('p','项目 ID：'+snapshot.me.room_id,'meta'));
    const local=element('section','','git-block');local.setAttribute('aria-label','本地 agent 接入');
    append(local,element('p','02 / LOCAL AGENT','eyebrow'),element('h3','本地 agent 接入'),element('p','每台电脑配置一次，在任务检查点同步分支与实际变更。','muted'));panel.append(local);
    const setup=element('details');append(setup,element('summary','本地 agent 一次接入'),element('p','安装 Coopagents service 依赖；用自己的 agent 令牌启动本地 stdio MCP。令牌放在环境变量中。'),element('pre','python -m coopagents.git_adapter --repository PATH --service '+context.origin+' --project '+snapshot.me.room_id),element('p','检查点工具：repo_checkpoint(task_id)。通过 --inspect 诊断、--init-project 创建可提交的公共约定；保留现有 agent 配置。','muted'));local.append(setup);
    root=element('section','','git-block');root.setAttribute('aria-label','GitHub 交付同步');
    append(root,element('p','03 / VERIFIED DELIVERY','eyebrow'));panel.append(root);
    append(root,element('h3','GitHub 交付同步'),element('p',connected(git)?'已授权 '+git.connection.full_name+' · 最后核对 '+when(git.connection.sync_at):'尚未连接 GitHub App。','meta'));
    const status=element('p','','error');status.setAttribute('role','status');
    if(!git.github_configured){append(root,element('p','服务管理员尚未配置 GitHub App，本地 Git 检查点可独立使用。','muted'));return;}
    if(git.can_manage){
      const connect=element('button','授权仓库访问 ↗');connect.type='button';
      connect.addEventListener('click',async()=>{connect.disabled=true;try{const result=await context.api('/api/git/github/authorize',{});if(!context.isCurrent())return;const u=new URL(result.authorization_url);if(u.protocol!=='https:'||u.hostname!=='github.com'||u.username||u.password||u.port||u.pathname!=='/login/oauth/authorize')throw new Error('授权地址不可用');authorization={state:result.state,room:snapshot.me.room_id,url:u.href};root.querySelector('.git-authorization')?.remove();renderAuthorization(root,status,snapshot,context);}catch(error){status.textContent=error.message;}finally{connect.disabled=false;}});root.append(connect);
      renderAuthorization(root,status,snapshot,context);
    }
    if(connected(git)){const refresh=element('button','核对远端状态 ↻');refresh.type='button';refresh.addEventListener('click',async()=>{refresh.disabled=true;try{await context.api('/api/git/github/refresh',{});document.activeElement?.blur();await context.sync();}catch(error){status.textContent=error.message;}finally{refresh.disabled=false;}});root.append(refresh);}
    root.append(status);
    if((git.github_pending||[]).length)append(root,element('p',git.github_pending.length+' 个开放 PR 尚未关联任务；在任务详情中指定 PR 编号。','muted'));
    if(git.github_discovery?.truncated)append(root,element('p','开放 PR 列表仅展示最近 '+git.github_discovery.limit+' 条，其他 PR 可按编号明确关联。','muted'));
    if(git.github_discovery?.releases?.truncated)append(root,element('p','Release 列表仅展示最近 '+git.github_discovery.releases.limit+' 条，其他 Release 可按 ID 明确关联。','muted'));
    if((git.github_events||[]).some(e=>e.status!=='completed'))append(root,element('p','有事件等待同步或重试；最后成功记录保留。','muted'));
  }
  function renderOverlaps(root,git,taskName){
    (git?.overlaps||[]).forEach(o=>append(root,append(element('article','','record git-overlap'),element('h3',o.task_ids.map(taskName).join(' × ')),element('p','实际变更路径：'+o.paths.join('、')+(o.path_count>o.paths.length?'（共 '+o.path_count+' 条）':'')),element('p','本地 Git 观测 · '+o.captured_at.map(when).join(' / ')+' · 路径重叠需要协商','meta'))));
  }
  const api={state,safeURL,safeReleaseURL,caption,checks,summarize,renderDetails,renderPanel,renderOverlaps,clear};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.CoopagentsGit=api;
})();
