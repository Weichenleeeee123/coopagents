import {C, Frame, Headline, MONO, Panel, Reveal, Subnote, enter, useSeconds} from './design';

export const Evidence = () => {
 const t=useSeconds(); const nodes=['任务','分支','提交','PR','Release']; const p=enter(t,1,15);
 return <Frame dark chapter="07 / CONNECTED TO EVIDENCE" duration={20}>
  <Headline dark wide label="04 · 可追溯的交付关系" lines={['从进展，走到证据。']} body="把任务关联到 Git 对象，查看关系与证据来源。"/>
  <svg width={1640} height={220} style={{position:'absolute',left:140,top:550}}><path d="M100 100 L1540 100" stroke="#526156" strokeWidth={2}/><path d="M100 100 L1540 100" stroke={C.mint} strokeWidth={3} pathLength={1} strokeDasharray={`${p} 1`}/>{nodes.map((n,i)=><circle key={n} cx={100+i*360} cy={100} r={t>1+i*3.5?12:6} fill={t>1+i*3.5?C.mint:'#59665C'}/>)}</svg>
  {nodes.map((n,i)=><Reveal key={n} delay={i*3.4} style={{position:'absolute',left:150+i*360,top:710,width:200,textAlign:'center'}}><div style={{fontSize:36}}>{n}</div><div style={{fontFamily:MONO,fontSize:18,color:C.mint,marginTop:18}}>EVIDENCE / 0{i+1}</div></Reveal>)}
  <Reveal delay={8} style={{position:'absolute',right:190,top:180}}><Panel dark style={{padding:'18px 26px',fontFamily:MONO,fontSize:19,color:C.mint}}>traceable, not assumed.</Panel></Reveal>
  <Subnote dark>关系示意 · 只呈现有证据的关联，不代表所有任务都经过固定交付流程。</Subnote>
 </Frame>;
};
