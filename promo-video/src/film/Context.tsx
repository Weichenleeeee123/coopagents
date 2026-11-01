import {C, Frame, Headline, MONO, Panel, Reveal, Subnote, useSeconds} from './design';

export const Context = () => {
 const t=useSeconds(); const step=Math.min(2,Math.floor(t/6));
 const rows=[['项目约定','接口返回明确的状态与来源。'],['待审提案','这是一项提案，还不是生效决定。'],['共享文件','只共享项目需要的那部分背景。']];
 return <Frame chapter="04 / SHARED CONTEXT" duration={20}>
  <Headline label="01 · 共享上下文" lines={['理解同一个','项目背景。']} body={'共享约定、文件与限定范围的上下文。\n让信息保留来源，也保留新鲜度。'}/>
  <div style={{position:'absolute',left:1040,top:255,width:730}}>{rows.map(([label,body],i)=><Reveal key={label} delay={1+i*3} style={{marginBottom:22,translate:`${step===i?-15:0}px 0px`}}><Panel style={{padding:34,borderColor:step===i?'#90A997':C.line}}><div style={{display:'flex',justifyContent:'space-between',fontSize:23,color:'#53725C',marginBottom:22}}>{label}<span style={{fontFamily:MONO,color:C.muted,fontSize:17}}>{i===1?'PENDING':'SHARED'}</span></div><div style={{fontSize:29,lineHeight:1.6}}>{body}</div><div style={{height:2,background:C.line,marginTop:28}}><div style={{height:2,width:step>=i?'100%':'18%',background:'#6E907A'}}/></div></Panel></Reveal>)}</div>
  <Subnote>情景演示 · 待审提案与生效决定，明确区分。</Subnote>
 </Frame>;
};
