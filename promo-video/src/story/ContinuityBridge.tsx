import {useCurrentFrame} from 'remotion';
import {C} from './palette';
import {EASE} from './motion';
import shots from './shots.json';

type Transfer={at:number;label:string;from:[number,number];to:[number,number];color:string;shape:'chip'|'invite'};
const transfers:Transfer[]=[
 {at:7,label:'Coopagents',from:[960,510],to:[490,335],color:C.mint,shape:'chip'},
 {at:10,label:'Atlas invite',from:[1430,605],to:[470,605],color:C.coral,shape:'invite'},
 {at:14,label:'status?',from:[820,380],to:[930,465],color:C.sky,shape:'chip'},
 {at:15,label:'status?',from:[1270,480],to:[600,385],color:C.sky,shape:'chip'},
 {at:17,label:'status',from:[690,530],to:[600,425],color:C.mint,shape:'chip'},
 {at:18,label:'status',from:[670,515],to:[1270,460],color:C.mint,shape:'chip'},
 {at:19,label:'status',from:[780,385],to:[970,560],color:C.mint,shape:'chip'},
 {at:20,label:'login.ts',from:[1100,540],to:[485,500],color:C.lavender,shape:'chip'},
 {at:24,label:'login.ts',from:[1110,525],to:[1400,480],color:C.lavender,shape:'chip'},
 {at:25,label:'Login integration',from:[540,480],to:[1110,460],color:C.sky,shape:'chip'},
];
export const ContinuityBridge=()=>{
 const frame=useCurrentFrame();const transfer=transfers.find(item=>frame>=shots[item.at].start-18&&frame<=shots[item.at].start+34);
 if(!transfer)return null;
 const age=frame-shots[transfer.at].start;const q=EASE((age+18)/52);const arch=Math.sin(q*Math.PI);
 const x=transfer.from[0]+(transfer.to[0]-transfer.from[0])*q;const y=transfer.from[1]+(transfer.to[1]-transfer.from[1])*q-arch*155;
 const alpha=EASE((age+18)/10)*(1-EASE((age-23)/11));
 return <div style={{position:'absolute',inset:0,pointerEvents:'none',zIndex:30,opacity:alpha}}>
  <svg viewBox="0 0 1920 1080" width={1920} height={1080}><path d={`M${transfer.from.join(' ')} Q${(transfer.from[0]+transfer.to[0])/2} ${Math.min(transfer.from[1],transfer.to[1])-210} ${transfer.to.join(' ')}`} fill="none" stroke={transfer.color===C.coral?C.orange:C.blue} strokeWidth="3" strokeDasharray="5 11" opacity=".27"/></svg>
  <div style={{position:'absolute',left:x-150,top:y-42,width:300,height:84,display:'flex',alignItems:'center',justifyContent:'center',borderRadius:transfer.shape==='invite'?18:42,background:transfer.color,color:C.ink,font:'600 29px "Cascadia Code",Consolas,monospace',boxShadow:'0 24px 50px #20212420',border:'1px solid #FFFFFF',transform:`rotate(${Math.sin(q*Math.PI*2)*8}deg) scale(${1+arch*.11})`}}>{transfer.shape==='invite'?'↗  ':''}{transfer.label}</div>
 </div>;
};
