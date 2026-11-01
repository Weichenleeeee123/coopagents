import {C, Frame, Headline, MONO, Panel, Reveal, Subnote, enter, useSeconds} from './design';

export const Tasks = () => {
 const t=useSeconds(); const x=enter(t,4,2)*545+enter(t,12,2)*545;
 return <Frame chapter="06 / WORK THAT IS VISIBLE" duration={20}>
  <Headline wide label="03 · 任务与依赖" lines={['进展，大家都看得见。']} body="认领工作，汇报进展，把依赖放到共享看板里。"/>
  <div style={{position:'absolute',left:112,top:550,display:'flex',gap:25}}>{['待处理','进行中','交付关联'].map((s,i)=><Panel key={s} style={{width:520,height:315,padding:28,background:i===1?'#E7ECE4':'#F9FAF5'}}><div style={{fontSize:27,color:C.muted,display:'flex',justifyContent:'space-between'}}>{s}<span style={{fontFamily:MONO,fontSize:20}}>0{i+1}</span></div><div style={{height:1,background:C.line,marginTop:22}}/></Panel>)}</div>
  <Reveal delay={1} style={{position:'absolute',left:139+x,top:650,width:466}}><Panel style={{padding:28,boxShadow:'0 24px 45px #20212412'}}><div style={{fontFamily:MONO,fontSize:20,color:'#69816E'}}>TASK / DEMO-01</div><div style={{fontSize:32,marginTop:16}}>核对共享上下文接口</div><div style={{fontSize:21,color:C.muted,marginTop:22}}>{t<5?'等待认领':t<13?'已认领 · 正在核对':'已关联提交证据'}</div></Panel></Reveal>
  <Subnote>情景演示 · 任务可以认领和汇报；创建与接受交接仍由人决定。</Subnote>
 </Frame>;
};
