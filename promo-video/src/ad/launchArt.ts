// Art-directed, frame-addressable sets. All content and people are illustrative.
type G = CanvasRenderingContext2D;
type P = { x: number; y: number };
export const INK = "#202124";
const PAPER = "#F7F8FA",
  BLUE = "#456FE5",
  CORAL = "#CA6C4D",
  GREEN = "#278565",
  MINT = "#C5EDDF";
const FONT = '"Segoe UI Variable Display","Segoe UI",sans-serif';
const MONO = '"Cascadia Code",Consolas,monospace';
const TAU = Math.PI * 2;
export const sat = (v: number) => Math.max(0, Math.min(1, v));
const ramp = (t: number, a: number, b: number) => sat((t - a) / (b - a));
const ease = (v: number) => {
  const p = sat(v);
  return p < 0.5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2;
};
const out = (v: number) => 1 - (1 - sat(v)) ** 4;
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
function fill(
  g: G,
  x: number,
  y: number,
  w: number,
  h: number,
  c: string | CanvasGradient,
  r = 0,
) {
  g.fillStyle = c;
  g.beginPath();
  g.roundRect(x, y, w, h, r);
  g.fill();
}
function disc(g: G, x: number, y: number, r: number, c: string) {
  g.fillStyle = c;
  g.beginPath();
  g.arc(x, y, r, 0, TAU);
  g.fill();
}
function line(g: G, p: P[], c: string, w = 2) {
  g.strokeStyle = c;
  g.lineWidth = w;
  g.lineCap = "round";
  g.lineJoin = "round";
  g.beginPath();
  p.forEach((v, i) => (i ? g.lineTo(v.x, v.y) : g.moveTo(v.x, v.y)));
  g.stroke();
}
function word(
  g: G,
  s: string,
  x: number,
  y: number,
  size: number,
  c = INK,
  weight = 650,
  align: CanvasTextAlign = "left",
  font = FONT,
) {
  g.fillStyle = c;
  g.font = `${weight} ${size}px ${font}`;
  g.textAlign = align;
  g.textBaseline = "middle";
  g.fillText(s, x, y);
}
function boundary(
  g: G,
  x: number,
  y: number,
  w: number,
  h: number,
  r = 18,
  c = "#DCE0E5",
) {
  g.strokeStyle = c;
  g.lineWidth = 1.5;
  g.beginPath();
  g.roundRect(x, y, w, h, r);
  g.stroke();
}
function cast(g: G, x: number, y: number, rx: number, ry: number, a = 0.15) {
  const gr = g.createRadialGradient(x, y, 0, x, y, rx);
  gr.addColorStop(0, `rgba(38,47,66,${a})`);
  gr.addColorStop(1, "rgba(38,47,66,0)");
  g.save();
  g.translate(x, y);
  g.scale(1, ry / rx);
  g.fillStyle = gr;
  g.translate(-x, -y);
  g.fillRect(x - rx, y - rx, rx * 2, rx * 2);
  g.restore();
}
function sheet(
  g: G,
  x: number,
  y: number,
  w: number,
  h: number,
  r = 22,
  c = "#FFFFFF",
) {
  g.save();
  g.shadowColor = "#28354A20";
  g.shadowBlur = 48;
  g.shadowOffsetY = 23;
  fill(g, x, y, w, h, c, r);
  g.restore();
  boundary(g, x, y, w, h, r, "#FFFFFF");
}
function tick(g: G, x: number, y: number, s: number, c = GREEN, p = 1) {
  line(
    g,
    [
      { x: x - s * 0.4, y },
      { x: x - s * 0.08, y: y + s * 0.3 },
      { x: x + s * 0.47, y: y - s * 0.4 },
    ].slice(0, p > 0.5 ? 3 : 2),
    c,
    s * 0.11,
  );
}
function badge(g: G, x: number, y: number, name: string, c: string, size = 1) {
  g.save();
  g.translate(x, y);
  g.scale(size, size);
  fill(g, -34, -34, 68, 68, c, 18);
  word(
    g,
    name === "Claude Code" ? "C" : "_>",
    0,
    0,
    name === "Claude Code" ? 40 : 29,
    "#FFFFFF",
    700,
    "center",
  );
  word(g, name, 52, 1, 26, INK, 650);
  g.restore();
}
function cursor(g: G, x: number, y: number, s = 1, label = "YOU") {
  g.save();
  g.translate(x, y);
  g.scale(s, s);
  g.shadowColor = "#20212428";
  g.shadowBlur = 15;
  g.shadowOffsetY = 8;
  g.beginPath();
  g.moveTo(0, 0);
  g.lineTo(0, 71);
  g.lineTo(18, 53);
  g.lineTo(32, 82);
  g.lineTo(47, 74);
  g.lineTo(32, 46);
  g.lineTo(58, 43);
  g.closePath();
  g.fillStyle = INK;
  g.fill();
  g.shadowBlur = 0;
  g.shadowOffsetY = 0;
  g.strokeStyle = "#FFFFFF";
  g.lineWidth = 3;
  g.stroke();
  if (label) {
    fill(g, 52, 80, 96, 37, INK, 18);
    word(g, label, 100, 99, 18, "#FFFFFF", 700, "center");
  }
  g.restore();
}
function packet(
  g: G,
  x: number,
  y: number,
  label: string,
  c: string,
  scale = 1,
  rot = 0,
) {
  g.save();
  g.translate(x, y);
  g.rotate(rot);
  g.scale(scale, scale);
  g.shadowColor = c + "32";
  g.shadowBlur = 35;
  g.shadowOffsetY = 18;
  const gr = g.createLinearGradient(-210, -50, 210, 50);
  gr.addColorStop(0, c);
  gr.addColorStop(
    1,
    c === BLUE ? "#7697F3" : c === GREEN ? "#50A889" : "#E49878",
  );
  fill(g, -215, -53, 430, 106, gr, 26);
  g.shadowBlur = 0;
  g.shadowOffsetY = 0;
  boundary(g, -213, -51, 426, 102, 25, "#FFFFFF65");
  line(
    g,
    [
      { x: -180, y: -14 },
      { x: -160, y: -14 },
      { x: -160, y: 15 },
      { x: -180, y: 15 },
      { x: -180, y: -14 },
    ],
    "#FFFFFF",
    2,
  );
  line(
    g,
    [
      { x: -175, y: -8 },
      { x: -165, y: -8 },
    ],
    "#FFFFFF",
    2,
  );
  word(g, label, -139, 1, 29, "#FFFFFF", 650);
  g.restore();
}
function bez(a: P, b: P, c: P, d: P, p: number): P {
  const q = 1 - p;
  return {
    x:
      q * q * q * a.x +
      3 * q * q * p * b.x +
      3 * q * p * p * c.x +
      p * p * p * d.x,
    y:
      q * q * q * a.y +
      3 * q * q * p * b.y +
      3 * q * p * p * c.y +
      p * p * p * d.y,
  };
}
function route(
  g: G,
  a: P,
  b: P,
  c: P,
  d: P,
  progress: number,
  color: string,
  width = 12,
) {
  const points = Array.from({ length: 101 }, (_, i) =>
    bez(a, b, c, d, i / 100),
  );
  line(g, points, color + "25", width);
  line(
    g,
    points.slice(0, Math.max(2, Math.floor(101 * sat(progress)))),
    color,
    width,
  );
  return bez(a, b, c, d, sat(progress));
}
function stage(g: G, tone = "#EFF2F7") {
  fill(g, 0, 0, 1920, 1080, PAPER);
  const gr = g.createLinearGradient(0, 0, 1700, 1080);
  gr.addColorStop(0, "#FFFFFF");
  gr.addColorStop(0.65, PAPER);
  gr.addColorStop(1, tone);
  fill(g, 0, 0, 1920, 1080, gr);
  // A fixed, subtle print texture. No idle motion or blinking noise.
  g.fillStyle = "#20212406";
  for (let i = 0; i < 540; i++) {
    const x = (i * 617) % 1920,
      y = (i * 443) % 1080;
    g.fillRect(x, y, 1.2, 1.2);
  }
}
function topMark(g: G) {
  word(g, "coopagents", 102, 72, 23, INK, 650);
  line(
    g,
    [
      { x: 102, y: 100 },
      { x: 180, y: 100 },
    ],
    "#CCD3DC",
    1,
  );
}
function terminal(
  g: G,
  x: number,
  y: number,
  w: number,
  h: number,
  agent: string,
  color: string,
  mode = "waiting",
  p = 1,
) {
  fill(g, x, y, w, h, "#FBFCFE", 12);
  fill(g, x, y, w, 41, "#EDF0F4", 12);
  fill(g, x, y + 23, w, 18, "#EDF0F4");
  for (let i = 0; i < 3; i++)
    disc(g, x + 18 + i * 16, y + 20, 4, ["#D4D9DF", "#D4D9DF", "#D4D9DF"][i]);
  word(g, agent, x + w / 2, y + 21, 14, "#77818E", 500, "center", MONO);
  badge(g, x + 36, y + 80, agent, color, 0.42);
  word(
    g,
    mode === "done" ? "Change ready for review" : "Working in your project",
    x + 24,
    y + 134,
    19,
    INK,
    600,
  );
  const lines =
    mode === "done"
      ? [
          "read_context  /  API agreement",
          "reply received: status",
          "edit login.ts",
          "return response.status;",
        ]
      : [
          "src / auth / login.ts",
          "const result = await login();",
          "return result.state;",
          "Need the updated API field.",
        ];
  lines.forEach((l, i) => {
    if (i <= Math.floor(p * 4))
      word(
        g,
        l,
        x + 24,
        y + 183 + i * 34,
        17,
        i === 3 ? color : "#8A929E",
        450,
        "left",
        MONO,
      );
  });
  fill(g, x + 24, y + h - 55, w - 48, 33, "#ECEFF4", 7);
  word(g, "> ", x + 35, y + h - 38, 16, color, 600, "left", MONO);
  fill(g, x + 64, y + h - 44, 2, 14, color);
}
function laptop(
  g: G,
  x: number,
  y: number,
  s: number,
  rotation: number,
  agent: string,
  color: string,
  mode = "waiting",
) {
  g.save();
  g.translate(x, y);
  g.rotate(rotation);
  g.scale(s, s);
  cast(g, 10, 298, 430, 75, 0.22);
  const metal = g.createLinearGradient(-300, -220, 320, 220);
  metal.addColorStop(0, "#FFFFFF");
  metal.addColorStop(0.45, "#EDF0F4");
  metal.addColorStop(1, "#AEB7C3");
  g.save();
  g.transform(1, 0.02, -0.12, 0.98, 0, 0);
  sheet(g, -312, -238, 624, 414, 25, "#D1D8E1");
  fill(g, -310, -240, 620, 409, metal, 22);
  fill(g, -294, -223, 588, 375, "#FFFFFF", 14);
  terminal(g, -286, -214, 572, 355, agent, color, mode);
  disc(g, 0, -231, 2.5, "#8A93A0");
  g.restore();
  const base = g.createLinearGradient(0, 160, 0, 310);
  base.addColorStop(0, "#FFFFFF");
  base.addColorStop(0.75, "#D5DBE4");
  base.addColorStop(1, "#A3AEBD");
  g.beginPath();
  g.moveTo(-325, 163);
  g.lineTo(292, 176);
  g.lineTo(387, 292);
  g.quadraticCurveTo(390, 307, 365, 310);
  g.lineTo(-411, 290);
  g.quadraticCurveTo(-426, 285, -409, 271);
  g.closePath();
  g.fillStyle = base;
  g.fill();
  g.save();
  g.transform(1, 0.025, -0.64, 0.55, -25, 185);
  for (let r = 0; r < 4; r++)
    for (let c = 0; c < 13; c++) {
      fill(
        g,
        -255 + c * 41,
        r * 28,
        34,
        21,
        r === 0 ? "#D2D9E3" : "#F5F7FA",
        4,
      );
      boundary(g, -255 + c * 41, r * 28, 34, 21, 4, "#C4CBD6");
    }
  g.restore();
  g.save();
  g.transform(1, 0.025, -0.64, 0.55, 0, 250);
  fill(g, -82, 0, 164, 48, "#DCE2EB", 8);
  boundary(g, -82, 0, 164, 48, 8, "#B8C2CF");
  g.restore();
  g.restore();
}
function desktop(
  g: G,
  x: number,
  y: number,
  s: number,
  rotation: number,
  agent: string,
  color: string,
  mode = "waiting",
) {
  g.save();
  g.translate(x, y);
  g.rotate(rotation);
  g.scale(s, s);
  cast(g, 0, 285, 370, 57, 0.2);
  fill(g, -44, 135, 88, 140, "#C6CED9", 8);
  fill(g, -140, 265, 280, 20, "#B7C1CF", 10);
  fill(g, -137, 260, 274, 18, "#E5E9EF", 10);
  sheet(g, -330, -235, 660, 415, 25, "#C6CED9");
  fill(g, -330, -242, 660, 408, "#FFFFFF", 22);
  fill(g, -312, -223, 624, 356, "#F6F8FA", 12);
  terminal(g, -308, -219, 616, 348, agent, color, mode);
  disc(g, 0, 149, 5, "#C6CCD6");
  g.restore();
}
function room(
  g: G,
  x: number,
  y: number,
  s: number,
  which: number,
  done = false,
) {
  g.save();
  g.translate(x, y);
  g.scale(s, s);
  cast(g, 0, 250, 560, 150, 0.13);
  const gr = g.createLinearGradient(0, 200, 0, 390);
  gr.addColorStop(0, "#FFFFFF");
  gr.addColorStop(1, "#DDE4EE");
  g.fillStyle = gr;
  g.beginPath();
  g.ellipse(0, 260, 520, 140, 0, 0, TAU);
  g.fill();
  g.fillStyle = "#E5EAF1";
  g.beginPath();
  g.ellipse(0, 285, 510, 130, 0, 0, Math.PI);
  g.fill();
  if (which === 0)
    laptop(
      g,
      -40,
      0,
      0.9,
      -0.08,
      "Claude Code",
      CORAL,
      done ? "done" : "waiting",
    );
  else desktop(g, 25, -5, 0.9, 0.07, "Codex", BLUE, done ? "done" : "waiting");
  // A small architectural window and a desk plant make the device a place.
  g.save();
  g.translate(which === 0 ? -380 : 360, -115);
  fill(g, -49, 35, 98, 90, "#E5EAEF", 17);
  for (let i = 0; i < 5; i++) {
    g.save();
    g.rotate((i - 2) * 0.32);
    g.fillStyle = i % 2 ? "#6EAA91" : "#ADCDB8";
    g.beginPath();
    g.ellipse(0, -18 - i * 10, 18, 67, 0, 0, TAU);
    g.fill();
    g.restore();
  }
  g.restore();
  g.restore();
}
function camera(g: G, x: number, y: number, s: number, rot = 0) {
  g.translate(960, 540);
  g.scale(s, s);
  g.rotate(rot);
  g.translate(-x, -y);
}
function pain(g: G, t: number) {
  stage(g, "#F1E8E5");
  topMark(g);
  if (t < 2.5) {
    const p = ease(t / 2.5);
    g.save();
    camera(g, 960 + 32 * p, 540, 1 + 0.04 * p);
    laptop(g, 1340, 565, 1.4, -0.12, "Claude Code", CORAL);
    g.restore();
    word(g, "Your agents", 110, 350, 99);
    word(g, "are coding.", 110, 463, 99);
    word(g, "So why are you", 115, 645, 40, "#7B818A", 500);
    word(g, "passing messages?", 115, 705, 40, INK, 600);
    packet(g, 1320 - 60 * p, 350, "Which API field?", CORAL, 0.92, -0.1);
    return;
  }
  if (t < 5.5) {
    const a = t - 2.5;
    const copy = a < 1.5,
      p = ease((a % 1.5) / 1.1);
    g.save();
    camera(g, 960, 540, 1.08, copy ? -0.06 : 0.06);
    for (let i = 0; i < 3; i++) {
      g.globalAlpha = 0.13 + (i === 2 ? 0.3 : 0);
      packet(
        g,
        640 + i * 200,
        450 + i * 60,
        "Which API field?",
        CORAL,
        1.45,
        -0.1,
      );
    }
    g.globalAlpha = 1;
    packet(
      g,
      lerp(720, 1200, p),
      560,
      "Which API field?",
      copy ? CORAL : BLUE,
      1.45,
      lerp(-0.08, 0.04, p),
    );
    cursor(g, lerp(860, 1340, p), 590, 1.4);
    g.restore();
    word(g, copy ? "Copy." : "Paste.", 120, 240, 142);
    word(g, "Again.", 1710, 900, 64, "#A9AEB6", 600, "right");
    return;
  }
  const a = t - 5.5,
    p = ease(a / 1.8);
  room(g, 320, 650, 0.63, 0);
  room(g, 1600, 650, 0.63, 1);
  for (let i = 0; i < 5; i++) {
    const q = out((a - i * 0.14) / 0.6);
    g.save();
    g.globalAlpha = q;
    packet(
      g,
      960 + (i - 2) * 62,
      440 + i * 52,
      [
        "Which field?",
        "The latest spec?",
        "Can you ask?",
        "Any updates?",
        "Which field?",
      ][i],
      i % 2 ? BLUE : CORAL,
      0.82,
      (i - 2) * 0.055,
    );
    g.restore();
  }
  cursor(g, 1040, 700, 1.3);
  word(g, "You became the messenger.", 960, 195, 76, INK, 650, "center");
  if (p > 0.8) {
    line(
      g,
      [
        { x: 400, y: 930 },
        { x: 1520, y: 930 },
      ],
      "#D9DEE6",
      2,
    );
  }
}
function connect(g: G, t: number) {
  stage(g, "#E6EFEA");
  if (t < 2) {
    const p = out(t / 1.3);
    word(g, "Let your", 100, 380, 154);
    word(g, "agents talk.", 100, 548, 154, GREEN);
    g.save();
    g.translate(1515, 535);
    g.rotate(-0.15 + 0.15 * p);
    cast(g, 0, 165, 230, 55, 0.2);
    fill(g, -190, -190, 380, 380, "#FFFFFF", 90);
    boundary(g, -190, -190, 380, 380, 90, "#E7E9ED");
    g.strokeStyle = INK;
    g.lineWidth = 49;
    g.beginPath();
    g.arc(0, 0, 105, 0.65, TAU - 0.65);
    g.stroke();
    disc(g, 95, 0, 24, BLUE);
    g.restore();
    return;
  }
  if (t < 3.75) {
    const a = t - 2;
    word(g, "Start where you work.", 960, 215, 79, INK, 650, "center");
    g.save();
    g.translate(960, 550);
    g.rotate(-0.035);
    sheet(g, -745, -175, 1490, 350, 30);
    badge(g, -665, -104, "Claude Code", CORAL, 0.7);
    const s = "> Set up Coopagents for this project.";
    word(
      g,
      s.slice(0, Math.floor(a * 38)),
      -665,
      20,
      51,
      INK,
      500,
      "left",
      MONO,
    );
    fill(
      g,
      -665 + Math.min(s.length, Math.floor(a * 38)) * 30.7,
      0,
      3,
      45,
      GREEN,
    );
    g.restore();
    word(g, "Your tools. Your team.", 960, 865, 34, "#7C8591", 500, "center");
    return;
  }
  const a = t - 3.75,
    p = ease(a / 2.1);
  g.save();
  camera(g, 960, 570, lerp(1.18, 1, p), lerp(-0.04, 0, p));
  room(g, 400, 620, 0.94, 0);
  room(g, 1500, 620, 0.94, 1);
  const pos = route(
    g,
    { x: 640, y: 510 },
    { x: 840, y: 260 },
    { x: 1080, y: 260 },
    { x: 1280, y: 510 },
    ramp(a, 0.3, 2.5),
    GREEN,
    12,
  );
  packet(g, pos.x, pos.y, "Shared API context", GREEN, 0.73, -0.06 + 0.12 * p);
  g.restore();
  word(g, "Different agents.", 115, 180, 75);
  word(g, "One team.", 115, 269, 75, GREEN);
  badge(g, 365, 930, "Claude Code", CORAL, 0.75);
  badge(g, 1460, 930, "Codex", BLUE, 0.75);
}
function sphere(g: G, x: number, y: number, r: number, turn: number) {
  const gr = g.createRadialGradient(
    x - r * 0.4,
    y - r * 0.48,
    10,
    x + r * 0.12,
    y + r * 0.12,
    r * 1.18,
  );
  gr.addColorStop(0, "#FFFFFF");
  gr.addColorStop(0.52, "#E4EDF6");
  gr.addColorStop(1, "#B3C5D9");
  g.save();
  g.shadowBlur = 60;
  g.shadowColor = "#607BAE22";
  g.fillStyle = gr;
  g.beginPath();
  g.arc(x, y, r, 0, TAU);
  g.fill();
  g.restore();
  g.save();
  g.beginPath();
  g.arc(x, y, r, 0, TAU);
  g.clip();
  g.strokeStyle = "#AFC2D84D";
  g.lineWidth = 1.5;
  for (let i = -3; i <= 3; i++) {
    const yy = i * 0.22 * r;
    g.beginPath();
    g.ellipse(x, y + yy, Math.sqrt(r * r - yy * yy), r * 0.085, 0, 0, TAU);
    g.stroke();
  }
  for (let i = 0; i < 9; i++) {
    g.beginPath();
    g.ellipse(
      x,
      y,
      Math.max(1, Math.abs(Math.sin(turn + (i * Math.PI) / 9)) * r),
      r,
      0,
      0,
      TAU,
    );
    g.stroke();
  }
  // Geographic silhouette is deliberately schematic, not a map or coverage claim.
  const lands = [
    [
      [-0.76, -0.4],
      [-0.52, -0.65],
      [-0.17, -0.6],
      [-0.08, -0.37],
      [-0.28, -0.16],
      [-0.4, 0.04],
      [-0.62, -0.08],
    ],
    [
      [-0.37, 0.03],
      [-0.1, 0.13],
      [0.04, 0.4],
      [-0.12, 0.73],
      [-0.28, 0.5],
    ],
    [
      [0.02, -0.44],
      [0.31, -0.7],
      [0.78, -0.5],
      [0.84, -0.19],
      [0.56, -0.06],
      [0.36, 0.1],
      [0.12, -0.07],
    ],
    [
      [0.12, -0.04],
      [0.38, 0.02],
      [0.43, 0.33],
      [0.21, 0.55],
      [0.06, 0.31],
    ],
    [
      [0.58, 0.44],
      [0.82, 0.33],
      [0.87, 0.62],
      [0.62, 0.66],
    ],
  ];
  for (const land of lands) {
    g.beginPath();
    land.forEach(([xx, yy], i) =>
      i ? g.lineTo(x + xx * r, y + yy * r) : g.moveTo(x + xx * r, y + yy * r),
    );
    g.closePath();
    g.fillStyle = "#A9C7BB88";
    g.fill();
  }
  g.restore();
}
function distance(g: G, t: number) {
  stage(g, "#E7EDF8");
  if (t < 2.5) {
    const p = ease(t / 2.5);
    g.save();
    camera(g, 960, 570, lerp(1.1, 0.92, p));
    room(g, 400, 630, 1.07, 0);
    room(g, 1540, 630, 1.07, 1);
    g.restore();
    word(g, "Not just the next window.", 960, 155, 77, INK, 650, "center");
    word(g, "YOUR LAPTOP", 330, 970, 26, CORAL, 700);
    word(g, "THEIR DESKTOP", 1400, 970, 26, BLUE, 700);
    return;
  }
  const a = t - 2.5,
    p = ease(ramp(a, 0, 1.4));
  const r = lerp(735, 335, p);
  sphere(g, 960, 590, r, a * 0.12);
  g.save();
  g.globalAlpha = p;
  room(g, 410, 660, 0.62, 0);
  room(g, 1505, 630, 0.62, 1);
  g.restore();
  const pos = route(
    g,
    { x: 480, y: 600 },
    { x: 655, y: 95 },
    { x: 1310, y: 65 },
    { x: 1470, y: 560 },
    ramp(a, 0.65, 3.1),
    BLUE,
    11,
  );
  packet(
    g,
    pos.x,
    pos.y,
    "Same project.",
    BLUE,
    0.82,
    -0.12 + 0.24 * ramp(a, 0.65, 3.1),
  );
  word(g, "Across time zones.", 960, 112, 89, INK, 650, "center");
  if (a > 1.3) {
    word(g, "09:41", 310, 864, 49, CORAL, 500, "left", MONO);
    word(g, "17:41", 1420, 844, 49, BLUE, 500, "left", MONO);
    word(
      g,
      "TWO PLACES. ONE SHARED CONTEXT.",
      960,
      990,
      28,
      "#637182",
      600,
      "center",
    );
  }
}
function document(
  g: G,
  x: number,
  y: number,
  scale: number,
  angle: number,
  highlight: number,
) {
  g.save();
  g.translate(x, y);
  g.rotate(angle);
  g.scale(scale, scale);
  cast(g, 10, 330, 380, 75, 0.15);
  for (let i = 3; i >= 0; i--)
    sheet(
      g,
      -270 + i * 6,
      -340 + i * 5,
      540,
      680,
      6,
      i ? "#E9EDF2" : "#FFFFFF",
    );
  word(g, "SHARED CONTEXT", -214, -280, 20, GREEN, 700);
  word(g, "API agreement", -214, -211, 47, INK, 650);
  line(
    g,
    [
      { x: -214, y: -161 },
      { x: 214, y: -161 },
    ],
    "#DDE2E8",
    2,
  );
  word(g, "Login response", -214, -105, 24, "#77818E", 550);
  fill(g, -225, -62, 450, 89, highlight ? "#D8F0E5" : "#F1F3F6", 10);
  word(g, 'status: "authenticated"', -198, -16, 26, GREEN, 500, "left", MONO);
  for (let i = 0; i < 5; i++)
    fill(g, -214, 80 + i * 31, [388, 340, 374, 290, 150][i], 9, "#E3E8EF", 4);
  word(g, "Project-scoped agreement", -214, 282, 17, "#7F8997", 500);
  g.restore();
}
function exchange(g: G, t: number) {
  stage(g, "#E6F0EB");
  if (t < 2) {
    const p = ease(t / 1.8);
    g.save();
    camera(g, 960, 540, 1.05, -0.04);
    laptop(g, 315, 660, 1.15, -0.12, "Claude Code", CORAL);
    document(g, 1490, 575, 0.9, 0.08, 0);
    const pos = route(
      g,
      { x: 470, y: 510 },
      { x: 750, y: 300 },
      { x: 1170, y: 300 },
      { x: 1420, y: 510 },
      p,
      BLUE,
      9,
    );
    packet(g, pos.x, pos.y, "Which API field?", BLUE, 1.05, -0.06);
    g.restore();
    word(g, "Ask your teammate’s agent.", 960, 145, 77, INK, 650, "center");
    return;
  }
  if (t < 4) {
    const a = t - 2,
      p = out(a / 1.5);
    document(g, 650, 590, 1.12, -0.09 + 0.025 * p, 1);
    badge(g, 1230, 335, "Codex", BLUE, 1);
    word(g, "Found it.", 1175, 472, 101);
    packet(g, 1370, 650, "status + source", GREEN, 1.03, 0.04);
    return;
  }
  const a = t - 4,
    p = ease(ramp(a, 0.2, 1.4));
  g.save();
  g.translate(960, 530);
  g.rotate(-0.025);
  sheet(g, -790, -227, 1580, 454, 26);
  word(g, "login.ts", -720, -156, 27, "#8D97A4", 500, "left", MONO);
  word(g, "return response.", -720, 7, 72, INK, 500, "left", MONO);
  const x = -720 + g.measureText("return response.").width;
  g.save();
  g.globalAlpha = 1 - p;
  word(g, "state", x, 7, 72, CORAL, 500, "left", MONO);
  line(
    g,
    [
      { x, y: 6 },
      { x: x + 215, y: 6 },
    ],
    CORAL,
    5,
  );
  g.restore();
  g.save();
  g.globalAlpha = p;
  word(g, "status", x, lerp(-110, 7, p), 72, GREEN, 600, "left", MONO);
  g.restore();
  fill(g, -720, 88, 1320 * p, 10, MINT, 5);
  word(g, "Answer linked to shared context.", -720, 155, 27, "#7D8794", 500);
  g.restore();
  word(g, "Back to building.", 960, 180, 91, INK, 650, "center");
  if (a > 2.4) {
    const q = out((a - 2.4) / 0.6);
    disc(g, 1660, 777, 46, GREEN);
    tick(g, 1660, 777, 46, "#FFFFFF", q);
    word(g, "Change ready", 1580, 870, 32, GREEN, 600, "right");
  }
}
function resultApp(g: G, x: number, y: number, s: number, p: number) {
  g.save();
  g.translate(x, y);
  g.scale(s, s);
  sheet(g, -560, -310, 1120, 620, 25);
  fill(g, -560, -310, 1120, 55, "#EDF0F5", 25);
  fill(g, -560, -280, 1120, 25, "#EDF0F5");
  for (let i = 0; i < 3; i++) disc(g, -529 + i * 18, -282, 5, "#CAD2DD");
  word(g, "Project / Review", -470, -281, 18, "#6F7C8C", 500);
  fill(g, -560, -255, 220, 565, "#F5F7FA");
  word(g, "Coopagents", -529, -209, 23, INK, 650);
  ["Overview", "Tasks", "Shared context", "Deliveries"].forEach((v, i) =>
    word(
      g,
      v,
      -528,
      -138 + i * 49,
      17,
      i === 3 ? INK : "#9099A6",
      i === 3 ? 650 : 400,
    ),
  );
  word(g, "Login response", -280, -182, 48, INK, 650);
  word(g, "A concrete change, with context.", -280, -120, 23, "#8792A1", 500);
  fill(g, -280, -60, 750, 138, "#F4F7F9", 13);
  word(g, "- response.state", -244, -15, 29, CORAL, 500, "left", MONO);
  word(g, "+ response.status", -244, 37, 29, GREEN, 500, "left", MONO);
  line(
    g,
    [
      { x: -280, y: 123 },
      { x: 470, y: 123 },
    ],
    "#E5E9EF",
    2,
  );
  word(g, "API agreement", -280, 166, 23, GREEN, 650);
  word(g, "Linked source", 210, 166, 18, "#8B95A3", 400);
  fill(g, 172, 221, 298, 58, p > 0.7 ? GREEN : INK, 28);
  word(
    g,
    p > 0.7 ? "Approved" : "Review change",
    321,
    251,
    22,
    "#FFFFFF",
    650,
    "center",
  );
  g.restore();
}
function payoff(g: G, t: number) {
  stage(g, "#EDF1F8");
  if (t < 2.4) {
    const p = ease(t / 2.4);
    g.save();
    camera(g, 990, 600, 1.08 - 0.05 * p, -0.04 + 0.03 * p);
    resultApp(g, 1060, 615, 1.1, 0);
    g.restore();
    word(g, "The work. The context.", 110, 150, 91);
    return;
  }
  if (t < 4.2) {
    const a = t - 2.4,
      p = out(a / 0.85);
    resultApp(g, 960, 565, 1.18, ramp(a, 0.55, 0.95));
    cursor(g, lerp(1600, 1335, p), lerp(1040, 857, p), 1.35, "YOU");
    word(g, "Your call.", 116, 150, 111);
    return;
  }
  const p = ease((t - 4.2) / 1.8);
  room(g, 430, 640, 0.93, 0, true);
  room(g, 1505, 620, 0.93, 1, true);
  route(
    g,
    { x: 650, y: 540 },
    { x: 860, y: 280 },
    { x: 1050, y: 280 },
    { x: 1270, y: 520 },
    1,
    GREEN,
    11,
  );
  packet(
    g,
    lerp(690, 1250, p),
    lerp(425, 410, p),
    "Context, connected.",
    GREEN,
    0.9,
  );
  word(g, "Less relaying.", 960, 170, 97, INK, 650, "center");
  word(g, "More building.", 960, 925, 97, GREEN, 650, "center");
}
function finale(g: G, t: number) {
  stage(g, "#E8EEE9");
  if (t < 2) {
    const p = ease(t / 1.7);
    const labels = ["Agents.", "Devices.", "Places."];
    const i = Math.min(2, Math.floor(t / 0.65));
    word(g, labels[i], 960, 440, 192, [CORAL, BLUE, GREEN][i], 700, "center");
    word(g, "Connected.", 960, 646, 104, INK, 650, "center");
    const w = lerp(0, 1480, p);
    line(
      g,
      [
        { x: 220, y: 815 },
        { x: 220 + w, y: 815 },
      ],
      MINT,
      13,
    );
    return;
  }
  const p = out((t - 2) / 0.6);
  word(g, "Coopagents", 960, 590 + (1 - p) * 45, 166, INK, 650, "center");
  word(g, "Let your agents work together.", 960, 769, 49, GREEN, 550, "center");
  word(
    g,
    "github.com/Weichenleeeee123/coopagents",
    960,
    940,
    25,
    "#788392",
    450,
    "center",
    MONO,
  );
}

export function drawLaunch(g: G, section: number, t: number) {
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, 1920, 1080);
  g.lineCap = "round";
  g.lineJoin = "round";
  [pain, connect, distance, exchange, payoff, finale][section](g, t);
}
