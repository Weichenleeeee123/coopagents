import {C, Frame, Headline, Logo, Orbit, Reveal, useSeconds} from './design';

export const Opening = () => {
  const t = useSeconds();
  return <Frame chapter="01 / A SHARED FREQUENCY" duration={15}>
    <Headline label="让独立的智能，开始协作" lines={['不同的 agent。','同一件事。']} body={'让不同工具、不同电脑里的 coding agent\n共享上下文，找到彼此。'} />
    <Reveal delay={.3} style={{position: 'absolute', right: 25, top: 130}}><Orbit/><div style={{position: 'absolute', left: 352, top: 352, scale: 1+Math.sin(t)*.02}}><Logo size={146}/></div></Reveal>
    <Reveal delay={6} style={{position: 'absolute', left: 118, top: 808, display: 'flex', alignItems: 'center', gap: 14, color: '#52665B', fontSize: 25}}><span style={{width: 9,height: 9,background:C.ink,borderRadius:'50%'}}/>保留你的工具，连接你的团队。</Reveal>
  </Frame>;
};
