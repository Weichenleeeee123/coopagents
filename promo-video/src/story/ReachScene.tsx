import {Img, staticFile} from 'remotion';
import {C} from './palette';
import {EASE} from './motion';

const mono='"Cascadia Code", Consolas, monospace';
export function Device({app,device,frame,compact=false}:{app:'Claude Code'|'Codex';device:'Laptop A'|'Desktop B';frame:number;compact?:boolean}){
 const isClaude=app==='Claude Code';const accent=isClaude?C.terminalCoral:C.terminalBlue;
 return <div style={{width:720,height:500,position:'relative',transform:`perspective(1800px) rotateY(${(isClaude?1:-1)*(7+Math.sin(frame/150)*2)}deg) rotateX(2deg)`}}>
  <div style={{position:'absolute',left:38,right:38,top:0,height:390,borderRadius:23,background:C.ink,padding:13,boxSizing:'border-box',boxShadow:'0 30px 65px #20212425',border:'1px solid #4B5259'}}>
   <div style={{height:'100%',borderRadius:13,background:'#242933',padding:28,boxSizing:'border-box',color:C.terminalText,fontFamily:mono}}>
    <div style={{display:'flex',alignItems:'center',gap:15,fontSize:27,color:accent}}><span style={{height:13,width:13,borderRadius:12,background:accent}}/>{app}</div>
    <div style={{fontSize:37,marginTop:36}}>❯ {isClaude?'claude':'codex'}<span style={{opacity:Math.floor(frame/23)%2}}> ▌</span></div>
    <div style={{fontSize:25,marginTop:27,color:'#B7C3CE'}}>{isClaude?'Frontend / Alice':'Backend / Mia'}</div>
    <div style={{display:'flex',gap:10,marginTop:31}}>{[160,90,130].map((w,i)=><div key={w} style={{height:7,width:w,borderRadius:5,background:accent,opacity:.22+((frame/90+i)%1)*.25}}/>)}</div>
   </div>
  </div>
  {device==='Laptop A'?<svg width={720} height={90} style={{position:'absolute',top:386}} viewBox="0 0 720 90"><path d="M39 0 H681 L720 52 Q720 68 692 68 H28 Q0 68 0 52Z" fill="#D8DDE2" stroke="#B3BBC4"/><path d="M275 0 H445 L455 17 H265Z" fill="#ADB7C1"/><path d="M5 52 H715" stroke="#9DA9B5"/></svg>:<svg width={720} height={110} style={{position:'absolute',top:383}} viewBox="0 0 720 110"><path d="M310 0 H410 L424 78 H296Z" fill="#BBC5CE"/><path d="M245 78 H475 Q492 78 497 96 H223 Q228 78 245 78Z" fill="#D3DCE3"/></svg>}
  {!compact?<div style={{position:'absolute',top:490,left:0,right:0,textAlign:'center',fontSize:25,fontWeight:550,color:isClaude?C.orange:C.blue}}>{device}</div>:null}
 </div>;
}

export const ReachScene=({frame,stage}:{frame:number;stage:string})=>{
 const regions=stage==='regions';const agents=stage==='agents';const t=frame/60;const enter=EASE(frame/65);
 const deviceScale=regions?.64:agents?.88:1;
 return <div style={{width:1800,height:720,position:'relative'}}>
  <div style={{position:'absolute',left:regions?0:35,top:regions?300:120,transformOrigin:'left top',transform:`translateX(${(1-enter)*-100}px) scale(${deviceScale})`,opacity:enter}}><Device app="Claude Code" device="Laptop A" frame={frame} compact={regions}/></div>
  <div style={{position:'absolute',right:regions?0:agents?-45:35,top:regions?300:120,transformOrigin:'right top',transform:`translateX(${(1-enter)*100}px) scale(${deviceScale})`,opacity:enter}}><Device app="Codex" device="Desktop B" frame={frame} compact={regions}/></div>
  {regions?<>
   <svg viewBox="0 0 1800 720" style={{position:'absolute',inset:0,width:'100%',height:'100%'}}>
    <defs><radialGradient id="reach-globe"><stop stopColor="#FFFFFF"/><stop offset=".8" stopColor="#E5EDF8"/><stop offset="1" stopColor="#C8D9ED"/></radialGradient><clipPath id="reach-sphere"><circle cx="900" cy="327" r="240"/></clipPath></defs>
    <circle cx="900" cy="327" r="258" fill="none" stroke={C.blue} strokeOpacity=".1" strokeWidth="16"/>
    <circle cx="900" cy="327" r="240" fill="url(#reach-globe)"/>
    <g clipPath="url(#reach-sphere)" fill="none" stroke="#8CAAD0" strokeOpacity=".43" strokeWidth="1.5">
     {[-180,-90,0,90,180].map(y=><ellipse key={y} cx="900" cy={327+y*.82} rx={Math.sqrt(240*240-y*y)} ry={35+Math.abs(y)*.09}/>)}
     {[0,1,2,3,4].map(i=><ellipse key={i} cx="900" cy="327" rx={Math.abs(Math.sin(t*.13+i*Math.PI/5))*238+2} ry="240" transform="rotate(-16 900 327)"/>)}
    </g>
    <path d="M275 420 C640 -30 1150 -30 1525 420" fill="none" stroke={C.blue} strokeWidth="4" pathLength="1" strokeDasharray={`${EASE((frame-25)/85)} 1`}/>
    <path d="M275 440 C650 690 1160 690 1525 440" fill="none" stroke={C.green} strokeWidth="2" strokeOpacity=".45"/>
    {[0,1,2].map(i=>{const q=(frame/210+i/3)%1,v=1-q;const x=275*v*v*v+3*640*v*v*q+3*1150*v*q*q+1525*q*q*q;const y=420*v*v*v-90*v*v*q-90*v*q*q+420*q*q*q;return <g key={i}><circle cx={x} cy={y} r={12} fill={i%2?C.orange:C.blue}/><circle cx={x} cy={y} r="23" fill="none" stroke={i%2?C.orange:C.blue} opacity=".2"/></g>;})}
   </svg>
   <div style={{position:'absolute',left:60,top:217,fontSize:37,fontWeight:650,color:C.orange}}>Region A</div>
   <div style={{position:'absolute',right:70,top:217,fontSize:37,fontWeight:650,color:C.blue}}>Region B</div>
   <div style={{position:'absolute',left:0,right:0,top:632,textAlign:'center',fontSize:25,color:C.muted}}>Shared project context · Illustrated locations</div>
  </>:<>
   <svg viewBox="0 0 1800 720" style={{position:'absolute',inset:0,width:'100%',height:'100%'}}><path d="M660 350 C810 180 990 180 1140 350" stroke={C.blue} strokeWidth="4" fill="none" pathLength="1" strokeDasharray={`${EASE(frame/90)} 1`}/><path d="M660 400 C810 565 990 565 1140 400" stroke={C.green} strokeWidth="3" fill="none" opacity=".5"/></svg>
   <div style={{position:'absolute',left:807,top:282,transform:`scale(${.84+enter*.16})`}}><Img src={staticFile('coopagents-icon.png')} style={{width:186,height:186,borderRadius:44,boxShadow:'0 24px 65px #20212420'}}/></div>
   <div style={{position:'absolute',top:550,left:750,width:300,textAlign:'center',fontSize:26,color:C.green}}>One shared project</div>
  </>}
 </div>;
};
