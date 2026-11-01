import type {CSSProperties, ReactNode} from 'react';
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';

export const C = {paper: '#F4F3EE', ink: '#202124', muted: '#70746F', mint: '#B7DCC7', line: '#D5D8D1', slate: '#A7B8D0'};
export const FONT = '"Microsoft YaHei UI", "Microsoft YaHei", sans-serif';
export const MONO = '"Cascadia Code", Consolas, monospace';
export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
export const ease = Easing.bezier(0.16, 1, 0.3, 1);
export const enter = (t: number, delay = 0, duration = 1) => interpolate(t, [delay, delay + duration], [0, 1], {...clamp, easing: ease});
export const useSeconds = () => {const frame = useCurrentFrame(); const {fps} = useVideoConfig(); return frame / fps;};

export const Reveal = ({children, delay = 0, style}: {children: ReactNode; delay?: number; style?: CSSProperties}) => {
  const t = useSeconds(); const p = enter(t, delay);
  return <div style={{opacity: p, translate: `0px ${(1-p)*40}px`, ...style}}>{children}</div>;
};

export const Logo = ({size = 64}: {size?: number}) => <Img src={staticFile('coopagents-icon.png')} style={{width: size, height: size, borderRadius: size*.24}} />;

export const Frame = ({children, dark = false, chapter, duration, final = false}: {children: ReactNode; dark?: boolean; chapter: string; duration: number; final?: boolean}) => {
  const t = useSeconds();
  const opacity = final ? enter(t, 0, .7) : interpolate(t, [0, .6, duration-.5, duration], [0, 1, 1, 0], clamp);
  return <AbsoluteFill style={{background: dark ? C.ink : C.paper, color: dark ? C.paper : C.ink, fontFamily: FONT, overflow: 'hidden'}}>
    <AbsoluteFill style={{opacity: .05, backgroundImage: `radial-gradient(${dark ? '#FFFFFF' : '#202124'} 1px,transparent 1px)`, backgroundSize: '32px 32px', translate: `${Math.sin(t/7)*5}px ${Math.cos(t/9)*5}px`}} />
    <AbsoluteFill style={{opacity}}>
      <div style={{position: 'absolute', left: 110, top: 76, display: 'flex', alignItems: 'center', gap: 18}}><Logo size={52}/><span style={{fontFamily: 'Segoe UI, sans-serif', fontSize: 28, fontWeight: 600, letterSpacing: -.7}}>Coopagents</span></div>
      <div style={{position: 'absolute', right: 112, top: 91, fontSize: 19, fontFamily: MONO, letterSpacing: 2, color: dark ? '#919992' : C.muted}}>{chapter}</div>
      {children}
      <div style={{position: 'absolute', left: 112, bottom: 66, fontSize: 18, fontFamily: MONO, color: dark ? '#9BA29B' : C.muted}}>独立思考 · 同频协作</div>
      <div style={{position: 'absolute', right: 112, bottom: 72, width: 150, height: 2, background: dark ? '#505550' : C.line}}><div style={{width: `${Math.min(1,t/duration)*100}%`, height: '100%', background: dark ? C.mint : C.ink}}/></div>
    </AbsoluteFill>
  </AbsoluteFill>;
};

export const Headline = ({label, lines, body, dark = false, wide = false}: {label: string; lines: string[]; body: string; dark?: boolean; wide?: boolean}) => <div style={{position: 'absolute', left: 112, top: 250, width: wide ? 1550 : 790}}>
  <Reveal><div style={{fontFamily: MONO, color: dark ? C.mint : '#52665B', fontSize: 23, letterSpacing: 2, marginBottom: 33}}>{label}</div></Reveal>
  {lines.map((line,i)=><Reveal key={line} delay={.15+i*.16}><div style={{fontSize: 100, fontWeight: 650, lineHeight: 1.26, letterSpacing: -3}}>{line}</div></Reveal>)}
  <Reveal delay={.6}><div style={{fontSize: 33, lineHeight: 1.65, marginTop: 33, color: dark ? '#C2C9C0' : '#656B65', whiteSpace: 'pre-line'}}>{body}</div></Reveal>
</div>;

export const Panel = ({children, dark = false, style}: {children: ReactNode; dark?: boolean; style?: CSSProperties}) => <div style={{boxSizing: 'border-box', background: dark ? '#292D2B' : '#FCFCF8', border: `1px solid ${dark ? '#515851' : '#D8DCD4'}`, borderRadius: 24, boxShadow: dark ? '0 30px 60px #00000015' : '0 28px 65px #20212409', ...style}}>{children}</div>;

export const Subnote = ({children, dark = false}: {children: ReactNode; dark?: boolean}) => <div style={{position: 'absolute', left: 112, right: 112, bottom: 132, fontSize: 23, color: dark ? '#9AA99E' : '#70776E'}}>{children}</div>;

export const Orbit = ({dark = false, size = 850}: {dark?: boolean; size?: number}) => {
  const t = useSeconds();
  return <svg viewBox="0 0 900 900" width={size} height={size} style={{overflow: 'visible'}}>
    {Array.from({length: 7},(_,i)=><ellipse key={i} cx={450} cy={450} rx={300} ry={105+i*22} fill="none" stroke={dark ? '#B9CEC1' : '#72927F'} strokeWidth={1.3} opacity={.16+i*.04} transform={`rotate(${i*24+t*2} 450 450)`} />)}
    {Array.from({length: 8},(_,i)=>{const a=t*(.12+i*.008)+i*Math.PI/4; const x=450+Math.cos(a)*310; const y=450+Math.sin(a)*260; return <g key={i}><circle cx={x} cy={y} r={11} fill={i%3===0 ? C.mint : dark ? '#E9EDE7' : C.ink}/><circle cx={x} cy={y} r={22+Math.sin(t*2+i)*5} fill="none" stroke={dark ? C.mint : C.muted} opacity={.22}/></g>;})}
    <circle cx={450} cy={450} r={93} fill={dark ? '#353C36' : '#E2E7DE'} opacity={.7}/>
    <circle cx={450} cy={450} r={112} fill="none" stroke={dark ? C.mint : '#8B9F91'} opacity={.4}/>
  </svg>;
};
