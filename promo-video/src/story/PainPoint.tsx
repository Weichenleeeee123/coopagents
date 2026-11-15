import {Device} from './ReachScene';
import {C} from './palette';
import {EASE} from './motion';

const Bubble=({label,x,y,color,scale=1,alpha=1}:{label:string;x:number;y:number;color:string;scale?:number;alpha?:number})=><div style={{position:'absolute',left:x-142,top:y-38,width:284,height:76,display:'flex',alignItems:'center',justifyContent:'center',background:color,color:C.ink,border:'1px solid white',borderRadius:20,boxShadow:'0 18px 40px #20212418',fontFamily:'"Cascadia Code",Consolas,monospace',fontSize:25,fontWeight:600,transform:`scale(${scale})`,opacity:alpha}}>{label}</div>;

export const PainPoint=({frame,stage}:{frame:number;stage:string})=>{
 const relief=stage==='relief';const first=stage==='parallel';const enter=EASE(frame/55);const t=frame/60;
 const humanY=relief?350+EASE(frame/80)*210:350;
 const q=(frame/138)%1;const half=q<.5;const u=EASE(half?q*2:(q-.5)*2);
 const packetX=half?450+u*450:900+u*450;
 const packetY=half?350-Math.sin(u*Math.PI)*75:350-Math.sin(u*Math.PI)*75;
 return <div style={{position:'relative',width:1800,height:720}}>
  <div style={{position:'absolute',left:5,top:215,transform:'scale(.76)',transformOrigin:'left top'}}><Device app="Claude Code" device="Laptop A" frame={frame}/></div>
  <div style={{position:'absolute',right:5,top:215,transform:'scale(.76)',transformOrigin:'right top'}}><Device app="Codex" device="Desktop B" frame={frame}/></div>
  <svg viewBox="0 0 1800 720" style={{position:'absolute',inset:0,width:'100%',height:'100%'}}>
   {!relief?<><path d="M470 370 Q650 230 800 345" fill="none" stroke={C.orange} strokeWidth="3" strokeDasharray="8 12"/><path d="M1000 345 Q1150 230 1330 370" fill="none" stroke={C.blue} strokeWidth="3" strokeDasharray="8 12"/></>:<><path d="M460 350 C740 50 1050 50 1340 350" fill="none" stroke={C.green} strokeWidth="5" pathLength="1" strokeDasharray={`${EASE(frame/65)} 1`}/><path d="M460 360 C730 540 1080 540 1340 360" fill="none" stroke={C.blue} strokeWidth="2" opacity=".5"/></>}
   <circle cx="900" cy={humanY} r={100+(stage==='bottleneck'?Math.sin(t*2)*5:0)} fill={relief?C.mint:C.lavender}/>
   <circle cx="900" cy={humanY-26} r="29" fill={relief?C.green:C.lilac}/><path d={`M845 ${humanY+45} Q850 ${humanY+1} 900 ${humanY+1} Q950 ${humanY+1} 955 ${humanY+45} Z`} fill={relief?C.green:C.lilac}/>
   <circle cx="900" cy={humanY} r="115" fill="none" stroke={relief?C.green:C.lilac} strokeWidth="2" opacity=".2"/>
  </svg>
  <div style={{position:'absolute',left:790,top:humanY+125,width:220,textAlign:'center',fontSize:28,fontWeight:600,color:relief?C.green:C.lilac}}>{relief?'You decide.':'YOU'}</div>
  {first?<><Bubble label="state?" x={400+EASE(frame/180)*160} y={270-EASE(frame/180)*90} color={C.coral} alpha={enter}/><Bubble label="status." x={1420-EASE((frame-20)/160)*180} y={260-EASE((frame-20)/160)*80} color={C.sky} alpha={EASE((frame-25)/40)}/></>:null}
  {stage==='relay'?<><Bubble label={half?'Copy the question':'Paste the context'} x={packetX} y={packetY-115} color={half?C.coral:C.sky}/><div style={{position:'absolute',left:765,top:72,fontSize:21,color:C.muted}}>COPY · EXPLAIN · PASTE</div></>:null}
  {stage==='clarify'||stage==='bottleneck'?<>
   {['Which field?','Latest spec?','Who owns this?'].map((label,i)=>{const e=EASE((frame-i*29)/45);return <Bubble key={label} label={label} x={680+i*220} y={105+Math.abs(i-1)*85-Math.sin(t*1.3+i)*10} color={[C.coral,C.sky,C.lavender][i]} alpha={e} scale={.78+e*.12}/>;})}
   {stage==='bottleneck'?<div style={{position:'absolute',left:770,top:530,fontSize:24,color:C.muted}}>Relay. Clarify. Repeat.</div>:null}
  </>:null}
  {relief?<>{[0,1,2].map(i=>{const a=(frame/180+i/3)%1,v=1-a;const x=460*v*v*v+3*740*v*v*a+3*1050*v*a*a+1340*a*a*a;const y=350*v*v*v+3*50*v*v*a+3*50*v*a*a+350*a*a*a;return <div key={i} style={{position:'absolute',left:x-65,top:y-24,width:130,height:48,borderRadius:18,background:i%2?C.sky:C.mint,color:i%2?C.blue:C.green,boxShadow:'0 8px 18px #20212415',display:'grid',placeItems:'center',fontFamily:'Consolas,monospace',fontSize:21}}>context</div>;})}<div style={{position:'absolute',top:60,left:620,right:620,textAlign:'center',fontFamily:'Consolas,monospace',fontSize:25,color:C.green}}>Shared context</div></>:null}
 </div>;
};
