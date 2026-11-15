import {useLayoutEffect,useRef} from 'react';
import {AbsoluteFill,staticFile,useCurrentFrame,useVideoConfig} from 'remotion';
import {Audio} from '@remotion/media';
import {C} from '../story/palette';
import {AUDIO_ENVELOPE} from '../motion/audio-envelope';
import {drawCraft} from './craftDrawing';

export const CraftTest=()=>{
 const frame=useCurrentFrame();
 const {fps}=useVideoConfig();
 const canvas=useRef<HTMLCanvasElement>(null);
 const energy=AUDIO_ENVELOPE[Math.min(AUDIO_ENVELOPE.length-1,frame)]?.[0]??0;
 useLayoutEffect(()=>{
  const context=canvas.current?.getContext('2d');
  if(context)drawCraft(context,frame/60,energy);
 },[frame,energy]);
 return <AbsoluteFill style={{background:C.paper,overflow:'hidden'}}>
  <canvas ref={canvas} width={1920} height={1080} style={{width:'100%',height:'100%'}}/>
  <Audio src={staticFile('funk-caravan-ad54.m4a')} name="Funk Caravan / craft test" volume={.85} premountFor={fps}/>
 </AbsoluteFill>;
};
