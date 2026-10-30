 'use strict';
(() => {
  const sessions=new WeakMap();
  const labels={confirmed:'成员已确认',suggested:'待确认建议',observed:'只读观测',agent_report:'agent 明确报告',shared:'共享事实'};
  const el=(tag,value='',cls)=>{const n=document.createElement(tag);n.textContent=value??'';if(cls)n.className=cls;return n;};
  const time=v=>v?new Date(v).toLocaleString('zh-CN'):'未知';
  function render(root,result,context={}){
    if(!root)return;
    if(!result){sessions.delete(root);root.replaceChildren();return;}
    let state=sessions.get(root);
    if(!state||state.room!==context.roomId){state={room:context.roomId,filters:{},data:null,request:0};sessions.set(root,state);}
    if(state.inflight)return;
    if(root.contains(document.activeElement)&&['INPUT','SELECT'].includes(document.activeElement?.tagName))return;
    root.replaceChildren();
    const section=el('section','','shared-context');section.setAttribute('aria-label','共享上下文');
    section.append(el('h2','共享上下文'),el('p','按需查询项目共享信息，保留来源、版本、范围、新鲜度和可引用标识。','muted'));
    const controls=el('form','','context-filters'),fields={},body=el('div'),feedback=el('p','','meta');
    function input(name,label,options){
      const n=el(options?'select':'input');n.name=name;
      if(options)for(const [value,title] of [['','全部'],...options]){const option=el('option',title);option.value=String(value);n.append(option);}
      n.value=state.filters[name]||'';if(!options)n.maxLength=500;
      const container=el('label',label);container.append(n);controls.append(container);fields[name]=n;
    }
    input('task_id','任务',(context.tasks||[]).map(t=>[t.id,'#'+t.id+' '+t.title]));
    input('member_id','成员',(context.members||[]).map(m=>[m.member_id,m.display_name]));
    input('scope','声明范围');input('branch','分支');input('delivery_kind','交付类型',[['branch','Branch'],['commit','Commit'],['pr','PR'],['release','Release']]);
    input('delivery_value','交付标识');input('query','搜索');
    const submit=el('button','查询');submit.type='submit';controls.append(submit);section.append(controls,feedback,body);
    const current=()=>sessions.get(root)===state&&(!context.isCurrent||context.isCurrent());
    function show(data){
      body.replaceChildren();
      for(const item of data.items||[]){
        const d=item.data||{},row=el('article','','context-item');
        row.append(el('h3',d.title||d.summary||d.filename||d.need||d.tool||d.delivery_value||item.kind),
          el('p',(labels[d.confirmation]||d.confirmation||item.source)+' · '+({fresh:'新鲜',current:'当前',stale:'已过期',unavailable:'当前不可用',unknown:'未知'}[item.freshness]||item.freshness)+' · '+time(item.observed_at),'meta'));
        if(d.body)row.append(el('p',d.body));
        if(d.evidence)row.append(el('p','依据：'+d.evidence,'meta'));
        if(d.version)row.append(el('p','版本 v'+d.version+(d.effective?' · 当前生效':''),'meta'));
        if(d.task_id&&context.openTask){const b=el('button','任务 #'+d.task_id);b.type='button';b.addEventListener('click',()=>context.openTask(d.task_id));row.append(b);}
        row.append(el('p','来源 '+item.source+' · 范围 '+item.scope+' · 引用 '+item.id,'meta'));
        body.append(row);
      }
      if(!(data.items||[]).length)body.append(el('p','当前范围没有共享记录。','muted'));
      if(data.source_truncated)body.append(el('p','部分上游来源已截断；可打开原始任务或交付对象查看完整证据。','muted'));
      if(context.query){
        for(const [label,offset] of [['上一页',data.offset>0?Math.max(0,data.offset-(data.limit||50)):null],['下一页',data.next_offset]]){
          if(offset==null)continue;
          const b=el('button',label);b.type='button';b.addEventListener('click',()=>load(offset));body.append(b);
        }
      }
    }
    async function load(offset=0){
      if(!current()||!context.query)return;
      const id=++state.request;state.inflight=true;submit.disabled=true;feedback.textContent='正在查询…';
      try{const data=await context.query({...state.filters,offset});if(!current()||id!==state.request)return;state.data=data;show(data);feedback.textContent='';}
      catch(e){if(current()&&id===state.request)feedback.textContent=e.message;}
      finally{if(id===state.request){state.inflight=false;submit.disabled=false;}}
    }
    controls.addEventListener('submit',async event=>{
      event.preventDefault();const filters={};for(const [k,n] of Object.entries(fields))if(n.value)filters[k]=k==='task_id'?Number(n.value):n.value;
      state.filters=filters;await load();
    });
    if(!context.query)controls.hidden=true;
    show(state.data||result);root.append(section);
  }
  const api={render};if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.CoopagentsSharedContext=api;
})();
