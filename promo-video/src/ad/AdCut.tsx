import {useLayoutEffect,useRef} from 'react';
import {AbsoluteFill,Img,Sequence,staticFile,useCurrentFrame,useVideoConfig} from 'remotion';
import {Audio} from '@remotion/media';
import {C} from '../story/palette';
import {AUDIO_ENVELOPE} from '../motion/audio-envelope';
import plan from './plan.json';
import {drawAd} from './drawingV2';

const fade=(n:number)=>Math.max(0,Math.min(1,n));
export const AdScene=({scene}:{scene:number})=>{
 const frame=useCurrentFrame();const canvas=useRef<HTMLCanvasElement>(null);const item=plan[scene];
 const local=Math.min(frame,item.duration-1);const energy=AUDIO_ENVELOPE[Math.max(0,Math.min(7761,item.start+local))]?.[0]??0;
 useLayoutEffect(()=>{const context=canvas.current?.getContext('2d');if(context)drawAd(context,scene,local,energy);},[scene,local,energy]);
 const opacity=(scene===0?1:fade(frame/12))*(1-fade((frame-item.duration)/12));
 return <AbsoluteFill style={{opacity,transform:`translateX(${(1-fade(frame/12))*30-fade((frame-item.duration)/12)*30}px)`}}>
  <canvas ref={canvas} width={1920} height={1080} style={{width:'100%',height:'100%'}}/>
  {scene===7?<Img src={staticFile('coopagents-icon.png')} style={{position:'absolute',left:840,top:230,width:240,height:240,borderRadius:56,opacity:fade(frame/40),transform:`scale(${.85+.15*fade(frame/50)})`,boxShadow:'0 22px 65px #20212416'}}/>:null}
 </AbsoluteFill>;
};

export const AdCut=()=>{
 const {fps}=useVideoConfig();const frame=useCurrentFrame();
 return <AbsoluteFill style={{background:C.paper,overflow:'hidden'}}>
  <AbsoluteFill style={{background:`radial-gradient(ellipse at ${15+Math.sin(frame/400)*5}% 87%, #C5EDDF55, transparent 51%), radial-gradient(ellipse at 90% 13%, #E7EEFF99, transparent 46%)`}}/>
  <Sequence durationInFrames={432} name="01 / The human relay" premountFor={fps}><AdScene scene={0}/></Sequence>
  <Sequence from={420} durationInFrames={432} name="02 / Connect agents and devices" premountFor={fps}><AdScene scene={1}/></Sequence>
  <Sequence from={840} durationInFrames={432} name="03 / Across regions" premountFor={fps}><AdScene scene={2}/></Sequence>
  <Sequence from={1260} durationInFrames={432} name="04 / Ask, answer, source" premountFor={fps}><AdScene scene={3}/></Sequence>
  <Sequence from={1680} durationInFrames={432} name="05 / An answer becomes code" premountFor={fps}><AdScene scene={4}/></Sequence>
  <Sequence from={2100} durationInFrames={372} name="06 / Linked delivery, human control" premountFor={fps}><AdScene scene={5}/></Sequence>
  <Sequence from={2460} durationInFrames={432} name="07 / Less relaying, more building" premountFor={fps}><AdScene scene={6}/></Sequence>
  <Sequence from={2880} durationInFrames={360} name="08 / Coopagents" premountFor={fps}><AdScene scene={7}/></Sequence>
  <Audio src={staticFile('funk-caravan-ad54.m4a')} name="Funk Caravan / 54 seconds / 3-second fade" volume={.85} premountFor={fps}/>
 </AbsoluteFill>;
};
