import {useLayoutEffect, useRef} from 'react';
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {AUDIO_ENVELOPE} from './audio-envelope';
import {drawMotion, PALETTE} from './renderer';
import {OFFSETS} from './timing';

const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
const words=['Coopagents','各自强大','找到彼此','共享上下文','直接协作','并行推进','有据可循','同频','由你决定','Coopagents'];
export const MotionStage=({mode}:{mode:number})=>{
 const canvas=useRef<HTMLCanvasElement>(null);const frame=useCurrentFrame();const {fps}=useVideoConfig();const t=frame/fps;
 const globalFrame=Math.min(AUDIO_ENVELOPE.length-1,Math.max(0,OFFSETS[mode]+Math.round(t*60)));
 const [low,energy,high]=AUDIO_ENVELOPE[globalFrame]??[0,0,0];
 useLayoutEffect(()=>{const context=canvas.current?.getContext('2d');if(context)drawMotion(context,mode,t,low,energy,high);},[mode,t,low,energy,high]);
 const dark=[0,2,4,6,7,9].includes(mode);const titleStart=mode===0?2.2:mode===9?4.1:1;
 const titleOpacity=mode===9?interpolate(t,[titleStart,titleStart+.6],[0,1],clamp):interpolate(t,[titleStart,titleStart+.4,titleStart+2.4,titleStart+2.8],[0,1,1,0],clamp);
 const titleY=interpolate(t,[titleStart,titleStart+.65],[110,0],{...clamp,easing:Easing.bezier(.16,1,.3,1)});
 const brand=mode===0||mode===9;
 return <AbsoluteFill style={{overflow:'hidden',background:dark?PALETTE.ink:PALETTE.paper}}>
  <canvas ref={canvas} width={1920} height={1080} style={{position:'absolute',inset:0,width:'100%',height:'100%'}}/>
  <div style={{position:'absolute',left:brand?0:116,right:brand?0:undefined,top:brand?710:104,textAlign:brand?'center':'left',overflow:'hidden',height:brand?210:160}}><div style={{color:dark?PALETTE.paper:PALETTE.ink,fontFamily:'"Segoe UI", "Microsoft YaHei UI", sans-serif',fontSize:brand?160:98,fontWeight:650,letterSpacing:brand?-8:-3,lineHeight:1.15,opacity:titleOpacity,translate:`0px ${titleY}px`,textShadow:dark?'0 3px 30px #00000035':'none'}}>{words[mode]}</div></div>
  {mode===9?<>
   <div style={{position:'absolute',left:0,right:0,top:400,textAlign:'center',opacity:interpolate(t,[3,4],[0,1],clamp),scale:interpolate(t,[3,4.8],[.5,1],{...clamp,easing:Easing.bezier(.16,1,.3,1)})}}><Img src={staticFile('coopagents-icon.png')} style={{width:210,height:210,borderRadius:48}}/></div>
   <div style={{position:'absolute',left:0,right:0,top:905,textAlign:'center',fontFamily:'"Microsoft YaHei UI",sans-serif',fontSize:40,color:PALETTE.lime,opacity:interpolate(t,[6,6.6],[0,1],clamp)}}>同频协作 · 共同交付</div>
   <div style={{position:'absolute',left:0,right:0,bottom:53,textAlign:'center',fontFamily:'Consolas,monospace',fontSize:23,color:'#ACB99E',opacity:interpolate(t,[8.2,8.8],[0,1],clamp)}}>github.com/Weichenleeeee123/coopagents</div>
  </>:null}
 </AbsoluteFill>;
};
