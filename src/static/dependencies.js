'use strict';
(() => {
  const states=new Map();
  const node=(tag,value='',cls)=>{const n=document.createElement(tag);n.textContent=value;if(cls)n.className=cls;return n;};
  const add=(parent,...children)=>{children.forEach(child=>parent.append(child));return parent;};
  const routeLabels={routed:'已找到负责人',waiting_source:'等待发起任务认领',unassigned:'被依赖任务待分派',target_cancelled:'被依赖任务已取消，仍需处理'};
  const statusLabels={active:'等待满足',satisfied:'已确认满足',cancelled:'已撤销'};
  const active=snapshot=>(snapshot.dependencies||[]).filter(d=>d.status==='active');
  const blocked=(task,snapshot)=>!task.cancelled_at&&active(snapshot).some(d=>d.source_task_id===task.id);
  function clear(){states.clear();}
  function local(key){let s=states.get(key);if(!s){s={need:'',context:'',scope:'',target:'',summary:'',body:'',evidence:'',loading:false,status:'',open:false};states.set(key,s);}return s;}
  function requestKey(state,operation,body){const signature=JSON.stringify([operation,body]);if(state.request?.signature!==signature)state.request={signature,key:crypto.randomUUID()};return state.request.key;}
  function input(tag,label,value,save,max=4000){const n=node(tag);n.value=value;n.maxLength=max;if(tag==='textarea')n.rows=3;n.addEventListener('input',()=>save(n.value));return {control:n,label:add(node('label',label),n)};}
  function button(label,fn){const b=node('button',label);b.type='button';b.addEventListener('click',fn);return b;}
  function renderDetails(container,task,snapshot,context){
    const me=snapshot.me,key=JSON.stringify([me.room_id,me.member_id,task.id]),state=local(key);
    state.capture?.();
    const current=()=>context.isCurrent()&&states.get(key)===state;
    const section=node('section','','dependency-section');
    add(section,node('p','任务依赖','detail-label'),node('p','回复后，由等待方查看并确认满足。任务合并和消息回执不会自动解除依赖。','muted'));
    for(const [field,title] of [['source_task_id','我在等谁'],['target_task_id','谁在等我']]){
      add(section,node('h3',title));
      const records=(snapshot.dependencies||[]).filter(d=>d[field]===task.id);
      if(!records.length)add(section,node('p','暂无依赖。','muted'));
      records.forEach(dep=>renderDependency(section,dep,snapshot,context,key));
    }
    const allowed=task.owner_member_id===me.member_id||snapshot.lifecycle?.can_manage||(!task.owner_member_id&&task.creator_member_id===me.member_id);
    if(allowed&&!task.cancelled_at){
      const form=node('details'),content=node('div');form.open=state.open;
      add(form,node('summary','添加依赖 · 查找任务负责人'),content);state.capture=()=>{state.open=form.open;};
      const scope=input('input','按声明范围查找任务',state.scope,v=>state.scope=v,500);
      const target=node('select');target.setAttribute('aria-label','明确选择被依赖任务');
      function targets(){
        target.replaceChildren();const empty=node('option','请选择被依赖任务');empty.value='';target.append(empty);
        (state.candidates||snapshot.tasks.filter(t=>t.id!==task.id&&!t.cancelled_at)).forEach(t=>{const option=node('option','#'+t.id+' '+t.title+' · '+(t.owner_member_id?context.memberName(t.owner_member_id):'待分派'));option.value=String(t.id);target.append(option);});
        target.value=state.target;
      }
      targets();target.addEventListener('change',()=>state.target=target.value);
      const notice=node('p',state.status,'meta');
      const lookup=button('查找负责人',async()=>{
        if(!current()||state.loading)return;
        state.loading=true;state.status='正在查找…';state.render();
        try{
          const result=await context.api('/api/owners/lookup',{scope:scope.control.value});
          if(!current())return;
          state.candidates=result.candidates.filter(t=>t.id!==task.id);state.target='';
          state.status=result.status==='ambiguous'?'多个任务范围匹配，请根据声明证据明确选择。':result.status==='not_found'?'没有匹配的声明范围。':result.status==='unassigned'?'找到任务，当前无人负责。':'找到任务及当前负责人。';
          state.lookupEvidence=result.candidates.map(t=>'#'+t.id+' '+t.scope+' · '+({'Exact task id':'任务编号一致','Equal declared scope':'声明范围相同','Slash-segment prefix overlap':'声明范围按路径段包含匹配'}[t.evidence]||t.evidence)).join('\n');
        }catch(error){if(current())state.status=error.message;}
        finally{if(current()){state.loading=false;state.render();}}
      });
      const need=input('input','需要对方提供什么',state.need,v=>state.need=v,500);
      const detail=input('textarea','请求上下文（可选）',state.context,v=>state.context=v,3000);
      const evidence=node('p',state.lookupEvidence||'','meta');
      const create=button('建立任务依赖',async()=>{
        if(!current()||state.loading)return;
        if(!state.target||!state.need.trim()){state.status='请选择目标任务，并填写需要什么。';state.render();return;}
        const body={source_task_id:task.id,target_task_id:Number(state.target),need:state.need.trim(),context:state.context.trim(),expected_revision:task.revision};
        body.request_key=requestKey(state,'create',body);state.loading=true;state.status='正在建立依赖…';state.render();
        try{await context.api('/api/dependencies',body);if(!current())return;
          state.need='';state.context='';state.target='';state.status='依赖已建立。';state.request=null;
          document.activeElement?.blur?.();await context.sync();
        }catch(error){if(current())state.status=error.message;}
        finally{if(current()){state.loading=false;state.render();}}
      });
      state.render=()=>{targets();notice.textContent=state.status;evidence.textContent=state.lookupEvidence||'';lookup.disabled=create.disabled=target.disabled=scope.control.disabled=need.control.disabled=detail.control.disabled=state.loading;need.control.value=state.need;detail.control.value=state.context;};
      add(content,scope.label,lookup,evidence,add(node('label','被依赖任务'),target),need.label,detail.label,create,notice);add(section,form);
    }
    container.append(section);
  }
  function renderDependency(container,dep,snapshot,context,taskKey){
    const key=taskKey+':dependency:'+dep.id,state=local(key),current=()=>context.isCurrent()&&states.get(key)===state;
    const me=snapshot.me.member_id,source=dep.source.owner_member_id===me,target=dep.target.owner_member_id===me;
    const manageable=source||snapshot.lifecycle?.can_manage||(!dep.source.owner_member_id&&dep.source.creator_member_id===me);
    const row=node('article','','dependency-record'),status=node('p',state.status,'meta'),controls=[];
    add(row,node('h4','#'+dep.id+' · '+dep.need),node('p',dep.source.title+' → '+dep.target.title,'detail-value'),node('p',statusLabels[dep.status]+' · '+routeLabels[dep.routing_state]+' · '+(dep.target.owner_member_id?context.memberName(dep.target.owner_member_id):'待分派'),'meta'));
    if(dep.context)add(row,node('p',dep.context,'detail-value'));
    if(dep.latest_reply)add(row,node('p',(dep.latest_reply.actor_kind==='web'?'网页成员回复：':'agent 回复：')+dep.latest_reply.body,'dependency-reply'),node('p','证据：'+(dep.latest_reply.evidence||'未提供'),'meta'));
    state.capture?.();
    const detail=node('details'),history=node('div');detail.open=state.historyOpen||false;
    add(detail,node('summary','依赖路由与处理记录'),history);state.capture=()=>{state.historyOpen=detail.open;};
    function renderHistory(){history.replaceChildren();(state.read?.history||[]).forEach(event=>add(history,node('p',event.action+' · '+event.summary+' · '+event.created_at,'meta')));}
    function action(label,operation,bodyFor){
      const b=button(label,async()=>{
        if(!current()||state.loading)return;
        const extra=bodyFor();if(extra===null){state.render();return;}
        const body=operation==='read'?{}:{expected_revision:dep.revision,...extra};
        if(operation!=='read')body.request_key=requestKey(state,operation,body);
        state.loading=true;state.status='正在处理…';state.render();
        try{
          const result=await context.api('/api/dependencies/'+dep.id+'/'+operation,body);
          if(!current())return;
          if(operation==='read'){state.read=result;state.status=result.read_recorded?'已查看最新回复，可以确认满足。':'已查看记录；当前没有可由你确认的最新回复。';if(result.revision!==dep.revision)await context.sync();}
          else{state.read=null;state.request=null;state.status='已保存。';document.activeElement?.blur?.();await context.sync();}
        }catch(error){if(current())state.status=error.message+'；草稿已保留，请刷新当前版本。';}
        finally{if(current()){state.loading=false;state.render();}}
      });b.dataset.lifecycleFocus=key+':'+operation;controls.push(b);return b;
    }
    const read=action(dep.latest_reply?'查看最新回复与记录':'查看依赖记录','read',()=>({}));add(row,read);
    if(dep.status==='active'&&target&&dep.routing_state==='routed'){
      const body=input('textarea','答复等待方',state.body,v=>state.body=v);
      const evidence=input('input','答复证据（可选）',state.evidence,v=>state.evidence=v,1000);
      const reply=action('发送答复','reply',()=>{if(!state.body.trim()){state.status='请填写答复。';return null;}return {body:state.body.trim(),evidence:state.evidence.trim()};});
      add(row,body.label,evidence.label,reply);
    }
    let confirm;
    if(dep.status==='active'&&manageable){
      const summary=input('textarea','确认说明 / 撤销原因',state.summary,v=>state.summary=v);
      const reason=()=>{if(!state.summary.trim()){state.status='请填写确认说明或撤销原因。';return null;}return {summary:state.summary.trim()};};
      add(row,summary.label);
      if(source){confirm=action('确认依赖已满足','resolve',()=>{const r=reason();return r?{...r,reply_id:state.read?.latest_reply?.id}:null;});add(row,confirm);}
      add(row,action('撤销依赖','cancel',reason));
    }
    if(dep.closed_reason)add(row,node('p','关闭说明：'+dep.closed_reason,'meta'));
    state.render=()=>{
      status.textContent=state.status;controls.forEach(b=>b.disabled=state.loading);
      if(confirm)confirm.disabled=state.loading||!state.read?.read_recorded||state.read.revision!==dep.revision||state.read.latest_reply?.id!==dep.latest_reply?.id;
      renderHistory();
    };
    state.render();add(row,detail,status);container.append(row);
  }
  function pending(snapshot){
    const me=snapshot.me.member_id,items=[];
    for(const dep of active(snapshot)){
      if(dep.routing_state!=='routed'){
        if(snapshot.lifecycle?.can_manage||dep.source.owner_member_id===me||dep.creator_member_id===me)items.push({kind:'dependency',task_id:dep.source_task_id,label:routeLabels[dep.routing_state]+'：'+dep.need});
      }else if(dep.latest_reply&&dep.source.owner_member_id===me)items.push({kind:'dependency',task_id:dep.source_task_id,label:'查看并确认答复：'+dep.need});
      else if(!dep.latest_reply&&dep.target.owner_member_id===me)items.push({kind:'dependency',task_id:dep.target_task_id,label:'有人在等你的答复：'+dep.need});
    }
    for(const r of snapshot.requests||[])if(!r.dependency_id&&!r.resolved_at&&(r.receiver_member_id===me||r.sender_member_id===me||(!r.receiver_member_id&&snapshot.lifecycle?.can_manage)))items.push({kind:'request',id:r.id,label:'技术请求 #'+r.id+'：'+r.body});
    for(const h of snapshot.lifecycle?.handoffs||[])if(h.target_member_id===me)items.push({kind:'handoff',task_id:h.task_id,label:'待你接手任务 #'+h.task_id+'：'+h.summary});
    for(const c of snapshot.contracts||[]){const latest=c.versions.find(v=>v.version===c.current_version);if(latest&&!latest.decision)items.push({kind:'contract',id:c.id,label:'公共约定待审核：'+latest.title});}
    return items;
  }
  function renderOverview(container,snapshot,context){
    container.replaceChildren();add(container,node('h2','需要我处理'));
    const items=pending(snapshot);if(!items.length)add(container,node('p','当前没有待你处理的协作事项。','muted'));
    items.forEach(item=>add(container,button(item.label,()=>context.openItem(item))));
  }
  const exported={clear,blocked,pending,renderDetails,renderOverview};
  if(typeof module!=='undefined')module.exports=exported;
  if(typeof window!=='undefined')window.CrewmeshDependencies=exported;
})();
