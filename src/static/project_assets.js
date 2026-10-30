'use strict';
(() => {
  const el=(tag,text,cls)=>{const node=document.createElement(tag);node.textContent=text??'';if(cls)node.className=cls;return node;};
  let state=null;
  function renderList(){
    if(!state)return;
    state.list.replaceChildren();
    if(state.error)state.status.textContent=state.error;
    else if(state.uploading)state.status.textContent='正在分享文件…';
    else if(state.loading)state.status.textContent='正在读取项目资产…';
    else state.status.textContent=state.assets.length+' 个共享资产';
    if(!state.assets.length&&!state.loading&&!state.error)state.list.append(el('p','尚未显式分享项目文件。','muted'));
    state.assets.forEach(asset=>{
      const row=el('article','','asset-row');
      const title=el('h3',String(asset.filename||'文件').slice(0,255));
      const metadata=el('p',`${asset.media_type} · ${asset.size_bytes} bytes · SHA-256 ${asset.sha256}`,'meta');
      const sourceType={upload:'成员上传',path:'仓库路径',commit:'Commit',pull_request:'PR',release:'Release'}[asset.source_type]||'显式引用';
      const source=asset.source_type==='upload'?sourceType:`${sourceType} · ${asset.source_ref}`;
      const details=el('p',`${source} · 分享者 ${asset.uploader_member_id} · ${asset.created_at}`,'meta');
      const download=el('button','下载');download.type='button';download.title='下载共享资产';
      download.addEventListener('click',async()=>{
        const current=state,context=current?.context;
        if(!context||current.uploading)return;
        download.disabled=true;
        try{
          const blob=await context.api('/api/assets/'+encodeURIComponent(asset.id),undefined,true,{},'blob');
          if(state!==current||!context.isCurrent())return;
          const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=asset.filename;link.click();URL.revokeObjectURL(link.href);
        }catch(error){if(state===current&&context.isCurrent()){current.error=error.message;renderList();}}
        finally{download.disabled=false;}
      });
      row.append(title,metadata,details,download);state.list.append(row);
    });
  }
  async function load(current){
    current.loading=true;current.error='';renderList();
    try{
      const result=await current.context.api('/api/assets');
      if(state!==current||!current.context.isCurrent())return;
      if(!result||!Array.isArray(result.assets))throw new Error('资产清单格式无效');
      current.assets=result.assets;current.error='';
    }catch(error){if(state===current&&current.context.isCurrent())current.error=error.message;}
    finally{if(state===current){current.loading=false;renderList();}}
  }
  function mount(root,context){
    root.replaceChildren();
    const section=el('section','','project-assets');section.setAttribute('aria-label','共享项目资产');
    const heading=el('div','','section-heading');heading.append(el('h2','共享项目资产'),el('span','成员明确分享的文件'));
    const controls=el('div','','asset-controls'),label=el('label','选择文件');
    const input=document.createElement('input');input.type='file';input.accept='.txt,.md,.json,.pdf,.png,.jpg,.jpeg,.webp,.bin';input.setAttribute('aria-label','选择需要分享的文件');label.append(input);
    const sourceLabel=el('label','资产来源');const sourceType=document.createElement('select');sourceType.setAttribute('aria-label','资产来源类型');
    for(const [value,title] of [['upload','普通上传'],['path','仓库相对路径'],['commit','Commit'],['pull_request','Pull request'],['release','Release']]){
      const option=el('option',title);option.value=value;sourceType.append(option);
    }
    const sourceRef=document.createElement('input');sourceRef.type='text';sourceRef.maxLength=500;sourceRef.placeholder='例如 docs/guide.md 或对象编号';sourceRef.setAttribute('aria-label','资产来源引用');sourceRef.hidden=true;sourceLabel.append(sourceType,sourceRef);
    const upload=el('button','分享文件');upload.type='button';upload.disabled=true;
    const refresh=el('button','刷新清单');refresh.type='button';
    const status=el('p','','asset-status');status.setAttribute('role','status');
    const list=el('div','','asset-list');
    sourceType.addEventListener('change',()=>{sourceRef.hidden=sourceType.value==='upload';sourceRef.required=sourceType.value!=='upload';});
    input.addEventListener('change',()=>{upload.disabled=!(input.files&&input.files.length);if(state)state.status.textContent=upload.disabled?'请选择文件':'已选择 '+input.files[0].name;});
    upload.addEventListener('click',async()=>{
      const current=state,file=input.files?.[0];
      if(!current||!file||current.uploading)return;
      current.uploading=true;current.error='';upload.disabled=true;renderList();
      try{
        const data=new FormData();data.append('file',file,file.name);data.append('source_type',sourceType.value);data.append('source_ref',sourceRef.value.trim());
        await current.context.api('/api/assets',data,true);
        if(state!==current||!current.context.isCurrent())return;
        input.value='';current.uploading=false;await load(current);
      }catch(error){
        if(state===current&&current.context.isCurrent()){current.uploading=false;current.error=error.message;upload.disabled=!(input.files&&input.files.length);renderList();}
      }
    });
    controls.append(label,sourceLabel,upload,refresh);section.append(heading,controls,status,list);root.append(section);
    state={roomId:context.roomId,context,assets:[],loading:false,uploading:false,error:'',root,list,status,input,upload,refresh,sourceType,sourceRef};
    refresh.addEventListener('click',()=>{if(state&&!state.loading&&!state.uploading)load(state);});
    load(state);
  }
  function render(root,context){
    if(!root||!context||typeof context.roomId!=='string')return;
    if(!state||state.root!==root||state.roomId!==context.roomId){state=null;mount(root,context);return;}
    state.context=context;
  }
  function clear(root){if(state&&(root===undefined||state.root===root)){state=null;if(root)root.replaceChildren();}}
  const api={render,clear};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.CoopagentsProjectAssets=api;
})();
