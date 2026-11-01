import {C, Frame, Headline, MONO, Panel, Reveal, useSeconds} from './design';

export const Control = () => {
 const t=useSeconds();
 return <Frame chapter="09 / HUMAN BY DESIGN" duration={15}>
  <Headline label="人，始终掌握重要决定" lines={['让 agent 协作。','让人作决定。']} body={'创建任务、批准约定、接受交接、修改权限。\n这些决定，仍然由人掌握。'}/>
  <div style={{position:'absolute',left:1080,top:275,width:620,height:620}}><svg width={620} height={620}>{[220,270,300].map((r,i)=><circle key={r} cx={310} cy={310} r={r} stroke={i===0?'#86A28F':C.line} strokeWidth={1.5} fill="none" strokeDasharray={i===1?'3 14':undefined} transform={`rotate(${t*5} 310 310)`}/>)}<circle cx={310} cy={310} r={150} fill={C.mint}/></svg><div style={{position:'absolute',top:258,width:'100%',textAlign:'center',fontSize:46,fontWeight:650}}>由你决定<div style={{fontFamily:MONO,fontSize:18,marginTop:18,fontWeight:400}}>HUMAN IN THE LOOP</div></div>{['约定','交接','权限'].map((s,i)=><Reveal key={s} delay={1+i*2} style={{position:'absolute',left:i===0?-20:i===1?475:225,top:i===0?185:i===1?200:570}}><Panel style={{padding:'14px 28px',fontSize:25}}>{s}</Panel></Reveal>)}</div>
 </Frame>;
};
