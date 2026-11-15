import {C} from '../story/palette';

type G=CanvasRenderingContext2D;
type Point={x:number;y:number};
const TAU=Math.PI*2;
const clamp=(v:number)=>Math.max(0,Math.min(1,v));
const ease=(v:number)=>{const q=clamp(v);return q*q*(3-2*q);};
const out=(v:number)=>1-(1-clamp(v))**3;
const mix=(a:number,b:number,p:number)=>a+(b-a)*p;
const mono='"Cascadia Code",Consolas,monospace';
const sans='"Segoe UI Variable","Segoe UI",sans-serif';

function type(g:G,value:string,x:number,y:number,size:number,color:string=C.ink,align:CanvasTextAlign='center',weight=650){g.fillStyle=color;g.font=`${weight} ${size}px ${sans}`;g.textAlign=align;g.textBaseline='middle';g.fillText(value,x,y);}
function code(g:G,value:string,x:number,y:number,size:number,color:string=C.ink,align:CanvasTextAlign='center'){g.fillStyle=color;g.font=`500 ${size}px ${mono}`;g.textAlign=align;g.textBaseline='middle';g.fillText(value,x,y);}
function circle(g:G,x:number,y:number,r:number,color:string,alpha=1){g.save();g.globalAlpha*=alpha;g.fillStyle=color;g.beginPath();g.arc(x,y,r,0,TAU);g.fill();g.restore();}
function path(g:G,points:Point[],color:string,width=4,alpha=1){if(points.length<2)return;g.save();g.globalAlpha*=alpha;g.lineWidth=width;g.lineCap='round';g.lineJoin='round';g.strokeStyle=color;g.beginPath();points.forEach((p,i)=>i?g.lineTo(p.x,p.y):g.moveTo(p.x,p.y));g.stroke();g.restore();}
function bezier(a:Point,b:Point,c:Point,d:Point,u:number):Point{const v=1-u;return{x:v*v*v*a.x+3*v*v*u*b.x+3*v*u*u*c.x+u*u*u*d.x,y:v*v*v*a.y+3*v*v*u*b.y+3*v*u*u*c.y+u*u*u*d.y};}
function beam(g:G,a:Point,b:Point,c:Point,d:Point,t:number,color:string,reveal=1){const points=Array.from({length:101},(_,i)=>bezier(a,b,c,d,i/100));path(g,points.slice(0,Math.max(2,Math.round(reveal*101))),color,4,.5);for(let n=0;n<4;n++){const u=(t*.28+n*.25)%1;const at=bezier(a,b,c,d,u);for(let j=5;j>=1;j--){const trail=bezier(a,b,c,d,Math.max(0,u-j*.008));circle(g,trail.x,trail.y,4,color,.08);}circle(g,at.x,at.y,7,color);}}
function person(g:G,x:number,y:number,s:number,color:string){circle(g,x,y,s*.95,color,.12);circle(g,x,y-s*.26,s*.22,color);g.fillStyle=color;g.beginPath();g.moveTo(x-s*.48,y+s*.43);g.quadraticCurveTo(x-s*.4,y+s*.02,x,y+s*.02);g.quadraticCurveTo(x+s*.4,y+s*.02,x+s*.48,y+s*.43);g.closePath();g.fill();}
function agent(g:G,x:number,y:number,r:number,which:number,t:number,label=true){const color=which?C.blue:C.orange;g.save();g.translate(x,y);g.rotate((which?-1:1)*t*.08);if(which){g.strokeStyle=color;g.lineWidth=r*.12;g.lineCap='round';g.lineJoin='round';g.beginPath();g.moveTo(-r*.12,-r*.7);g.lineTo(-r*.72,0);g.lineTo(-r*.12,r*.7);g.moveTo(r*.12,-r*.7);g.lineTo(r*.72,0);g.lineTo(r*.12,r*.7);g.stroke();}else{for(let i=0;i<8;i++){g.save();g.rotate(i*Math.PI/4);g.strokeStyle=color;g.lineCap='round';g.lineWidth=r*.13;g.beginPath();g.moveTo(r*.2,0);g.lineTo(r*.86,0);g.stroke();g.restore();}}g.restore();if(label)type(g,which?'Codex':'Claude Code',x,y+r+38,32,color);}
function bigWord(g:G,value:string,t:number,color:string=C.ink,sub=''){const e=out(t/.32);g.save();g.translate(960,470+(1-e)*95);g.rotate((1-e)*-.06);g.scale(.91+e*.09,.91+e*.09);g.globalAlpha*=e;g.strokeStyle=color;g.lineWidth=2;g.font=`750 260px ${sans}`;const fit=Math.min(1,1690/g.measureText(value).width);g.font=`750 ${260*fit}px ${sans}`;g.textAlign='center';g.textBaseline='middle';g.globalAlpha*=.15;g.strokeText(value,14,-27);g.globalAlpha/=.15;g.fillStyle=color;g.fillText(value,0,0);g.restore();if(sub)type(g,sub,960,735,43,C.muted);}
function page(g:G,x:number,y:number,s:number,rotation:number,color:string){g.save();g.translate(x,y);g.rotate(rotation);g.strokeStyle=color;g.lineWidth=5;g.lineJoin='round';g.beginPath();g.moveTo(-s*.34,-s*.48);g.lineTo(s*.16,-s*.48);g.lineTo(s*.34,-s*.29);g.lineTo(s*.34,s*.48);g.lineTo(-s*.34,s*.48);g.closePath();g.stroke();g.beginPath();g.moveTo(s*.16,-s*.48);g.lineTo(s*.16,-s*.29);g.lineTo(s*.34,-s*.29);g.stroke();for(let i=0;i<3;i++){g.beginPath();g.moveTo(-s*.2,-s*.1+i*s*.16);g.lineTo(s*(i===2?.06:.19),-s*.1+i*s*.16);g.stroke();}g.restore();}
function check(g:G,x:number,y:number,r:number,color:string,p=1){const points=[{x:x-r*.5,y},{x:x-r*.1,y:y+r*.37},{x:x+r*.55,y:y-r*.45}];const f=clamp(p)*2;if(f<=1)path(g,[points[0],{x:mix(points[0].x,points[1].x,f),y:mix(points[0].y,points[1].y,f)}],color,r*.1);else path(g,[points[0],points[1],{x:mix(points[1].x,points[2].x,f-1),y:mix(points[1].y,points[2].y,f-1)}],color,r*.1);}

function relay(g:G,t:number,phase='pain'){
 const free=phase==='free';agent(g,340,510,82,0,t);agent(g,1580,510,82,1,t);
 const down=free?ease(t/1.3):0;person(g,960,510+down*255,105,free?C.green:C.lilac);
 type(g,free?'You decide.':'YOU',960,655+down*200,36,free?C.green:C.lilac);
 if(free){beam(g,{x:430,y:480},{x:720,y:160},{x:1200,y:160},{x:1490,y:480},t,C.green,ease(t/.5));beam(g,{x:1490,y:520},{x:1200,y:660},{x:720,y:660},{x:430,y:520},t+.5,C.blue,ease(t/.7));}
 else{beam(g,{x:430,y:480},{x:600,y:280},{x:780,y:280},{x:875,y:480},t,C.orange);beam(g,{x:1045,y:480},{x:1220,y:280},{x:1400,y:280},{x:1490,y:480},t+.7,C.blue);}
}

function pain(g:G,t:number){
 if(t<1.5){relay(g,t);type(g,'Two agents. One human relay.',960,185,76);const q=ease(t/1.2);code(g,'state?',530+q*100,345,40,C.orange);code(g,'status?',1390-q*100,345,40,C.blue);return;}
 if(t<2.75){bigWord(g,'COPY.',t-1.5,C.orange,'A question from one agent.');const p=ease((t-1.5)/1.1);path(g,[{x:320,y:820},{x:320+p*1280,y:820}],C.orange,12,.3);return;}
 if(t<4){bigWord(g,'PASTE.',t-2.75,C.blue,'Into another conversation.');const p=ease((t-2.75)/1.1);path(g,[{x:1600,y:820},{x:1600-p*1280,y:820}],C.blue,12,.3);return;}
 if(t<5.5){bigWord(g,'EXPLAIN.',t-4,C.lilac,'Again. And again.');for(let i=0;i<3;i++)path(g,Array.from({length:80},(_,j)=>({x:180+j*20,y:810+Math.sin(j*.13+t*3+i)*25+i*18})),[C.orange,C.blue,C.lilac][i],3,.3);return;}
 relay(g,t*.8);type(g,'You became the message bus.',960,190,78);code(g,'requirements',670,330+Math.sin(t*3)*17,34,C.orange);code(g,'latest spec?',1250,325+Math.cos(t*3)*17,34,C.blue);
}

function devices(g:G,t:number){
 const p=out(t/.7);const shift=(1-p)*230;
 for(let i=0;i<2;i++){const x=i?1420+shift:500-shift;const y=570;const color=i?C.blue:C.orange;g.save();g.translate(x,y);g.rotate((i?1:-1)*(.07+Math.sin(t)*.025));g.strokeStyle=color;g.lineWidth=6;g.lineJoin='round';g.strokeRect(-210,-150,420,270);if(i){path(g,[{x:-35,y:120},{x:-35,y:190},{x:-120,y:190},{x:120,y:190},{x:35,y:190},{x:35,y:120}],color,6);}else{path(g,[{x:-210,y:120},{x:-265,y:175},{x:265,y:175},{x:210,y:120}],color,6);path(g,[{x:-75,y:130},{x:-88,y:150},{x:88,y:150},{x:75,y:130}],color,3);}agent(g,0,-15,55,i,t,false);g.restore();type(g,i?'Desktop B':'Laptop A',x,835,33,C.muted);}
 beam(g,{x:750,y:515},{x:870,y:365},{x:1050,y:365},{x:1170,y:515},t,C.green,p);
}
function connect(g:G,t:number){
 if(t<1.6){relay(g,t,'free');type(g,'Let them talk.',960,170,108);return;}
 if(t<3.2){const p=out((t-1.6)/.8);g.save();g.translate(960,470);g.rotate((1-p)*-.8);g.strokeStyle=C.ink;g.lineWidth=46;g.lineCap='round';g.beginPath();g.arc(0,0,155,-.7,.7+4.2*p);g.stroke();circle(g,145,0,27,C.blue);g.restore();type(g,'Coopagents',960,750,130);return;}
 if(t<5){const z=t-3.2;type(g,'Across agents.',960,195,100);agent(g,500+Math.sin(z*2)*30,530,130,0,t);agent(g,1420-Math.sin(z*2)*30,530,130,1,t);beam(g,{x:680,y:500},{x:860,y:300},{x:1060,y:300},{x:1240,y:500},z,C.green);return;}
 type(g,'Across devices.',960,195,100);devices(g,t-5);
}

function globe(g:G,t:number){
 const r=mix(460,280,ease(t/1.6));const cx=960,cy=510;g.save();g.translate(cx,cy);g.rotate(-.15);const gr=g.createRadialGradient(-80,-100,20,0,0,r);gr.addColorStop(0,'#FFFFFF');gr.addColorStop(1,'#D8E6F7');g.fillStyle=gr;g.beginPath();g.arc(0,0,r,0,TAU);g.fill();g.save();g.beginPath();g.arc(0,0,r,0,TAU);g.clip();g.strokeStyle='#9BB9DB';g.lineWidth=1.8;for(let i=-3;i<=3;i++){g.beginPath();g.ellipse(0,i*r*.24,Math.sqrt(r*r-(i*r*.24)**2),r*.09,0,0,TAU);g.stroke();}for(let i=0;i<6;i++){g.beginPath();g.ellipse(0,0,Math.max(2,Math.abs(Math.sin(t*.32+i*Math.PI/6))*r),r,0,0,TAU);g.stroke();}g.restore();g.restore();
 beam(g,{x:290,y:680},{x:680,y:70},{x:1240,y:70},{x:1630,y:680},t,C.blue,ease(t/.8));beam(g,{x:290,y:700},{x:700,y:960},{x:1250,y:960},{x:1630,y:700},t+.6,C.green,ease(t/.8));circle(g,290,680,20,C.orange);circle(g,1630,680,20,C.blue);type(g,'Region A',290,760,32,C.orange);type(g,'Region B',1630,760,32,C.blue);
}
function world(g:G,t:number){
 if(t<3.2){globe(g,t);type(g,'Across regions.',960,130,98);return;}
 if(t<5){const age=t-3.2;g.save();g.translate(960,465);g.rotate(-.035);g.fillStyle=C.terminal;g.beginPath();g.roundRect(-650,-80,1300,160,12);g.fill();code(g,'Claude Code',-612,-120,24,C.orange,'left');const prompt='> Set up Coopagents.';code(g,prompt.slice(0,Math.min(prompt.length,Math.floor(age*30))),-600,0,55,C.terminalText,'left');if(age<1)code(g,'|',-600+Math.min(prompt.length,Math.floor(age*30))*33,0,55,C.terminalMint,'left');g.restore();type(g,'Start where you work.',960,780,70);return;}
 const age=t-5;type(g,'One shared context.',960,170,98);for(let i=0;i<6;i++){const a=i*TAU/6+age*.55;const shrink=1-ease(age/2)*.4;const x=960+Math.cos(a)*520*shrink,y=550+Math.sin(a)*240*shrink;page(g,x,y,125,Math.sin(a)*.13,[C.blue,C.green,C.orange][i%3]);path(g,[{x,y},{x:960,y:550}],C.line,2);}circle(g,960,550,95,C.mint);code(g,'context',960,550,31,C.green);
}

function question(g:G,t:number){
 if(t<2){const p=out(t/.6);type(g,'Ask the right agent.',960,175,100);agent(g,300,550,80,0,t);agent(g,1620,550,80,1,t);const x=mix(450,960,p);code(g,'Which field?',x,500,85,C.blue);beam(g,{x:430,y:650},{x:750,y:850},{x:1170,y:850},{x:1490,y:650},t,C.blue,p);return;}
 if(t<4){const a=t-2;type(g,'The question travels.',960,160,80);const q=ease(a/1.6);const at=bezier({x:250,y:690},{x:650,y:180},{x:1260,y:180},{x:1670,y:690},q);beam(g,{x:250,y:690},{x:650,y:180},{x:1260,y:180},{x:1670,y:690},a,C.blue);g.save();g.translate(at.x,at.y);g.rotate(Math.cos(q*Math.PI)*.25);code(g,'status?',0,0,73,C.blue);g.restore();agent(g,1670,740,64,1,t);return;}
 if(t<5.6){const p=out((t-4)/.55);g.save();g.translate(960,500);g.scale(.7+.3*p,.7+.3*p);code(g,'status',0,0,180,C.green);g.restore();path(g,[{x:630,y:625},{x:630+p*660,y:625}],C.mint,28);type(g,'Found in shared context.',960,785,55,C.muted);return;}
 const a=t-5.6;type(g,'Answer + source.',960,170,94);const x=1380-ease(a/1.4)*760;code(g,'status',x,480,120,C.green);page(g,x+220,650,100,-.1,C.blue);type(g,'API agreement',x+220,755,33,C.muted);beam(g,{x:1650,y:850},{x:1200,y:990},{x:700,y:990},{x:270,y:850},a,C.green);
}

function build(g:G,t:number){
 if(t<3.6){const strike=ease((t-.45)/.6);const answer=ease((t-1.35)/.8);type(g,'The answer becomes code.',960,180,84);code(g,'response.',830,520,112,C.ink,'right');g.save();g.globalAlpha*=1-answer;code(g,'state',860,520,112,C.orange,'left');path(g,[{x:855,y:520},{x:855+strike*335,y:520}],C.orange,7);g.restore();const x=mix(1580,860,answer),y=mix(260,520,answer);g.save();g.globalAlpha*=out((t-1)/.35);code(g,'status',x,y,112,C.green,'left');g.restore();return;}
 if(t<5.5){const a=t-3.6;type(g,'Keep building.',960,170,105);for(let i=0;i<7;i++){const x=170+i*265;const y=470+Math.sin(a*2+i*.6)*105;code(g,['{','<','/','>','}','(',')'][i],x,y,125,[C.blue,C.green,C.lilac][i%3]);path(g,[{x,y:y+110},{x:x+90,y:y+150}],C.mint,4);}path(g,Array.from({length:80},(_,i)=>({x:170+i*20,y:750+Math.sin(i*.09+a*2)*45})),C.blue,4,.5);return;}
 const p=out((t-5.5)/.7);page(g,960,480,270,Math.sin(t)*.06,C.blue);code(g,'login.ts',960,730,57,C.ink);check(g,1250,460,110,C.green,p);type(g,'A concrete change.',960,170,86);
}

function trace(g:G,t:number){
 type(g,t<4?'Linked to the work.':'People stay in control.',960,170,92);
 if(t<4){const positions=[{x:400,y:550},{x:960,y:440},{x:1520,y:550}];beam(g,positions[0],{x:700,y:240},{x:1220,y:240},positions[2],t,C.green,ease(t/.7));for(let i=0;i<3;i++){const p=out((t-i*.32)/.6);g.save();g.globalAlpha*=p;const at=positions[i];if(i===1)page(g,at.x,at.y,175,Math.sin(t)*.05,C.blue);else{circle(g,at.x,at.y,82,i===0?C.coral:C.mint);if(i===0)code(g,'work',at.x,at.y,32,C.orange);else check(g,at.x,at.y,85,C.green,p);}type(g,['Task','Code','Evidence'][i],at.x,at.y+175,40,C.muted);g.restore();}return;}
 const p=out((t-4)/.7);person(g,960,520,150,C.green);circle(g,1250,500,95,C.mint,p);check(g,1250,500,95,C.green,p);type(g,'You decide.',960,790,70,C.green);
}

function relief(g:G,t:number){
 if(t<2.4){relay(g,t,'free');type(g,'Agents share context.',960,165,98);return;}
 if(t<4.7){const phase=Math.floor((t-2.4)/.77);const label=['AGENTS.','DEVICES.','REGIONS.'][Math.min(2,phase)];bigWord(g,label,(t-2.4)% .77,[C.orange,C.blue,C.green][Math.min(2,phase)]);return;}
 const a=t-4.7;bigWord(g,a<1.1?'LESS RELAYING.':'MORE BUILDING.',a<1.1?a:a-1.1,a<1.1?C.muted:C.green);g.save();g.globalAlpha*=.2;for(let i=0;i<6;i++)path(g,[{x:120,y:880+i*15},{x:1800,y:880+i*15-Math.sin(a*3+i)*35}],C.blue,2);g.restore();
}

function brand(g:G,t:number){
 const p=out(t/.8);g.save();g.translate(960,350);g.rotate((1-p)*-.6);g.strokeStyle=C.blue;g.lineWidth=4;for(let i=0;i<4;i++){g.beginPath();g.ellipse(0,0,195+i*25,115+i*20,i*.4+t*.15,0,TAU);g.globalAlpha=.12;g.stroke();}g.restore();
 const word=out((t-.6)/.75);g.save();g.globalAlpha*=word;type(g,'Coopagents',960,650+(1-word)*60,154,C.ink);g.restore();
 if(t>1.7){g.save();g.globalAlpha*=out((t-1.7)/.6);type(g,'Less relaying. More building.',960,805,52,C.green);g.restore();}
 if(t>3.1){g.save();g.globalAlpha*=out((t-3.1)/.5);code(g,'github.com/Weichenleeeee123/coopagents',960,955,25,C.blue);g.restore();}
}

const renderers=[pain,connect,world,question,build,trace,relief,brand] as const;
export function drawAd(g:G,index:number,frame:number,energy:number){
 g.setTransform(1,0,0,1,0,0);g.clearRect(0,0,1920,1080);g.lineCap='round';g.lineJoin='round';g.textBaseline='middle';
 const t=frame/60;g.save();const pulse=1+energy*.004;g.translate(960,540);g.scale(pulse,pulse);g.translate(-960,-540);renderers[index](g,t);g.restore();
}
