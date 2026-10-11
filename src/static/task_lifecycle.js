'use strict';
(() => {
  const drafts=new Map();
  const labels={claim_task:'认领任务',release_task:'释放任务',propose_handoff:'提出转交',accept_handoff:'接受交接',reject_handoff:'拒绝交接',force_handoff:'负责人强制转交',cancel_task:'取消任务',reopen_task:'重新打开'};
  const element=(tag,value='',cls)=>{const node=document.createElement(tag);node.textContent=value;if(cls)node.className=cls;return node;};
  const append=(parent,...children)=>{children.forEach(child=>parent.append(child));return parent;};
  const matches=(task,filter)=>filter==='all'||(filter==='cancelled'?Boolean(task.cancelled_at||task.state==='cancelled'):!task.cancelled_at&&task.state!=='cancelled');
  function clear(){drafts.clear();}
  function renderHistory(root,records,task,context){
    records.forEach(record=>{
      const entry=element('details'),body=element('div');
      append(entry,element('summary',(labels[record.action]||record.action)+' · '+context.memberName(record.actor_member_id)+' · '+new Date(record.created_at).toLocaleString()),body);
      append(body,element('p',record.summary,'detail-value'),element('p','责任周期 '+record.ownership_epoch+' · '+context.memberName(record.from_owner_member_id)+' → '+(record.to_owner_member_id?context.memberName(record.to_owner_member_id):'待认领'),'meta'));
      const archived=record.context||{};
      if(archived.progress)append(body,element('p','当时进展：'+archived.progress.summary,'detail-value'));
      (archived.sessions||[]).forEach(session=>append(body,element('p','当时会话 '+session.session_key+' · '+session.branch,'meta')));
      (archived.deliveries||[]).forEach(delivery=>append(body,element('p','历史交付 · '+(delivery.pr_number?'PR #'+delivery.pr_number:delivery.branch||delivery.commit_sha)+' · '+delivery.state,'meta')));
      const full=element('button','查看完整交接证据');full.type='button';
      full.addEventListener('click',async()=>{
        full.disabled=true;
        try{
          const event=await context.api('/api/tasks/'+task.id+'/history/'+record.id);
          if(!context.isCurrent())return;
          append(body,element('pre',JSON.stringify(event.context,null,2),'lifecycle-evidence'));
          full.hidden=true;
        }catch(error){if(context.isCurrent())append(body,element('p',error.message,'error'));}
        finally{if(context.isCurrent())full.disabled=false;}
      });
      append(body,full);append(root,entry);
    });
  }
  function renderDetails(container,task,snapshot,context){
    const me=snapshot.me,life=snapshot.lifecycle||{},key=me.room_id+':'+task.id;
    let draft=drafts.get(key);if(!draft){draft={summary:'',target:'',request:null};drafts.set(key,draft);}
    const owner=task.owner_member_id===me.member_id,manager=life.can_manage===true;
    const canEdit=owner||manager||(!task.owner_member_id&&[task.creator_member_id,task.last_owner_member_id].includes(me.member_id));
    const pending=(life.handoffs||[]).find(h=>h.task_id===task.id&&h.status==='pending');
    const recipient=pending?.target_member_id===me.member_id,cancelled=task.cancelled_at||task.state==='cancelled';
    const section=element('section','','task-lifecycle');
    append(section,element('p','任务交接与恢复','detail-label'),element('p','当前责任人：'+(cancelled?'已取消，恢复后可认领':task.owner_member_id?context.memberName(task.owner_member_id):'待认领')+' · 执行会话：'+(task.execution_session_key||'尚未绑定')+' · 责任周期 '+task.ownership_epoch,'meta'));
    if(task.owner_member_id&&!task.execution_session_key&&(task.ownership_epoch>1||task.last_owner_member_id))append(section,element('p','请让接手 agent 使用新的 session_key 调用 claim_task，然后在上报时携带返回的 ownership_epoch。','muted'));
    if(life.handoffs_truncated&&!pending){
      const query=element('button','查询此任务的当前交接');query.type='button';
      append(section,element('p','项目待交接较多，当前列表只显示部分。','muted'),query);
      query.addEventListener('click',async()=>{
        query.disabled=true;
        try{
          const scoped=await context.api('/api/tasks/'+task.id+'/history',{limit:1});
          if(!context.isCurrent())return;
          section.replaceChildren();
          renderDetails(section,scoped.task,{...snapshot,lifecycle:{...life,handoffs_truncated:false,
            handoffs:[...(life.handoffs||[]),...(scoped.handoff?[scoped.handoff]:[])]}},context);
        }catch(error){if(context.isCurrent())append(section,element('p',error.message,'error'));}
        finally{if(context.isCurrent())query.disabled=false;}
      });
    }
    if(pending)append(section,element('p','待 '+context.memberName(pending.target_member_id)+' 明确接手：'+pending.summary,'notice'));
    if(canEdit||recipient){
      const summary=element('textarea'),target=element('select'),status=element('p','','meta'),actions=element('div','','lifecycle-actions');
      summary.rows=3;summary.maxLength=4000;summary.required=true;summary.value=draft.summary;summary.placeholder='交接摘要：分支、已完成内容、剩余问题和下一步';
      summary.addEventListener('input',()=>{draft.summary=summary.value;});
      const empty=element('option','选择接手成员');empty.value='';target.append(empty);
      (snapshot.members||[]).filter(member=>member.member_id!==task.owner_member_id).forEach(member=>{const option=element('option',member.display_name);option.value=member.member_id;target.append(option);});
      target.value=draft.target;target.addEventListener('change',()=>{draft.target=target.value;});
      append(section,append(element('label','操作 / 交接摘要（必填）'),summary));
      if(canEdit&&!cancelled&&task.owner_member_id)append(section,append(element('label','目标成员'),target));
      const buttons=[];
      function action(name){
        const button=element('button',labels[name]);button.type='button';buttons.push(button);
        button.addEventListener('click',async()=>{
          if(!context.isCurrent())return;
          if(!summary.value.trim()){status.textContent='请先填写交接摘要。';return;}
          const body={expected_revision:task.revision,summary:summary.value.trim()};
          if(['propose_handoff','force_handoff'].includes(name)){
            if(!target.value){status.textContent='请选择接手成员。';return;}body.target_member_id=target.value;
          }
          const signature=JSON.stringify([name,body]);
          if(draft.request?.signature!==signature)draft.request={signature,key:crypto.randomUUID()};
          body.request_key=draft.request.key;
          buttons.forEach(b=>b.disabled=true);status.textContent='正在保存…';
          try{
            await context.api('/api/tasks/'+task.id+'/'+name.replaceAll('_','-'),body);
            if(!context.isCurrent())return;
            drafts.delete(key);document.activeElement?.blur?.();await context.sync();
            if(context.isCurrent())status.textContent='已保存。';
          }catch(error){if(context.isCurrent())status.textContent=error.message+'；刷新查看当前版本后可重试，摘要会保留。';}
          finally{if(context.isCurrent())buttons.forEach(b=>b.disabled=false);}
        });
        actions.append(button);
      }
      if(cancelled){if(canEdit)action('reopen_task');}
      else{
        if(canEdit&&task.owner_member_id){action('release_task');if(!pending)action('propose_handoff');}
        if(recipient){action('accept_handoff');action('reject_handoff');}
        if(manager&&task.owner_member_id)action('force_handoff');
        if(canEdit)action('cancel_task');
      }
      append(section,actions,status);
    }
    const history=element('details'),historyBody=element('div');
    append(history,element('summary','交接与恢复记录'),historyBody);
    const records=(life.history||[]).filter(record=>record.task_id===task.id);
    renderHistory(historyBody,records,task,context);
    if(!records.length)append(historyBody,element('p','尚无交接记录。','muted'));
    const load=element('button','查看此任务的更多记录');load.type='button';
    let before=null;
    load.addEventListener('click',async()=>{
      load.disabled=true;
      try{
        const result=await context.api('/api/tasks/'+task.id+'/history',{before_id:before,limit:20});
        if(!context.isCurrent())return;
        if(before===null)historyBody.replaceChildren();
        renderHistory(historyBody,result.events,task,context);before=result.next_before_id;
        load.hidden=!before;
      }catch(error){if(context.isCurrent())append(historyBody,element('p',error.message,'error'));}
      finally{if(context.isCurrent())load.disabled=false;}
    });
    append(history,load);append(section,history);container.append(section);
  }
  const exported={renderDetails,matches,clear};
  if(typeof module!=='undefined')module.exports=exported;
  if(typeof window!=='undefined')window.CrewmeshTaskLifecycle=exported;
})();
