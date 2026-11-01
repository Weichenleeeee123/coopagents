import {C, Frame, Logo, Orbit, Reveal} from './design';

export const Closing = () => <Frame dark final chapter="10 / COOPAGENTS · 同频" duration={15}>
  <div style={{position:'absolute',left:535,top:20,opacity:.2}}><Orbit dark/></div>
  <div style={{position:'absolute',inset:0,display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center'}}>
    <Reveal><Logo size={155}/></Reveal>
    <Reveal delay={.3}><div style={{fontFamily:'Segoe UI, sans-serif',fontSize:112,fontWeight:600,letterSpacing:-5,marginTop:24}}>Coopagents</div></Reveal>
    <Reveal delay={1}><div style={{fontSize:48,marginTop:30,color:C.mint}}>同频工作，共同交付。</div></Reveal>
    <Reveal delay={5}><div style={{fontSize:29,marginTop:52}}>让你的 agent，认识你的团队。</div></Reveal>
    <Reveal delay={7}><div style={{fontFamily:'Consolas, monospace',fontSize:24,color:'#ABB8AD',marginTop:30}}>github.com/Weichenleeeee123/coopagents</div></Reveal>
    <Reveal delay={9}><div style={{fontSize:20,letterSpacing:3,color:'#87968B',marginTop:28}}>OPEN SOURCE / ALPHA</div></Reveal>
  </div>
</Frame>;
