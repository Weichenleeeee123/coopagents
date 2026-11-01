import {Fragment} from 'react';
import type {ReactNode, CSSProperties} from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import shots from './shots.json';
import {TERMINAL_CONTENT} from './terminalContent';
import {AUDIO_ENVELOPE} from '../motion/audio-envelope';
import {C} from './palette';
import {LightBackdrop} from './LightBackdrop';
import {stageMotion} from './motion';
import {ReachScene} from './ReachScene';
import {PainPoint} from './PainPoint';
import {EnglishWorkbench} from './EnglishWorkbench';


const FONT='"Segoe UI Variable", "Segoe UI", sans-serif';
const MONO='"Cascadia Code", Consolas, monospace';
const cl={extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
const p=(f:number,start=0,len=30)=>{const n=Math.max(0,Math.min(1,(f-start)/len));return 1-(1-n)**3;};
const text=(value:string,frame:number,start=12,speed=27)=>Array.from(value).slice(0,Math.max(0,Math.floor((frame-start)/60*speed))).join('');
const Rise=({children,frame,start=0,style}:{children:ReactNode;frame:number;start?:number;style?:CSSProperties})=><div style={{opacity:p(frame,start),translate:`0px ${(1-p(frame,start))*20}px`,...style}}>{children}</div>;
const Badge=({children,color=C.blue}:{children:ReactNode;color?:string})=><span style={{display:'inline-block',border:`1px solid ${color}66`,borderRadius:30,padding:'9px 20px',fontSize:23,color,background:`${color}12`}}>{children}</span>;
const Panel=({children,style}:{children:ReactNode;style?:CSSProperties})=><div style={{boxSizing:'border-box',background:C.panel,border:`1px solid ${C.line}`,borderRadius:25,boxShadow:'0 24px 60px #20212412',...style}}>{children}</div>;


function Term({app='Claude Code',tab='atlas / frontend',children,style}:{app?:string;tab?:string;children:ReactNode;style?:CSSProperties}){
 const accent=app==='Codex'?C.terminalBlue:C.terminalCoral;
 return <Panel style={{width:1400,height:580,overflow:'hidden',background:C.terminal,color:C.terminalText,...style}}>
  <div style={{height:74,display:'flex',alignItems:'center',gap:22,padding:'0 32px',borderBottom:'1px solid #35423A',background:C.ink}}><div style={{display:'flex',gap:9}}>{['#D98473','#D9BC6E','#93B883'].map(c=><span key={c} style={{width:12,height:12,borderRadius:10,background:c}}/>)}</div><span style={{color:accent,fontFamily:MONO,fontSize:25,fontWeight:600}}>{app}</span><span style={{fontFamily:MONO,fontSize:21,color:'#AAB9AA',marginLeft:'auto'}}>{tab}</span></div>
  <div style={{padding:'37px 42px',fontFamily:MONO,fontSize:35,lineHeight:1.7,background:C.terminal,color:C.terminalText,height:'calc(100% - 74px)',boxSizing:'border-box'}}>{children}</div>
 </Panel>;
}
function Call({name,frame,start=70}:{name:string;frame:number;start?:number}){return <Rise frame={frame} start={start}><div style={{color:C.terminalMint,fontSize:26,margin:'18px 0 14px'}}><span style={{display:'inline-block',width:10,height:10,marginRight:13,borderRadius:10,background:C.green}}/>coopagents / {name}</div></Rise>;}
function TerminalShot({stage,frame}:{stage:string;frame:number}){
 const d=TERMINAL_CONTENT[stage];
 return <Term app={d.app} tab={d.tab}>
  <div style={{minHeight:65}}><span style={{color:C.terminalMint,marginRight:18}}>❯</span>{text(d.prompt,frame)}<span style={{opacity:Math.floor(frame/22)%2?0:1,color:C.terminalMint}}>▌</span></div>
  {d.tool?<Call name={d.tool} frame={frame}/>:<div style={{height:35}}/>}
  {d.lines.map((line,i)=><Rise key={line} frame={frame} start={95+i*34}><div style={{color:i===1?C.terminalMuted:C.terminalText,fontSize:32,marginTop:10}}><span style={{color:'#647761',marginRight:18}}>{i===0?'›':' '}</span>{line}</div></Rise>)}
  {stage==='configure'?<Rise frame={frame} start={215}><div style={{color:C.terminalCoral,fontSize:24,marginTop:25}}>Preserve settings / Wake-up stays off</div></Rise>:null}
 </Term>;
}
function MiniTerm({app,lines,frame}:{app:string;lines:string[];frame:number}){return <Term app={app} tab={app==='Codex'?'atlas / backend':'atlas / frontend'} style={{width:760,height:440}}><div style={{fontSize:29,color:C.terminalMint}}>❯ {app==='Codex'?'codex':'claude'}<span style={{opacity:Math.floor(frame/20)%2}}> ▌</span></div>{lines.map((line,i)=><Rise key={line} frame={frame} start={12+i*25}><div style={{fontSize:28,marginTop:28,color:i?C.terminalMuted:C.terminalText}}>{line}</div></Rise>)}</Term>;}

function TwoTools({frame,question=false}:{frame:number;question?:boolean}){return <div style={{position:'relative',width:1660,height:620}}>
 <div style={{position:'absolute',left:0,top:45,transform:`perspective(1800px) rotateY(${5-Math.sin(frame/100)*2}deg) rotateZ(-2deg)`}}><MiniTerm app="Claude Code" frame={frame} lines={question?['The login status field...','state? status?']:['Login integration','Frontend / Alice']}/></div>
 <div style={{position:'absolute',right:0,top:110,transform:`perspective(1800px) rotateY(-6deg) rotateZ(2deg)`}}><MiniTerm app="Codex" frame={frame} lines={question?['API agreement updated','Who needs this context?']:['Login API','Backend / Mia']}/></div>
 {question?<Rise frame={frame} start={35} style={{position:'absolute',left:690,top:0}}><Badge>Which field?</Badge></Rise>:null}
 </div>;}
function Setup({frame,reload}:{frame:number;reload:boolean}){return <Term tab="atlas / setup">
 <div style={{color:C.terminalCoral,fontSize:28}}>Claude Code · Coopagents</div>
 {reload?<><Rise frame={frame} start={8}><div style={{fontSize:51,marginTop:35,color:C.terminalMint}}>✓ MCP configuration saved</div></Rise><Rise frame={frame} start={65}><div style={{fontSize:38,marginTop:38}}>Next: open a new Claude Code session</div></Rise><Rise frame={frame} start={105}><div style={{fontSize:26,color:C.terminalMuted,marginTop:26}}>In the new session: whoami → read_team</div></Rise></>:['Read the Coopagents space Skill','Reuse a matching connection when available','Save MCP configuration for this repo'].map((s,i)=><Rise key={s} frame={frame} start={15+i*42}><div style={{marginTop:29,display:'flex',alignItems:'center',gap:18}}><span style={{color:C.terminalMint}}>✓</span>{s}</div></Rise>)}
 </Term>;}
function Invitation({frame,join}:{frame:number;join:boolean}){return <div style={{position:'relative',width:1500,height:640}}>
 <div style={{position:'absolute',left:join?260:0,top:20}}><Term app={join?'Codex':'Claude Code'} tab="atlas / invitation" style={{width:1220,height:550}}><div><span style={{color:C.terminalMint}}>❯ </span>{text(join?'Use this invite to join Atlas.':'Create a private invite for Mia.',frame)}</div><Rise frame={frame} start={85}><div style={{marginTop:35,fontSize:30,color:C.terminalMuted}}>{join?'Configure → verify in a new session':'One-time invite / Share privately'}</div></Rise></Term></div>
 <Rise frame={frame} start={75} style={{position:'absolute',left:join?70:1030,top:310,rotate:join?'-5deg':'5deg'}}><Panel style={{background:C.mint,color:C.ink,padding:30,width:380,height:230}}><div style={{fontFamily:MONO,fontSize:24,fontWeight:700}}>ATLAS / INVITE</div><div style={{marginTop:24,fontSize:25}}>Contents hidden</div><div style={{display:'flex',gap:8,marginTop:22}}>{Array.from({length:12},(_,i)=><div key={i} style={{width:12,height:22,background:'#22341B',opacity:.3+i%3*.1,borderRadius:3}}/>)}</div></Panel></Rise>
 </div>;}
function Team({frame}:{frame:number}){return <Panel style={{width:1430,height:590,padding:44}}><div style={{display:'flex',alignItems:'center',justifyContent:'space-between'}}><span style={{fontSize:42}}>Atlas / Project members</span><Badge>read_team</Badge></div><div style={{display:'flex',gap:32,marginTop:58}}>{[['Alice','Claude Code',C.orange],['Mia','Codex',C.blue]].map(([name,app,c],i)=><Rise key={name} frame={frame} start={15+i*50} style={{flex:1}}><Panel style={{height:260,padding:36,background:'#F3F5F8'}}><div style={{fontSize:44,color:c}}>{name}</div><div style={{fontSize:30,marginTop:12}}>{app}</div><div style={{fontSize:19,marginTop:18,color:C.muted}}>Member and tool registered</div><div style={{fontSize:19,marginTop:12,color:C.muted}}>{name==='Alice'?'Laptop A / Region A':'Desktop B / Region B'}</div></Panel></Rise>)}</div></Panel>;}
function SharedContext({frame,lookup}:{frame:number;lookup:boolean}){return <div style={{position:'relative',width:1460,height:640}}>
 <Panel style={{position:'absolute',left:40,top:20,width:1340,height:570,padding:44,background:'#FFFFFF',color:C.ink}}><div style={{display:'flex',alignItems:'center',justifyContent:'space-between'}}><span style={{fontSize:35}}>Atlas / API agreement</span><Badge color="#416546">Approved</Badge></div><div style={{height:1,background:'#C9D3C5',marginTop:28}}/><div style={{fontSize:29,color:'#64765E',marginTop:32}}>Login API / Response field</div><Rise frame={frame} start={18}><div style={{fontFamily:MONO,fontSize:100,fontWeight:600,marginTop:18,display:'inline-block',background:lookup?C.mint:'transparent',padding:'0 20px',borderRadius:12}}>status</div></Rise><div style={{fontSize:24,color:'#5E7057',marginTop:33}}>Source: team-approved API agreement</div></Panel>
 {lookup?<Rise frame={frame} start={35} style={{position:'absolute',left:980,top:480}}><Panel style={{padding:'24px 32px',fontFamily:MONO,fontSize:26,color:C.green}}>MCP / read_context</Panel></Rise>:null}
 </div>;}
function Route({frame,answer}:{frame:number;answer:boolean}){const q=p(frame,15,130);const x=answer?1100-q*700:230+q*700;return <div style={{width:1640,height:600,position:'relative'}}>
 <svg width={1640} height={600} style={{position:'absolute',inset:0}}><path d="M210 320 C600 100 1000 540 1430 320" fill="none" stroke="#60794E" strokeWidth={4} pathLength={1} strokeDasharray={`${p(frame,0,90)} 1`}/></svg>
 {[['Alice','Claude Code'],['Mia','Codex']].map(([name,app],i)=><Panel key={name} style={{position:'absolute',left:i?1280:0,top:205,width:330,height:265,padding:30}}><div style={{fontSize:42,color:i?C.green:C.orange}}>{name}</div><div style={{fontSize:28,marginTop:18}}>{app}</div><div style={{fontSize:18,color:C.muted,marginTop:23}}>{i?'Desktop B / Region B':'Laptop A / Region A'}</div></Panel>)}
 <div style={{position:'absolute',left:x,top:150+Math.sin(q*Math.PI)*125,width:380,padding:28,boxSizing:'border-box',borderRadius:20,background:answer?C.mint:C.sky,color:C.ink,boxShadow:'0 30px 60px #0005'}}><div style={{fontSize:30,fontWeight:600}}>{answer?'The field is status.':'Login status field?'}</div><div style={{fontFamily:MONO,fontSize:19,marginTop:16}}>{answer?'reply → requests[].replies':'send_request → Mia'}</div></div>
 {answer?<Rise frame={frame} start={130} style={{position:'absolute',left:430,top:480}}><Badge>Reply on the original request / read_team</Badge></Rise>:null}
 </div>;}
function Code({frame,commit}:{frame:number;commit:boolean}){return <Term app="Claude Code" tab="atlas / frontend / login.ts" style={{height:620}}>
 <div style={{fontSize:25,color:C.terminalMuted,marginBottom:30}}>{commit?'CHANGE REVIEW / Login integration':'TYPESCRIPT / Login response'}</div>
 <div style={{fontSize:39}}><span style={{color:'#B7A5EC'}}>const </span>response = <span style={{color:'#B7A5EC'}}>await </span>login();</div>
 <Rise frame={frame} start={15}><div style={{fontSize:39,marginTop:24,color:'#D89989',textDecoration:frame>80?'line-through':'none',opacity:frame>100?.45:1}}>- const status = response.state;</div></Rise>
 <Rise frame={frame} start={commit?70:24}><div style={{fontSize:39,marginTop:18,color:C.terminalMint}}>+ const status = response.<span style={{background:'#A5E1CA25',padding:'3px 9px'}}>status</span>;</div></Rise>
 <Rise frame={frame} start={125}><div style={{fontSize:26,marginTop:45,color:C.terminalMuted}}>{commit?'Demo commit linked to the login task':'Aligned with the shared API agreement'}</div></Rise>
 </Term>;}
function Task({frame,claim}:{frame:number;claim:boolean}){return <Panel style={{width:1420,height:590,padding:42,position:'relative'}}><div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}><div style={{fontSize:36}}>Atlas / Shared tasks</div><Badge>Created by Alice</Badge></div><div style={{display:'flex',gap:25,marginTop:32}}>{['Unclaimed','In progress','Delivery links'].map((s,i)=><div key={s} style={{width:428,height:340,borderTop:`3px solid ${i===1?C.green:C.line}`,paddingTop:18,color:C.muted,fontSize:23}}>{s}</div>)}</div><div style={{position:'absolute',left:42+(claim?p(frame,35,100)*453:0),top:210,width:380}}><Panel style={{padding:28,background:claim?C.mint:C.sky,color:C.ink}}><div style={{fontSize:34}}>Login integration</div><div style={{fontSize:23,marginTop:22}}>{claim?'Alice / Claude Code':'Ready to claim'}</div><div style={{fontSize:20,marginTop:20,opacity:.7}}>{claim?'claim_task':'Existing task'}</div></Panel></div></Panel>;}
function Delivery({frame}:{frame:number}){return <div style={{width:1600,height:560,position:'relative'}}><svg width={1600} height={560} style={{position:'absolute',inset:0}}><path d="M300 270 C700 100 900 440 1300 270" fill="none" stroke={C.green} strokeWidth={5} pathLength={1} strokeDasharray={`${p(frame,20,100)} 1`}/></svg>{[['Login integration','Shared task'],['login.ts','Demo commit']].map(([name,label],i)=><Rise key={name} frame={frame} start={i*40} style={{position:'absolute',left:50+i*1010,top:145}}><Panel style={{width:490,height:255,padding:40}}><div style={{fontSize:25,color:C.muted}}>{label}</div><div style={{fontSize:50,marginTop:24,color:i?C.green:C.text}}>{name}</div></Panel></Rise>)}<Rise frame={frame} start={115} style={{position:'absolute',left:680,top:440}}><Badge>Confirmed association</Badge></Rise></div>;}
function Workbench({frame}:{frame:number}){return <EnglishWorkbench frame={frame}/>;}
function Control({frame}:{frame:number}){const clicked=frame>125;return <Panel style={{width:1200,height:620,padding:46,position:'relative'}}><div style={{fontSize:35,color:C.muted}}>Atlas / Proposed agreement</div><div style={{fontSize:60,marginTop:35}}>Add error-code notes</div><div style={{marginTop:30}}><Badge color={clicked?C.green:C.orange}>{clicked?'Approved by Alice':'Needs human approval'}</Badge></div><div style={{position:'absolute',bottom:60,right:55,padding:'22px 42px',borderRadius:17,background:clicked?C.mint:C.lavender,color:C.ink,fontSize:32,fontWeight:600}}>{clicked?'Approved ✓':'Approve agreement'}</div><svg width={90} height={110} style={{position:'absolute',left:interpolate(frame,[0,125],[1120,1000],cl),top:interpolate(frame,[0,125],[590,500],cl),filter:'drop-shadow(0 8px 12px #20212425)'}} viewBox="0 0 80 100"><path d="M8 4 L70 48 L43 55 L57 87 L42 94 L28 62 L8 84 Z" fill="#F1F3E9" stroke="#253125" strokeWidth={3}/></svg></Panel>;}
function Recap({frame}:{frame:number}){return <div style={{display:'flex',gap:24,alignItems:'center'}}>{[['read_context','Shared context'],['reply','Direct replies'],['read_deliveries','Linked delivery']].map(([tool,label],i)=><Fragment key={tool}><Rise frame={frame} start={i*35}><Panel style={{width:460,height:300,padding:36}}><div style={{fontSize:49,color:C.green}}>{label}</div><div style={{fontFamily:MONO,fontSize:25,marginTop:46}}>{tool}</div><div style={{height:3,width:`${p(frame,i*35,100)*100}%`,background:C.green,marginTop:35}}/></Panel></Rise>{i<2?<span style={{fontSize:45,color:'#8FA583'}}>→</span>:null}</Fragment>)}</div>;}

export const StoryStage=({shotId}:{shotId:number})=>{
 const frame=useCurrentFrame();const shot=shots[shotId];if(!shot)throw new Error('Unknown storyboard shot');
 const globalFrame=shot.start+frame;const hero=['brand','closing'].includes(shot.kind);
 const energy=AUDIO_ENVELOPE[Math.min(7761,Math.max(0,globalFrame))]?.[0]??0;
 const camera=stageMotion(shotId,frame,shot.duration);
 let visual:ReactNode;
 switch(shot.kind){
  case 'pain':visual=<PainPoint frame={frame} stage={shot.stage}/>;break;
  case 'relief':visual=<PainPoint frame={frame} stage="relief"/>;break;
  case 'reach':visual=<ReachScene frame={frame} stage={shot.stage}/>;break;
  case 'terminal':visual=<TerminalShot stage={shot.stage} frame={frame}/>;break;
  case 'hook':visual=<TwoTools frame={frame}/>;break;
  case 'question':visual=<TwoTools question frame={frame}/>;break;
  case 'tools':visual=<TwoTools frame={frame}/>;break;
  case 'setup':visual=<Setup frame={frame} reload={shot.stage==='reload'}/>;break;
  case 'invite':visual=<Invitation frame={frame} join={shot.stage==='join'}/>;break;
  case 'team':visual=<Team frame={frame}/>;break;
  case 'context':visual=<SharedContext frame={frame} lookup={shot.stage==='lookup'}/>;break;
  case 'route':visual=<Route frame={frame} answer={shot.stage==='answer'}/>;break;
  case 'code':visual=<Code frame={frame} commit={shot.stage==='commit'}/>;break;
  case 'task':visual=<Task frame={frame} claim={shot.stage==='claim'}/>;break;
  case 'delivery':visual=<Delivery frame={frame}/>;break;
  case 'workbench':visual=<Workbench frame={frame}/>;break;
  case 'control':visual=<Control frame={frame}/>;break;
  case 'recap':visual=<Recap frame={frame}/>;break;
  default:visual=<div style={{textAlign:'center'}}><Img src={staticFile('coopagents-icon.png')} style={{width:190,height:190,borderRadius:44,scale:1+energy*.025}}/><div style={{fontFamily:'Segoe UI,sans-serif',fontSize:152,letterSpacing:-7,fontWeight:650,marginTop:20}}>Coopagents</div>{shot.stage==='cta'?<Rise frame={frame} start={55}><div style={{fontFamily:MONO,fontSize:29,color:C.blue,marginTop:40}}>github.com/Weichenleeeee123/coopagents</div></Rise>:null}</div>;
 }
 return <AbsoluteFill style={{background:'transparent',fontFamily:FONT,color:C.text,overflow:'hidden'}}>
  <div style={{position:'absolute',inset:0,opacity:camera.opacity}}><LightBackdrop globalFrame={globalFrame} hero={hero}/></div>
  <div style={{position:'absolute',top:65,left:92,right:92,display:'flex',alignItems:'center',justifyContent:'space-between',fontSize:22,color:C.muted,opacity:camera.opacity}}><span>{shot.tool?<><span style={{color:C.green}}>MCP</span> / {shot.tool}</>:'COOPAGENTS'}</span><span>{shot.kind==='workbench'?'Self-hosted service':shot.kind==='reach'?'Connection illustration':'Workflow illustration / Time compressed'}</span></div>
  <div style={{position:'absolute',left:0,right:0,top:150,height:700,display:'flex',alignItems:'center',justifyContent:'center',...camera}}>{visual}</div>
  <Rise frame={frame} start={9} style={{position:'absolute',left:92,right:92,bottom:87,fontSize:43,fontWeight:550,textAlign:'center',textShadow:'0 2px 20px #FFFFFF',opacity:camera.opacity}}>{shot.caption}</Rise>
 </AbsoluteFill>;
};
