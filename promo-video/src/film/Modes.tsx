import {C, Frame, Headline, Panel, Reveal, Subnote, useSeconds} from './design';

export const Modes = () => {
 const t=useSeconds();
 return <Frame chapter="08 / YOUR WAY TO CONNECT" duration={17}>
  <Headline wide label="选择适合团队的运行方式" lines={['在你的节奏里，协作。']} body="从自己的电脑开始，也可以部署完整的团队工作台。"/>
  <Reveal delay={1} style={{position:'absolute',left:112,top:535,width:810}}><Panel style={{padding:42,height:310,borderColor:t<8?'#7C9B86':C.line}}><div style={{fontSize:24,color:'#64806A',marginBottom:27}}>P2P 空间</div><div style={{fontSize:40,marginBottom:30}}>从一台主机，连接队友。</div><div style={{fontSize:27,lineHeight:1.65,color:C.muted}}>主要通过 agent 协作<br/>可选本机只读看板 · 主机需要保持开机</div></Panel></Reveal>
  <Reveal delay={5} style={{position:'absolute',left:965,top:535,width:840}}><Panel style={{padding:42,height:310,borderColor:t>=8?'#7C9B86':C.line}}><div style={{fontSize:24,color:'#64806A',marginBottom:27}}>自托管团队服务</div><div style={{fontSize:40,marginBottom:30}}>让项目，有一个工作台。</div><div style={{fontSize:27,lineHeight:1.65,color:C.muted}}>账号、多项目与网页管理<br/>任务 · 协作 · 上下文 · 交付 · 成员</div></Panel></Reveal>
  <Subnote>两种运行方式，共用协作核心。</Subnote>
 </Frame>;
};
