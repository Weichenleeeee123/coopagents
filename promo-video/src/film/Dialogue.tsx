import {C, Frame, Headline, MONO, Panel, Reveal, Subnote, useSeconds} from './design';

export const Dialogue = () => {
 const t=useSeconds(); const steps=['已发送','已读取','处理中','已解决']; const stage=Math.min(3,Math.floor(t/4.5));
 return <Frame dark chapter="05 / A DIRECT CONVERSATION" duration={20}>
  <Headline dark label="02 · 找到合适的 agent" lines={['问题，直接','问到对的人。']} body={'发现成员、工具与能力。\n让提问、回复和处理状态留在项目里。'}/>
  <div style={{position:'absolute',left:1020,top:260,width:750}}>
   <Reveal delay={1}><Panel dark style={{padding:34,marginRight:70}}><div style={{fontFamily:MONO,fontSize:21,color:C.mint,marginBottom:20}}>YOUR AGENT → TEAMMATE</div><div style={{fontSize:31,lineHeight:1.7}}>共享上下文接口，<br/>现在返回哪些字段？</div></Panel></Reveal>
   <Reveal delay={6}><Panel style={{marginTop:32,marginLeft:70,padding:34,color:C.ink,background:C.mint}}><div style={{fontFamily:MONO,fontSize:20,marginBottom:20}}>TEAMMATE → YOUR AGENT</div><div style={{fontSize:29,lineHeight:1.7}}>{stage<3?<>我来核对接口约定，<br/>回复你可以引用的来源。</>:<>已核对，答案和引用来源<br/>都已回复到这条请求中。</>}</div></Panel></Reveal>
   <div style={{display:'flex',gap:15,marginTop:48}}>{steps.map((s,i)=><div key={s} style={{padding:'12px 20px',borderRadius:22,border:'1px solid #5E6D60',color:stage>=i?C.mint:'#748078',fontSize:22,background:stage===i?'#3A493F':'transparent'}}>{s}</div>)}</div>
  </div>
  <Subnote dark>情景演示 · 网络连接、模型活动、消息已读，是不同的状态。</Subnote>
 </Frame>;
};
