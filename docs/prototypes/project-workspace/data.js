'use strict';
(() => {
  const views={overview:'概览',tasks:'任务',collaboration:'协作',context:'共享上下文',delivery:'交付',members:'成员与 agent',settings:'项目设置',projects:'全部项目',team:'团队管理',account:'个人账号'};
  const tabs={overview:['summary','activity'],tasks:['board','list'],collaboration:['open','all'],context:['agreements','files','records'],delivery:['all','pr','branch','commit','release'],members:['people'],settings:['repository','connection','diagnostics'],projects:['list'],team:['members','plan'],account:['profile']};
  const members=[
    {id:'m1',name:'陈予安',initial:'陈',role:'项目创建者',color:'green',agents:[{id:'a1',name:'Codex',tool:'Codex Desktop',platform:'Windows',version:'0.9-demo',branch:'feat/shared-context',taskIds:['t1','t5'],registered:'14:32',presence:'最近出现 · 14:30',connection:'连接已建立',delivery:'事件已送达 · 14:30',processing:'处理未知',capabilities:[['MCP','已验证支持'],['项目上下文','已验证支持'],['空闲唤醒','未验证']]}]},
    {id:'m2',name:'林可',initial:'林',role:'项目成员',color:'blue',agents:[{id:'a2',name:'Claude Code',tool:'Claude Code',platform:'macOS',version:'2.0-demo',branch:'feat/delivery-evidence',taskIds:['t2','t3'],registered:'14:28',presence:'最近出现 · 14:27',connection:'连接已建立',delivery:'事件已送达 · 14:27',processing:'明确处理 · 14:27',capabilities:[['MCP','已验证支持'],['项目上下文','已验证支持'],['空闲唤醒','未验证']]},{id:'a3',name:'Cursor',tool:'Cursor',platform:'Linux',version:'1.0-demo',branch:'review/connection',taskIds:['t6'],registered:'昨天 18:20',presence:'出现记录已过期',connection:'连接未知',delivery:'送达未知',processing:'处理未知',capabilities:[['MCP','证据已过期'],['项目上下文','未验证'],['空闲唤醒','不支持']]}]},
    {id:'m3',name:'周宁',initial:'周',role:'项目成员',color:'amber',agents:[{id:'a4',name:'OpenCode',tool:'OpenCode',platform:'Linux',version:'1.0-demo',branch:'docs/onboarding',taskIds:['t4'],registered:'13:54',presence:'最近出现 · 13:51',connection:'连接未知',delivery:'送达未知',processing:'处理未知',capabilities:[['MCP','未验证'],['项目上下文','未验证'],['空闲唤醒','未验证']]}]}
  ];
  const tasks=[
    {id:'t1',key:'CP-024',title:'共享上下文的来源与版本',state:'working',owner:'m1',scope:'src/context.py',summary:'按任务和成员查询已完成，正在验证引用与新鲜度。',time:'14:32',branch:'feat/shared-context',evidence:'本地回归 18 项通过；由 agent 明确报告。'},
    {id:'t2',key:'CP-023',title:'交付证据与任务反查',state:'review',owner:'m2',scope:'src/delivery.py',summary:'PR 已打开，等待核对多任务关联。',time:'14:28',branch:'feat/delivery-evidence',evidence:'PR #42 已打开；远端状态与任务验收分别记录。'},
    {id:'t3',key:'CP-022',title:'区分连接与模型处理状态',state:'blocked',owner:'m2',scope:'src/collaboration.py',summary:'等待明确消费回执字段的定义。',time:'14:15',branch:'feat/delivery-evidence',evidence:'关联请求 R-12 已回复，尚未确认解决。'},
    {id:'t4',key:'CP-021',title:'完善新成员接入文档',state:'working',owner:'m3',scope:'docs/onboarding',summary:'正在补充不同电脑的接入与故障排查示例。',time:'13:54',branch:'docs/onboarding',evidence:'共享了接入检查清单。'},
    {id:'t5',key:'CP-020',title:'成员与 agent 能力展示',state:'working',owner:'m1',scope:'src/capabilities.py',summary:'能力来源与版本范围保持独立展示。',time:'13:40',branch:'feat/shared-context',evidence:'平台验证证据仍需单独验收。'},
    {id:'t6',key:'CP-019',title:'连接诊断的过期状态',state:'open',owner:'m2',scope:'src/connection.py',summary:'已声明范围，尚未认领。',time:'昨天',branch:'review/connection',evidence:'只有历史登记，不代表当前连接可用。'},
    {id:'t7',key:'CP-018',title:'项目文件的访问权限',state:'merged',owner:'m3',scope:'src/assets.py',summary:'权限回归通过，PR 已合并。',time:'昨天',branch:'fix/asset-access',evidence:'已合并，不自动代表团队验收。'},
    {id:'t8',key:'CP-017',title:'整理公开演示场景',state:'open',owner:'',scope:'docs/demo',summary:'准备跨电脑、跨工具的真实演示。',time:'昨天',branch:'',evidence:'尚无交付证据。'}
  ];
  const requests=[
    {id:'r1',key:'R-12',title:'模型处理回执应该如何命名？',from:'m2',to:'m1',taskId:'t1',relatedTask:'t3',state:'replied',time:'14:26',body:'连接在线与事件送达不能代表模型已经处理。是否使用 processed_at 单独记录明确处理？',reply:'同意。processed_at 只在明确确认处理后记录，连接和送达分别保留。',contractId:'c1'},
    {id:'r2',key:'R-11',title:'接入检查清单是否包含凭据过期？',from:'m3',to:'m2',taskId:'t4',state:'waiting',time:'13:50',body:'需要明确区分凭据过期、网络不可达和 MCP 配置问题。请确认诊断字段。',reply:'',contractId:''},
    {id:'r3',key:'R-10',title:'共享文件下载的权限范围',from:'m1',to:'m3',taskId:'t7',state:'resolved',time:'昨天',body:'项目资产是否只允许当前项目成员下载？',reply:'是，下载使用项目权限校验，不公开文件地址。',contractId:'c2'}
  ];
  const contracts=[
    {id:'c1',title:'连接与模型处理的状态定义',key:'collaboration.receipts',effective:2,latest:3,state:'pending',owner:'m1',time:'14:20',sourceRequest:'r1',body:'登记、连接、事件送达和模型处理分别记录。只有明确处理确认才能写入 processed_at。',proposal:'v3 建议增加 processed_by_session，保持历史处理记录不变。'},
    {id:'c2',title:'项目文件的访问边界',key:'assets.access',effective:1,latest:1,state:'approved',owner:'m3',time:'昨天',sourceRequest:'r3',body:'成员显式分享的文件只对当前项目授权成员可见。下载需重新验证项目凭据。',proposal:''},
    {id:'c3',title:'交付关联的来源标记',key:'delivery.sources',effective:1,latest:1,state:'approved',owner:'m2',time:'昨天',sourceRequest:'',body:'明确关联、agent 建议和只读观测分别记录。PR 合并和 Release 发布不自动完成任务验收。',proposal:''}
  ];
  const files=[{id:'f1',name:'新成员接入检查清单.md',kind:'Markdown',size:'3.2 KB',owner:'m3',time:'13:54',source:'成员明确上传',taskId:'t4',body:'# 新成员接入检查清单\n\n- 确认项目和个人凭据\n- 检查网络与 MCP 连接\n- 独立确认 Harness 能力\n'}, {id:'f2',name:'交付关联说明.md',kind:'Markdown',size:'2.1 KB',owner:'m2',time:'昨天',source:'成员明确上传',taskId:'t2',body:'# 交付关联\n\n分支、Commit、PR 和 Release 可以关联多个任务。\n'}];
  const deliveries=[
    {id:'d1',kind:'pr',label:'PR #42',title:'共享上下文与交付关联',state:'review',stateText:'打开 · 待审阅',taskIds:['t1','t2'],owner:'m2',time:'14:28',source:'GitHub 只读状态 · 演示数据',branch:'feat/delivery-evidence',detail:'明确关联；远端同步时间 14:28。合并与任务验收分别记录。'},
    {id:'d2',kind:'branch',label:'feat/shared-context',title:'共享上下文开发分支',state:'working',stateText:'明确关联',taskIds:['t1','t5'],owner:'m1',time:'14:32',source:'成员明确关联',branch:'feat/shared-context',detail:'分支与两个任务关联，不表示代码已经提交或推送。'},
    {id:'d3',kind:'commit',label:'a41f92c',title:'校验资产访问权限',state:'merged',stateText:'只读观测',taskIds:['t7'],owner:'m3',time:'昨天',source:'本地 Git 观测 · 已过期',branch:'fix/asset-access',detail:'该 Commit 为合成展示对象；历史观测不可替代当前工作区状态。'},
    {id:'d4',kind:'release',label:'v0.9.0',title:'项目协作能力更新',state:'merged',stateText:'已发布',taskIds:['t7'],owner:'m1',time:'昨天',source:'GitHub 只读状态 · 演示数据',branch:'main',detail:'发布不自动确认相关任务已经验收。'},
    {id:'d5',kind:'branch',label:'review/connection',title:'连接诊断候选分支',state:'pending',stateText:'待确认建议',taskIds:['t6'],owner:'m2',time:'昨天',source:'agent 明确建议',branch:'review/connection',detail:'候选关联由成员决定；本原型确认只改变内存中的演示数据。'}
  ];
  const gitGraph=[
    {id:'g1',kind:'commit',label:'f3a91d2',title:'初始化认证回执协议',branch:'main',lane:0,parents:[],time:'09:14',taskIds:[],status:'已提交',owner:'m1',source:'只读观测'},
    {id:'g2',kind:'commit',label:'7b2f93a',title:'分离凭据与连接状态',branch:'main',lane:0,parents:['g1'],time:'10:02',taskIds:['t3'],status:'已推送',owner:'m1',source:'只读观测'},
    {id:'g3',kind:'branch',label:'feat/shared-context',title:'从 main 创建功能分支',branch:'feat/shared-context',lane:1,parents:['g2'],time:'10:25',taskIds:['t1','t5'],status:'开发中',owner:'m1',source:'明确关联'},
    {id:'g4',kind:'commit',label:'02f4ac1',title:'增加来源与版本引用',branch:'feat/shared-context',lane:1,parents:['g3'],time:'13:40',taskIds:['t1'],status:'已提交',owner:'m1',source:'agent 明确报告'},
    {id:'g5',kind:'branch',label:'feat/delivery-evidence',title:'从 main 创建功能分支',branch:'feat/delivery-evidence',lane:2,parents:['g2'],time:'10:41',taskIds:['t2'],status:'待审阅',owner:'m2',source:'明确关联'},
    {id:'g6',kind:'commit',label:'a41f92c',title:'添加交付对象与反向任务索引',branch:'feat/delivery-evidence',lane:2,parents:['g5'],time:'14:04',taskIds:['t2'],status:'已提交',owner:'m2',source:'只读观测'},
    {id:'g7',kind:'pr',label:'PR #42',title:'共享上下文与交付关联',branch:'feat/delivery-evidence',lane:2,parents:['g6'],time:'14:28',taskIds:['t1','t2'],status:'打开 · 待审阅',owner:'m2',source:'GitHub 只读状态'},
    {id:'g8',kind:'branch',label:'docs/onboarding',title:'从 main 创建文档分支',branch:'docs/onboarding',lane:3,parents:['g2'],time:'11:05',taskIds:['t4'],status:'开发中',owner:'m3',source:'明确关联'},
    {id:'g9',kind:'commit',label:'b82dd10',title:'记录跨电脑接入步骤',branch:'docs/onboarding',lane:3,parents:['g8'],time:'13:54',taskIds:['t4'],status:'已提交',owner:'m3',source:'agent 明确报告'},
    {id:'g10',kind:'merge',label:'8d291ce',title:'合入访问权限修复',branch:'main',lane:0,parents:['g2','g9'],time:'昨天',taskIds:['t7'],status:'已合并',owner:'m1',source:'远端只读观测'},
    {id:'g11',kind:'release',label:'v0.9.0',title:'发布项目协作更新',branch:'main',lane:0,parents:['g10'],time:'昨天',taskIds:['t7'],status:'已发布',owner:'m1',source:'GitHub Release 只读观测'}
  ];
  const activity=[{id:'e1',title:'林可打开 PR #42',detail:'共享上下文与交付关联',time:'14:28',type:'delivery',target:'d1'},{id:'e2',title:'陈予安回复了模型处理回执问题',detail:'R-12 · 尚未确认解决',time:'14:26',type:'request',target:'r1'},{id:'e3',title:'连接状态约定提出 v3',detail:'v2 仍然生效',time:'14:20',type:'contract',target:'c1'},{id:'e4',title:'周宁分享接入检查清单',detail:'成员明确分享的文件',time:'13:54',type:'file',target:'f1'},{id:'e5',title:'成员与 agent 能力展示更新进展',detail:'agent 明确报告',time:'13:40',type:'task',target:'t5'},{id:'e6',title:'项目文件访问权限完成合并',detail:'合并不代表验收',time:'昨天',type:'task',target:'t7'}];
  const projects=[
    {id:'atlas',name:'Coopagents',team:'同频产品团队',repository:'example/coopagents',description:'跨电脑、跨 coding agent 的项目协作',color:'green',members,tasks,requests,contracts,files,deliveries,gitGraph,activity},
    {id:'relay',name:'开发者文档',team:'同频产品团队',repository:'example/developer-docs',description:'接入指南、支持矩阵与公开演示',color:'blue',members:[members[2]],tasks:[{id:'rt1',key:'DOC-004',title:'整理跨电脑接入示例',state:'working',owner:'m3',scope:'guides/remote',summary:'整理网络与权限诊断的独立步骤。',time:'14:05',branch:'docs/remote',evidence:'合成文档项目'}],requests:[],contracts:[],files:[],deliveries:[],gitGraph:[],activity:[]},
    {id:'blank',name:'新项目',team:'实验团队',repository:'',description:'尚无协作记录',color:'amber',members:[{...members[0],agents:[]}],tasks:[],requests:[],contracts:[],files:[],deliveries:[],gitGraph:[],activity:[]}
  ];
  const currentUser={id:'m1',name:'陈予安',initial:'陈',color:'green',username:'design-preview'};
  const teams=[
    {id:'team1',name:'同频产品团队',members:[{id:'m1',role:'所有者',projects:['atlas']},{id:'m2',role:'管理员',projects:['atlas','relay']},{id:'m3',role:'成员',projects:['atlas','relay']}],projects:['atlas','relay']},
    {id:'team2',name:'实验团队',members:[{id:'m1',role:'所有者',projects:['blank']}],projects:['blank']}
  ];
  const objects={task:'tasks',request:'requests',contract:'contracts',file:'files',delivery:'deliveries',agent:'agents'};
  const objectViews={task:['tasks'],request:['collaboration'],contract:['context'],file:['context'],delivery:['delivery'],agent:['members']};
  function findObject(project,item){const [type,id]=String(item).split(':');return (type==='agent'?project.members.flatMap(m=>m.agents):project[objects[type]]||[]).find(o=>o.id===id);}
  function parseRoute(hash){
    const [path,query='']=String(hash||'').replace(/^#\/?/,'').split('?');const [pid,vid]=path.split('/'),args=new URLSearchParams(query);
    const project=projects.find(p=>p.id===pid)||projects[0],view=Object.hasOwn(views,vid)?vid:'overview';
    const allowed=tabs[view]||[],tab=allowed.includes(args.get('tab'))?args.get('tab'):allowed[0]||'';
    let item=args.get('item')||'';const type=item.split(':')[0];
    if(!objectViews[type]?.includes(view)||!findObject(project,item)||(type==='file'&&tab!=='files')||(type==='contract'&&tab!=='agreements'))item='';
    return {project:project.id,view,tab,item,mode:args.get('mode')==='read'?'read':'edit'};
  }
  function routeURL(route){const q=new URLSearchParams();if(route.tab)q.set('tab',route.tab);if(route.item)q.set('item',route.item);if(route.mode==='read')q.set('mode','read');return '#/'+route.project+'/'+route.view+(q.size?'?'+q:'');}
  function filterTasks(project,query,state,owner){const q=String(query).trim().toLocaleLowerCase();return project.tasks.filter(t=>(!q||[t.key,t.title,t.scope,t.summary].join(' ').toLocaleLowerCase().includes(q))&&(!state||state==='all'||(state==='active'?t.state!=='merged':t.state===state))&&(!owner||t.owner===owner));}
  function relations(project,id){return {requests:project.requests.filter(r=>r.taskId===id||r.relatedTask===id),deliveries:project.deliveries.filter(d=>d.taskIds.includes(id))};}
  function graphEdges(project){const rows=new Map(project.gitGraph.map((node,index)=>[node.id,index]));return project.gitGraph.flatMap((node,to)=>node.parents.map(from=>({from,to:node.id,fromRow:rows.get(from),toRow:to,fromLane:project.gitGraph[rows.get(from)]?.lane||0,toLane:node.lane}))).filter(edge=>edge.fromRow!==undefined);}
  const api={views,tabs,projects,teams,currentUser,parseRoute,routeURL,findObject,filterTasks,relations,graphEdges};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.WorkspaceModel=api;
})();
