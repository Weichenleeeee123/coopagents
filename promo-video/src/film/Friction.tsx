import {C, Frame, Headline, MONO, Panel, Reveal, useSeconds} from './design';

export const Friction = () => {
  const t = useSeconds();
  const questions = [ ['Claude Code', '接口的约定，定了吗？', 'waiting for context'], ['Codex', '这段逻辑，谁在负责？', 'waiting for an owner'], ['你的团队', '刚才的决定，在哪里？', 'waiting for a shared answer'] ];
  return <Frame dark chapter="02 / THE SPACE BETWEEN" duration={18}>
    <Headline dark wide label="每个 agent 都能独立工作" lines={['但上下文，还隔着一层。']} body={'决定散落在会话里。问题停在另一台电脑上。'}/>
    <div style={{position:'absolute',left:112,right:112,top:590,display:'flex',gap:28}}>
      {questions.map(([name,q,foot],i)=><Reveal key={name} delay={1+i*3.5} style={{flex:1, translate:`0px ${Math.sin(t*.7+i)*10}px`}}><Panel dark style={{padding:34,height:260}}><div style={{fontFamily:MONO,fontSize:24,color:C.mint,marginBottom:40}}>{name}<span style={{float:'right',color:'#737F75'}}>●</span></div><div style={{fontSize:32,marginBottom:38}}>{q}</div><div style={{fontFamily:MONO,fontSize:18,color:'#929F94'}}>{foot}<span style={{opacity:Math.sin(t*3)>0?1:.25}}> _</span></div></Panel></Reveal>)}
    </div>
  </Frame>;
};
