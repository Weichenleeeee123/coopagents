import {
  AbsoluteFill,
  Composition,
  Easing,
  Audio,
  Img,
  interpolate,
  Series,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

const COLORS = {
  ink: "#202124",
  paper: "#F7F7F3",
  mist: "#D9DBD7",
  mint: "#B8E6D0",
  cobalt: "#6F87FF",
  coral: "#F5B6A4",
  white: "#FFFFFF",
};

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

const Copy = ({ eyebrow, title, body, dark = false }: { eyebrow: string; title: string; body?: string; dark?: boolean }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rise = interpolate(frame, [0, 1.1 * fps], [26, 0], { ...clamp, easing: Easing.bezier(0.16, 1, 0.3, 1) });
  const opacity = interpolate(frame, [0, 0.8 * fps], [0, 1], clamp);
  return (
    <div style={{ position: "absolute", left: 110, right: 110, top: 130, opacity, translate: `0px ${rise}px`, color: dark ? COLORS.paper : COLORS.ink }}>
      <div style={{ fontFamily: "Microsoft YaHei UI, Microsoft YaHei, sans-serif", letterSpacing: 0, fontSize: 24, fontWeight: 700, textTransform: "uppercase", color: dark ? COLORS.mint : COLORS.cobalt }}>{eyebrow}</div>
      <div style={{ marginTop: 28, fontFamily: "Microsoft YaHei UI, Microsoft YaHei, sans-serif", fontSize: 88, lineHeight: 1.12, fontWeight: 700, letterSpacing: 0, maxWidth: 980, whiteSpace: "pre-line" }}>{title}</div>
      {body && <div style={{ marginTop: 34, fontFamily: "Microsoft YaHei, sans-serif", fontSize: 36, lineHeight: 1.45, maxWidth: 800, whiteSpace: "pre-line", color: dark ? "#D6D8D2" : "#54565A" }}>{body}</div>}
    </div>
  );
};

const Grid = ({ dark = false }: { dark?: boolean }) => (
  <AbsoluteFill style={{ opacity: 0.045, backgroundImage: `linear-gradient(${dark ? "#D9DBD7" : "#202124"} 1px, transparent 1px), linear-gradient(90deg, ${dark ? "#D9DBD7" : "#202124"} 1px, transparent 1px)`, backgroundSize: "100px 100px" }} />
);

const LogoMark = ({ size = 180 }: { size?: number }) => {
  const frame = useCurrentFrame();
  const rotation = interpolate(frame, [0, 4 * 30], [-14, 0], { ...clamp, easing: Easing.bezier(0.16, 1, 0.3, 1) });
  const scale = interpolate(frame, [0, 2 * 30], [0.7, 1], { ...clamp, easing: Easing.out(Easing.back(1.2)) });
  return <Img src={staticFile("coopagents-icon.png")} style={{ width: size, height: size, objectFit: "contain", borderRadius: size * 0.22, rotate: `${rotation}deg`, scale }} />;
};

const AgentDiagram = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const dash = interpolate(frame, [0, 2.8 * fps], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const nodes = [
    { x: 88, y: 110, label: "agent A", color: COLORS.cobalt },
    { x: 100, y: 490, label: "agent B", color: COLORS.coral },
    { x: 660, y: 130, label: "shared context", color: COLORS.mint },
    { x: 660, y: 480, label: "your team", color: COLORS.ink },
  ];
  return <div style={{ position: "absolute", left: 930, top: 190, width: 820, height: 650 }}>
    <svg viewBox="0 0 800 620" style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
      <path d="M88 110 C190 110 220 205 330 270" fill="none" stroke={COLORS.cobalt} strokeWidth="4" pathLength="1" strokeDasharray={`${dash} 1`} />
      <path d="M100 490 C210 490 230 395 330 335" fill="none" stroke={COLORS.coral} strokeWidth="4" pathLength="1" strokeDasharray={`${dash} 1`} />
      <path d="M470 270 C555 215 565 140 660 130" fill="none" stroke={COLORS.mint} strokeWidth="4" pathLength="1" strokeDasharray={`${dash} 1`} />
      <path d="M470 335 C560 380 565 470 660 480" fill="none" stroke={COLORS.ink} strokeOpacity="0.5" strokeWidth="4" pathLength="1" strokeDasharray={`${dash} 1`} />
    </svg>
    {nodes.map((node, i) => <div key={node.label} style={{ position: "absolute", left: node.x - 9, top: node.y - 9, display: "flex", alignItems: "center", gap: 15, opacity: interpolate(frame, [8 * i, 16 + 8 * i], [0, 1], clamp) }}>
      <div style={{ width: 22, height: 22, borderRadius: "50%", background: node.color, boxShadow: `0 0 0 10px ${node.color}22` }} />
      <span style={{ whiteSpace: "nowrap", padding: "12px 18px", background: COLORS.paper, border: `1px solid ${COLORS.mist}`, borderRadius: 12, fontFamily: "Arial", fontSize: 22, color: COLORS.ink }}>{node.label}</span>
    </div>)}
    <div style={{ position: "absolute", left: 315, top: 220, width: 160, height: 160, borderRadius: "50%", background: COLORS.paper, border: `1px solid ${COLORS.mist}`, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 18px 70px #20212414" }}><LogoMark size={106} /></div>
  </div>;
};

const Opening = () => {
  const frame = useCurrentFrame();
  const headerX = interpolate(frame, [0, 0.8 * 30], [-20, 0], { ...clamp, easing: Easing.out(Easing.cubic) });
  const headerOpacity = interpolate(frame, [0, 0.7 * 30], [0, 1], clamp);
  return <AbsoluteFill style={{ background: COLORS.paper }}><Grid />
    <div style={{ position: "absolute", left: 120, top: 82, display: "flex", alignItems: "center", gap: 18, opacity: headerOpacity, translate: `${headerX}px 0px` }}><LogoMark size={70} /><span style={{ fontFamily: "Arial", fontSize: 30, fontWeight: 700, color: COLORS.ink }}>Coopagents</span></div>
    <div style={{ position: "absolute", left: 128, top: 320, width: 730 }}><Copy eyebrow="Different agents. One mission." title={"让 agent，\n找到彼此。"} body={"不同工具。不同电脑。\n共享同一件事。"} /></div>
    <AgentDiagram />
    <div style={{ position: "absolute", left: 128, bottom: 78, color: "#6C6E72", fontFamily: "Arial", fontSize: 22 }}>A shared mission control for coding agents</div>
  </AbsoluteFill>;
};

const Friction = () => {
  const frame = useCurrentFrame();
  const shift = interpolate(frame, [0, 2 * 30], [0, -80], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  return <AbsoluteFill style={{ background: COLORS.ink }}><Grid dark /><Copy dark eyebrow="The gap" title="每个人都在工作。" body="上下文却散落在不同会话、不同机器、不同工具里。" /><div style={{ position: "absolute", right: 130, bottom: 130, width: 520, height: 240, border: "1px solid #55585B", borderRadius: 24, opacity: 0.8, translate: `${shift}px 0px` }}><div style={{ padding: 30, fontFamily: "monospace", color: "#B6BBB6", fontSize: 26, lineHeight: 1.7 }}>Claude: “我缺少背景。”<br />Codex: “我不知道决策。”<br />Human: “谁在处理这个？”</div></div></AbsoluteFill>;
};

const Connect = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const dash = interpolate(frame, [0, 4 * fps], [0, 1], clamp);
  return <AbsoluteFill style={{ background: COLORS.paper }}><Grid /><Copy eyebrow="The connection" title="把上下文，放回同一张桌子。" body="Coopagents 通过 MCP，让 agent 发现彼此，交换必要信息，并留下可追溯的协作记录。" /><svg style={{ position: "absolute", left: 90, right: 90, bottom: 80, height: 360, overflow: "visible" }} viewBox="0 0 1200 360"><path d="M80 240 C260 40 420 300 600 140 S920 50 1120 230" fill="none" stroke={COLORS.mist} strokeWidth="6" strokeDasharray="12 20" /><path d="M80 240 C260 40 420 300 600 140 S920 50 1120 230" fill="none" stroke={COLORS.cobalt} strokeWidth="6" pathLength="1" strokeDasharray={`${dash} 1`} /><circle cx="80" cy="240" r="26" fill={COLORS.ink} /><circle cx="600" cy="140" r="26" fill={COLORS.ink} /><circle cx="1120" cy="230" r="26" fill={COLORS.ink} /><text x="42" y="315" fill="#54565A" fontSize="28" fontFamily="Arial">your agent</text><text x="528" y="85" fill="#54565A" fontSize="28" fontFamily="Arial">shared context</text><text x="1025" y="315" fill="#54565A" fontSize="28" fontFamily="Arial">their agent</text></svg></AbsoluteFill>;
};

const Capabilities = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const items = ["共享上下文", "成员与 agent 发现", "直接协作", "任务与交付证据"];
  return <AbsoluteFill style={{ background: COLORS.mist }}><Copy eyebrow="What moves" title="协作变得可见。" body="从一个问题，到一个决定，再到一个交付。" /><div style={{ position: "absolute", left: 110, right: 110, bottom: 118, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>{items.map((item, i) => { const y = interpolate(frame, [i * 8, 1.2 * fps + i * 8], [40, 0], { ...clamp, easing: Easing.out(Easing.cubic) }); const o = interpolate(frame, [i * 8, 0.8 * fps + i * 8], [0, 1], clamp); return <div key={item} style={{ height: 110, background: COLORS.paper, borderRadius: 18, display: "flex", alignItems: "center", padding: "0 30px", fontFamily: "Arial", fontSize: 32, fontWeight: 700, color: COLORS.ink, opacity: o, translate: `0px ${y}px` }}><span style={{ color: [COLORS.cobalt, COLORS.mint, COLORS.coral, COLORS.ink][i], fontSize: 45, marginRight: 18 }}>0{i + 1}</span>{item}</div>; })}</div></AbsoluteFill>;
};

const Proof = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = interpolate(frame, [0, 5 * fps], [0, 1], clamp);
  return <AbsoluteFill style={{ background: COLORS.ink }}><Grid dark /><Copy dark eyebrow="The trace" title="每一步，都能回到证据。" body="任务关联分支、提交、PR 和 release。协作不是一句‘完成了’，而是一条看得见的路径。" /><div style={{ position: "absolute", left: 120, right: 120, bottom: 135, height: 8, background: "#4B4D50", borderRadius: 10 }}><div style={{ width: `${progress * 100}%`, height: "100%", background: COLORS.mint, borderRadius: 10 }} /></div><div style={{ position: "absolute", left: 120, right: 120, bottom: 88, display: "flex", justifyContent: "space-between", fontFamily: "Arial", fontSize: 26, color: "#B6BBB6" }}>{["question", "decision", "task", "commit", "release"].map((label, i) => <span key={label} style={{ color: progress > i / 4 ? COLORS.mint : "#777A7B" }}>{label}</span>)}</div></AbsoluteFill>;
};

const Trust = () => <AbsoluteFill style={{ background: COLORS.paper }}><Grid /><Copy eyebrow="Human control" title="人，保留最后的决定。" body="创建任务、批准约定、接受交接、修改权限——这些决定仍由人掌握。" /><div style={{ position: "absolute", right: 140, bottom: 115, width: 370, height: 370, borderRadius: "50%", border: `4px solid ${COLORS.ink}`, display: "flex", alignItems: "center", justifyContent: "center" }}><div style={{ width: 190, height: 190, borderRadius: "50%", background: COLORS.mint, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Arial", fontWeight: 700, fontSize: 30, textAlign: "center", color: COLORS.ink }}>human<br />in the loop</div></div></AbsoluteFill>;

const Finale = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 1.5 * 30], [0, 1], clamp);
  return <AbsoluteFill style={{ background: COLORS.ink, alignItems: "center", justifyContent: "center", opacity }}><Grid dark /><LogoMark size={230} /><div style={{ marginTop: 42, color: COLORS.paper, fontFamily: "Arial", fontSize: 94, fontWeight: 700, letterSpacing: 0 }}>Coopagents</div><div style={{ marginTop: 20, color: COLORS.mint, fontFamily: "Arial", fontSize: 34, letterSpacing: 0 }}>同频工作。共同交付。</div><div style={{ marginTop: 74, color: "#A5A8A6", fontFamily: "Arial", fontSize: 24 }}>github.com/Weichenleeeee123/coopagents · open source · alpha</div></AbsoluteFill>;
};

const Music = () => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  return <Audio src={staticFile("coopagents-original-score.wav")} volume={interpolate(frame, [0, fps, 179 * fps, 180 * fps], [0, 0.19, 0.19, 0], clamp)} durationInFrames={180 * fps} />;
};

const SceneTransitions = () => {
  const frame = useCurrentFrame();
  const boundaries = [28, 56, 88, 122, 152, 166].map((second) => second * 30);
  const opacity = Math.max(...boundaries.map((at) => interpolate(frame, [at - 8, at, at + 8], [0, 0.9, 0], { ...clamp, easing: Easing.inOut(Easing.cubic) })));
  return <AbsoluteFill style={{ background: COLORS.ink, opacity, pointerEvents: "none" }} />;
};

export const MyComposition = () => <Composition id="CoopagentsPromo" component={PromoVideo} durationInFrames={180 * 30} fps={30} width={1920} height={1080} />;

export const MyComponent: React.FC = () => <PromoVideo />;

const PromoVideo = () => <AbsoluteFill><Series><Series.Sequence durationInFrames={28 * 30} premountFor={30}><Opening /></Series.Sequence><Series.Sequence durationInFrames={28 * 30} premountFor={30}><Friction /></Series.Sequence><Series.Sequence durationInFrames={32 * 30} premountFor={30}><Connect /></Series.Sequence><Series.Sequence durationInFrames={34 * 30} premountFor={30}><Capabilities /></Series.Sequence><Series.Sequence durationInFrames={30 * 30} premountFor={30}><Proof /></Series.Sequence><Series.Sequence durationInFrames={14 * 30} premountFor={30}><Trust /></Series.Sequence><Series.Sequence durationInFrames={14 * 30} premountFor={30}><Finale /></Series.Sequence></Series><SceneTransitions /><Music /></AbsoluteFill>;
