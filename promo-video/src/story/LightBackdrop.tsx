import {C} from './palette';

export const LightBackdrop=({globalFrame,hero=false}:{globalFrame:number;hero?:boolean})=>{
 const t=globalFrame/60;
 return <svg viewBox="0 0 1920 1080" style={{position:'absolute',inset:0,width:'100%',height:'100%'}}>
  <defs><radialGradient id="mint-air"><stop stopColor={C.mint} stopOpacity={hero?.6:.34}/><stop offset="1" stopColor={C.mint} stopOpacity="0"/></radialGradient><radialGradient id="blue-air"><stop stopColor={C.sky} stopOpacity=".85"/><stop offset="1" stopColor={C.sky} stopOpacity="0"/></radialGradient></defs>
  <rect width="1920" height="1080" fill={C.paper}/>
  <ellipse cx={310+Math.sin(t*.11)*120} cy={890+Math.cos(t*.13)*60} rx="740" ry="590" fill="url(#mint-air)"/>
  <ellipse cx={1690+Math.cos(t*.09)*70} cy={150+Math.sin(t*.12)*100} rx="760" ry="640" fill="url(#blue-air)"/>
  {[0,1,2,3].map(i=><path key={i} d={`M ${-150+i*45} 1080 C ${180+i*70} ${610-i*22}, ${1580+i*30} ${1210-i*30}, 2080 ${80+i*50}`} stroke={i%2?C.blue:C.green} opacity={hero?.1:.045} strokeWidth={1.3} fill="none"/>) }
  {hero?<g>{[0,1,2,3,4].map(i=><ellipse key={i} cx="960" cy="410" rx={265+i*21} ry={150+i*14} fill="none" stroke={i%2?C.blue:C.green} strokeWidth="1.8" opacity=".15" transform={`rotate(${i*28+t*9} 960 410)`}/>)}{[0,1,2].map(i=>{const a=t*.55+i*Math.PI*2/3;const x=960+Math.cos(a)*340,y=410+Math.sin(a)*230;return <g key={i}><circle cx={x} cy={y} r="13" fill={[C.blue,C.orange,C.green][i]}/><circle cx={x} cy={y} r="25" fill="none" stroke={[C.blue,C.orange,C.green][i]} opacity=".2"/></g>;})}</g>:null}
 </svg>;
};
