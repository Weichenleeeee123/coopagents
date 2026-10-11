/* Invitation secrets live only in this page's memory and request bodies. */
(() => {
  'use strict';
  const el=id=>document.getElementById(id);
  let token='', preview=null, hooks=null, loading=false, revision=0, failure='';
  const roles={member:'成员',admin:'管理员',owner:'所有者'};
  function capture(){
    const hash=window.location.hash;
    if(!hash.startsWith('#invite='))return false;
    // Clear even malformed fragments before a network request or any other UI work.
    window.history.replaceState(null,'',window.location.pathname+window.location.search);
    preview=null;failure='';revision++;
    el('invitation-accept').hidden=true;el('invitation-details').textContent='';el('invitation-expiry').textContent='';
    try{token=decodeURIComponent(hash.slice(8));}catch{token='';}
    if(!token || token.length>128){token='';el('invitation-panel').hidden=false;el('invitation-status').textContent='邀请链接无效，请向邀请人索取新链接。';return false;}
    return true;
  }
  function render(){
    if(!token)return;
    el('invitation-panel').hidden=false;
    el('invitation-accept').hidden=!hooks?.session || !preview;
    el('invitation-accept').disabled=loading;
    el('invitation-refresh').hidden=!hooks?.config?.github_oauth_enabled || !!hooks?.session;
    if(preview){
      el('invitation-details').textContent=preview.team_name+' · 邀请角色：'+roles[preview.role]+' · 项目：'+(preview.projects.map(p=>p.name).join('、') || '仅加入团队，项目访问另行授权');
      el('invitation-expiry').textContent='有效期至 '+new Date(preview.expires_at).toLocaleString()+' · 24 小时单次邀请';
    }
    if(failure){el('invitation-status').textContent=failure;el('invitation-accept').hidden=true;}
    else if(hooks?.session){
      el('invitation-status').textContent='以 '+hooks.session.account.display_name+' 接受邀请。已有团队成员保留当前角色，并获得指定项目访问。';
    }else if(hooks?.config?.github_oauth_enabled){
      el('invitation-status').textContent='GitHub 登录在新标签页完成。登录后回到此页，点击“我已完成登录”。请保留此页；刷新或关闭后需重新打开原邀请链接。';
    }else el('invitation-status').textContent='请登录后明确接受邀请，或在下面创建账号并接受。刷新或关闭页面后，请重新打开原邀请链接。';
    const input=el('register-form').querySelector('[name=invite_token]');
    if(input)input.value=token;
    if(hooks?.config?.local_login_enabled)el('account-register').open=true;
    if(hooks?.config?.github_oauth_enabled){el('github-login').target='_blank';el('github-login').rel='noopener';}
  }
  async function load(){
    if(!token || !hooks || loading || preview)return;
    const mine=revision;let retry=false;loading=true;render();
    try{
      const result=await hooks.request('/account/invites/preview',{invite_token:token});
      if(mine!==revision)return;preview=result;render();
    }catch(error){if(error.message==='访问已切换')retry=true;else if(mine===revision){failure=error.message;render();}}
    finally{loading=false;el('invitation-accept').disabled=false;if(retry || mine!==revision)load();}
  }
  function clear(){token='';preview=null;revision++;el('invitation-panel').hidden=true;const input=el('register-form').querySelector('[name=invite_token]');if(input)input.value='';el('github-login').target='';}
  el('invitation-accept').addEventListener('click',async()=>{
    if(loading || !token || !preview || !hooks?.session)return;
    const mine=revision;loading=true;el('invitation-accept').disabled=true;
    try{await hooks.accept(token);if(mine===revision)clear();}
    catch(error){el('invitation-status').textContent=error.message;}
    finally{loading=false;el('invitation-accept').disabled=false;}
  });
  el('invitation-refresh').addEventListener('click',async()=>{
    try{await hooks?.refresh();}catch(error){el('invitation-status').textContent=error.message;}
  });
  el('invitation-dismiss').addEventListener('click',clear);
  window.addEventListener('hashchange',()=>{if(capture()){render();load();}});
  capture();
  window.CrewmeshInvitations={
    update(next){hooks=next;render();return load();}, clear, pending:()=>!!token,
    registration(data){return token?{...data,invite_token:token}:data;},
    link(invite){return window.location.origin+'/#invite='+encodeURIComponent(invite.invite_token);}
  };
})();
