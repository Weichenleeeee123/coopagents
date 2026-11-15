import {Img, staticFile} from 'remotion';

export const EnglishWorkbench=({frame}:{frame:number})=> <div style={{width:1510,height:720,borderRadius:18,overflow:'hidden',boxShadow:'0 35px 90px #0008',background:'#F7F9F5',color:'#202820',display:'flex',fontFamily:'Segoe UI, sans-serif'}}>
 <div style={{width:235,flexShrink:0,background:'#EDF1E9',borderRight:'1px solid #DAE2D4',padding:'30px 23px',boxSizing:'border-box'}}>
  <div style={{display:'flex',alignItems:'center',gap:13,fontSize:23,fontWeight:650}}><Img src={staticFile('coopagents-icon.png')} style={{width:35,height:35,borderRadius:9}}/>Coopagents</div>
  <div style={{margin:'42px 0 27px',padding:17,border:'1px solid #CDD8C6',borderRadius:12,fontSize:20}}>Atlas Workspace</div>
  {['Overview','Tasks','Collaboration','Shared context','Delivery','Members & agents'].map((label,i)=><div key={label} style={{fontSize:20,padding:'17px 12px',marginBottom:5,borderRadius:8,color:i===1?'#25341E':'#72816A',background:i===1?'#DCE5D4':'transparent',fontWeight:i===1?600:400}}>{label}</div>)}
 </div>
 <div style={{flex:1,padding:'32px 39px',position:'relative',overflow:'hidden'}}>
  <div style={{fontSize:18,color:'#7C8B72'}}>Atlas / Workspace / Tasks</div>
  <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginTop:30}}><div><div style={{fontSize:45,fontWeight:650}}>Tasks</div><div style={{fontSize:21,marginTop:9,color:'#7A896F'}}>Who owns the work. What happens next.</div></div><div style={{background:'#273923',color:'#FFF',padding:'14px 22px',borderRadius:10,fontSize:20}}>+ New task</div></div>
  <div style={{marginTop:29,borderBottom:'1px solid #D4DDCC',paddingBottom:18,fontSize:20,color:'#526849'}}>Board&nbsp;&nbsp;&nbsp;&nbsp;List</div>
  <div style={{display:'flex',gap:25,marginTop:28,transform:`translateY(${-Math.sin(frame/130)*4}px)`}}>
   {[
    {name:'Unclaimed',title:'Add API examples',owner:'Ready to claim',color:'#8C9C82'},
    {name:'In progress',title:'Login integration',owner:'Alice / Claude Code',color:'#5B8148'},
    {name:'Review',title:'Confirm delivery links',owner:'Mia / Codex',color:'#BA9851'},
   ].map((column,i)=><div key={column.name} style={{flex:1,minWidth:0}}><div style={{fontSize:22,fontWeight:600,borderBottom:`3px solid ${column.color}`,paddingBottom:14}}>{column.name} <span style={{color:'#83917B',fontSize:17}}>1</span></div><div style={{marginTop:18,padding:24,borderRadius:13,border:`1px solid ${i===1?'#9DBD87':'#D7E0D0'}`,background:i===1?'#EEF7E7':'white',boxShadow:'0 10px 20px #27392306',minHeight:210,boxSizing:'border-box'}}><div style={{fontFamily:'Consolas, monospace',fontSize:17,color:'#829176'}}>DEMO / 0{i+1}</div><div style={{fontSize:24,fontWeight:600,marginTop:20}}>{column.title}</div><div style={{fontSize:18,color:'#758B68',marginTop:19,lineHeight:1.55}}>{i===1?'Interface aligned. Adding tests.':'Shared project work.'}</div><div style={{borderTop:'1px solid #D7E2CE',paddingTop:16,marginTop:24,fontSize:18,color:'#6A7E5F'}}>{column.owner}</div></div></div>)}
  </div>
  <div style={{position:'absolute',right:30,bottom:24,padding:'9px 15px',borderRadius:22,fontSize:17,background:'#DDE8D5',color:'#57724A'}}>Self-hosted workbench / UI illustration</div>
 </div>
</div>;
