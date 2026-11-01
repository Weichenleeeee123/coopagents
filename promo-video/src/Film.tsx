import {AbsoluteFill, Audio, Series, staticFile, useVideoConfig} from 'remotion';
import {Opening} from './film/Opening';
import {Friction} from './film/Friction';
import {Connection} from './film/Connection';
import {Context} from './film/Context';
import {Dialogue} from './film/Dialogue';
import {Tasks} from './film/Tasks';
import {Evidence} from './film/Evidence';
import {Modes} from './film/Modes';
import {Control} from './film/Control';
import {Closing} from './film/Closing';

export const Film = () => {
 const {fps}=useVideoConfig();
 return <AbsoluteFill style={{background:'#202124'}}>
  <Series>
   <Series.Sequence name="01 · 不同的 agent，同一件事" durationInFrames={15*fps} premountFor={fps}><Opening/></Series.Sequence>
   <Series.Sequence name="02 · 上下文的距离" durationInFrames={18*fps} premountFor={fps}><Friction/></Series.Sequence>
   <Series.Sequence name="03 · 通过 MCP 建立连接" durationInFrames={20*fps} premountFor={fps}><Connection/></Series.Sequence>
   <Series.Sequence name="04 · 共享上下文" durationInFrames={20*fps} premountFor={fps}><Context/></Series.Sequence>
   <Series.Sequence name="05 · 直接提问与回复" durationInFrames={20*fps} premountFor={fps}><Dialogue/></Series.Sequence>
   <Series.Sequence name="06 · 任务与依赖" durationInFrames={20*fps} premountFor={fps}><Tasks/></Series.Sequence>
   <Series.Sequence name="07 · 交付与证据" durationInFrames={20*fps} premountFor={fps}><Evidence/></Series.Sequence>
   <Series.Sequence name="08 · 两种运行方式" durationInFrames={17*fps} premountFor={fps}><Modes/></Series.Sequence>
   <Series.Sequence name="09 · 由人掌握决定" durationInFrames={15*fps} premountFor={fps}><Control/></Series.Sequence>
   <Series.Sequence name="10 · 同频工作，共同交付" durationInFrames={15*fps} premountFor={fps}><Closing/></Series.Sequence>
  </Series>
  <Audio name="同频 / original score" src={staticFile('coopagents-original-score.wav')} volume={.8}/>
 </AbsoluteFill>;
};
