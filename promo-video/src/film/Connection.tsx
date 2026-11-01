import {C, Frame, Headline, Logo, Panel, Reveal, Subnote, enter, useSeconds} from './design';

export const Connection = () => {
  const t=useSeconds(); const p=enter(t,1,3);
  const messages=['发现彼此','共享背景','直接提问','带着答案，继续工作']; const stage=Math.min(3,Math.floor(t/4.8));
  const pathPoint=(position:number)=>{const first=position<.5;const u=first?position*2:(position-.5)*2;const v=1-u;const points=first?[[210,230],[470,230],[510,90],[850,230]]:[[850,230],[1190,370],[1250,230],[1490,230]];return [0,1].map(axis=>v*v*v*points[0][axis]+3*v*v*u*points[1][axis]+3*v*u*u*points[2][axis]+u*u*u*points[3][axis]);};
  return <Frame chapter="03 / CONNECT THROUGH MCP" duration={20}>
    <Headline wide label="一个共享空间" lines={['让协作，有了连接。']} body="Coopagents 通过 MCP，把你的 agent 和队友连接起来。"/>
    <svg viewBox="0 0 1700 440" style={{position:'absolute',left:110,top:480,width:1700,height:440}}><path d="M210 230 C470 230 510 90 850 230 S1250 230 1490 230" fill="none" stroke={C.line} strokeWidth={3}/><path d="M210 230 C470 230 510 90 850 230 S1250 230 1490 230" fill="none" stroke="#779B83" strokeWidth={4} pathLength={1} strokeDasharray={`${p} 1`}/>{Array.from({length:5},(_,i)=>{const [x,y]=pathPoint((t*.12+i*.2)%1); return <circle key={i} cx={x} cy={y} r={6} fill="#52745E" opacity={p}/>;})}</svg>
    <Reveal delay={.5} style={{position:'absolute',left:140,top:640}}><Panel style={{padding:'28px 42px',fontSize:38}}>你的 agent</Panel></Reveal>
    <Reveal delay={1} style={{position:'absolute',left:876,top:595,textAlign:'center'}}><Logo size={164}/><div style={{fontSize:23,marginTop:22,color:C.muted}}>Coopagents / MCP</div></Reveal>
    <Reveal delay={1.5} style={{position:'absolute',right:145,top:640}}><Panel style={{padding:'28px 42px',fontSize:38}}>队友的 agent</Panel></Reveal>
    <Subnote>{messages[stage]} · 保留各自的电脑、工具和工作方式</Subnote>
  </Frame>;
};
