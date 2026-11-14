import {C} from '../story/palette';

type G=CanvasRenderingContext2D;
type P={x:number;y:number};
const TAU=Math.PI*2;
const clamp=(v:number)=>Math.max(0,Math.min(1,v));
const out=(v:number)=>1-(1-clamp(v))**3;
const mix=(a:number,b:number,t:number)=>a+(b-a)*t;
const sans='"Segoe UI Variable","Segoe UI",sans-serif';
const mono='"Cascadia Code",Consolas,monospace';

function txt(g:G,s:string,x:number,y:number,size:number,color:string=C.ink,weight=650,align:CanvasTextAlign='center'){
 g.save();g.fillStyle=color;g.font=`${weight} ${size}px ${sans}`;g.textAlign=align;g.textBaseline='middle';g.fillText(s,x,y);g.restore();
}
function code(g:G,s:string,x:number,y:number,size:number,color:string=C.ink,align:CanvasTextAlign='left'){
 g.save();g.fillStyle=color;g.font=`500 ${size}px ${mono}`;g.textAlign=align;g.textBaseline='middle';g.fillText(s,x,y);g.restore();
}
function dot(g:G,x:number,y:number,r:number,color:string,a=1){g.save();g.globalAlpha*=a;g.fillStyle=color;g.beginPath();g.arc(x,y,r,0,TAU);g.fill();g.restore();}
function stroke(g:G,points:P[],color:string,w=4,a=1){if(points.length<2)return;g.save();g.globalAlpha*=a;g.strokeStyle=color;g.lineWidth=w;g.lineCap='round';g.lineJoin='round';g.beginPath();points.forEach((p,i)=>i?g.lineTo(p.x,p.y):g.moveTo(p.x,p.y));g.stroke();g.restore();}
function ribbon(g:G,points:P[],t:number,color:string,w=14){
 stroke(g,points,color,w,.16);const n=points.length-1;const q=clamp(t)*n;const i=Math.min(n-1,Math.floor(q));const p=mixP(points[i],points[i+1],q-i);dot(g,p.x,p.y,w*.92,color,.95);dot(g,p.x,p.y,w*.35,C.paper,.9);
}
function mixP(a:P,b:P,t:number):P{return{x:mix(a.x,b.x,t),y:mix(a.y,b.y,t)}}
function rounded(g:G,x:number,y:number,w:number,h:number,r:number,fill:string,strokeColor?:string,line=2,a=1){g.save();g.globalAlpha*=a;g.beginPath();g.roundRect(x,y,w,h,r);g.fillStyle=fill;g.fill();if(strokeColor){g.strokeStyle=strokeColor;g.lineWidth=line;g.stroke();}g.restore();}
function chip(g:G,x:number,y:number,w:number,label:string,color:string,p=1,rot=0){g.save();g.translate(x,y);g.rotate(rot);g.shadowBlur=26;g.shadowColor=color+'55';rounded(g,-w/2,-32,w,64,32,color);dot(g,-w*.36,0,8,C.paper,.95);txt(g,label,-w*.02,1,23,C.paper,750);stroke(g,[{x:w*.25,y:0},{x:w*.39,y:0}],C.paper,4,.8);g.restore();if(p<1)stroke(g,[{x:x-w*.36,y:y+48},{x:x-w*.36+w*.72*p,y:y+48}],color,6,.8);}
function agent(g:G,x:number,y:number,r:number,color:string,kind:'star'|'chevron',scale=1){g.save();g.translate(x,y);g.scale(scale,scale);g.shadowBlur=35;g.shadowColor=color+'44';if(kind==='star'){for(let i=0;i<8;i++){g.save();g.rotate(i*Math.PI/4);stroke(g,[{x:r*.2,y:0},{x:r,y:0}],color,r*.11);g.restore();}}else{stroke(g,[{x:-r*.55,y:-r*.7},{x:-r,y:0},{x:-r*.55,y:r*.7}],color,r*.16);stroke(g,[{x:r*.55,y:-r*.7},{x:r,y:0},{x:r*.55,y:r*.7}],color,r*.16);}g.restore();}
function person(g:G,x:number,y:number,s:number,color:string,a=1){g.save();g.globalAlpha*=a;dot(g,x,y-s*.6,s*.17,color);g.fillStyle=color;g.beginPath();g.moveTo(x-s*.45,y+s*.42);g.quadraticCurveTo(x-s*.4,y-s*.08,x,y-s*.05);g.quadraticCurveTo(x+s*.4,y-s*.08,x+s*.45,y+s*.42);g.closePath();g.fill();g.restore();}
function device(g:G,x:number,y:number,w:number,h:number,color:string,kind:'laptop'|'desktop'|'phone',a=1){g.save();g.globalAlpha*=a;g.translate(x,y);g.shadowBlur=46;g.shadowColor='#20212422';if(kind==='phone'){rounded(g,-w/2,-h/2,w,h,26,C.panel,color,5);rounded(g,-w*.34,-h*.32,w*.68,h*.57,12,C.sky,'#FFFFFF',2);dot(g,0,-h*.39,4,color);stroke(g,[{x:-w*.13,y:h*.36},{x:w*.13,y:h*.36}],color,5,.55);}else{rounded(g,-w/2,-h/2,w,h,16,C.panel,color,6);rounded(g,-w*.42,-h*.35,w*.84,h*.62,10,kind==='laptop'?C.coral:'#E6EEFF','#FFFFFF',3);stroke(g,[{x:-w*.57,y:h*.49},{x:w*.57,y:h*.49}],color,7);if(kind==='desktop'){stroke(g,[{x:0,y:h*.35},{x:0,y:h*.52}],color,5);stroke(g,[{x:-w*.2,y:h*.52},{x:w*.2,y:h*.52}],color,5);}}g.restore();}
function backdrop(g:G,t:number,energy:number){const gr=g.createLinearGradient(0,0,1920,1080);gr.addColorStop(0,C.paper);gr.addColorStop(.55,'#FFFFFF');gr.addColorStop(1,'#F0F6FF');g.fillStyle=gr;g.fillRect(0,0,1920,1080);const a=g.createRadialGradient(300,220,10,300,220,600);a.addColorStop(0,C.coral+'A0');a.addColorStop(1,C.coral+'00');g.fillStyle=a;g.fillRect(0,0,1000,760);const b=g.createRadialGradient(1650,850,10,1650,850,650);b.addColorStop(0,C.mint+'B0');b.addColorStop(1,C.mint+'00');g.fillStyle=b;g.fillRect(950,350,970,730);for(let i=0;i<28;i++){const x=(i*173+t*24)%1920;const y=90+(i*113)%880;dot(g,x,y,1.5,C.blue,.06+energy*.025);}}
function title(g:G,kicker:string,headline:string,accent:string){txt(g,kicker,120,112,34,C.muted,700,'left');txt(g,headline,120,175,82,C.ink,780,'left');stroke(g,[{x:120,y:225},{x:390,y:225}],accent,8,.85);}

function pain(g:G,t:number){
 title(g,'THE HUMAN RELAY','Copy. Paste. Explain.',C.orange);
 const phase=t<2?0:t<4?1:t<5.8?2:3;
 device(g,320,650,520,340,C.orange,'laptop',1);device(g,1600,650,520,340,C.blue,'desktop',1);person(g,960,700,190,C.lilac);
 if(phase===0){chip(g,420,430,390,'needs: login status',C.orange,out(t/.8),-.08);chip(g,1500,430,390,'which field?',C.blue,out((t-.45)/.8),.08);stroke(g,[{x:560,y:500},{x:820,y:630}],C.orange,10,.45);stroke(g,[{x:1360,y:500},{x:1100,y:630}],C.blue,10,.45);}
 if(phase===1){chip(g,mix(420,960,out((t-2)/1.4)),500,450,'needs: login status',C.orange,out((t-2)/1.4),-.04);chip(g,mix(1500,960,out((t-2.25)/1.4)),610,450,'needs: login status',C.blue,out((t-2.25)/1.4),.04);}
 if(phase===2){for(let i=0;i<3;i++){chip(g,960+(i-1)*170,430+i*72,340,'again?', [C.orange,C.blue,C.lilac][i],out((t-4-i*.18)/.45),(i-1)*.08);}person(g,960,700,190,C.lilac);txt(g,'You are the message bus.',960,955,46,C.lilac,700);}
 if(phase===3){const p=out((t-5.8)/1.2);stroke(g,[{x:380,y:480},{x:720,y:330},{x:1200,y:330},{x:1540,y:480}],C.green,18,.25);ribbon(g,[{x:380,y:480},{x:720,y:330},{x:1200,y:330},{x:1540,y:480}],p,C.green,16);txt(g,'A shared context should move itself.',960,950,46,C.green,700);}
}
function connect(g:G,t:number){
 title(g,'THE TURN','Let agents talk.',C.green);const p=out(t/.9);const q=out((t-1.15)/1.25);const r=out((t-3.2)/1.2);
 agent(g,340,620,125,C.orange,'star',1+p*.15);agent(g,1580,620,125,C.blue,'chevron',1+p*.15);person(g,960,850,150,C.lilac,1-q*.8);
 const pts=[{x:470,y:620},{x:730,y:390},{x:960,y:300},{x:1190,y:390},{x:1450,y:620}];ribbon(g,pts,q,C.green,18);
 if(t>2.7){device(g,960,520,330,510,C.green,'phone',.9+r*.1);chip(g,960,530,330,'shared context',C.green,r,.02);}
 if(t>4.8){txt(g,'One thread. Many workspaces.',960,950,46,C.green,700);}
}
function world(g:G,t:number){
 title(g,'THE NETWORK','Across devices. Across regions.',C.blue);const p=out(t/1.2);const q=out((t-1.5)/2.3);const cx=960,cy=600,r=280+80*(1-p);g.save();g.translate(cx,cy);g.scale(.82+.18*p,.82+.18*p);g.strokeStyle='#A8C0D8';g.lineWidth=2;for(let i=-3;i<=3;i++){g.beginPath();g.ellipse(0,i*r*.25,r,r*.08,0,0,TAU);g.stroke();}for(let i=0;i<7;i++){g.beginPath();g.ellipse(0,0,Math.abs(Math.sin(t*.45+i*.45))*r,r,0,0,TAU);g.stroke();}g.fillStyle='#E7F0FA';g.beginPath();g.arc(0,0,r,0,TAU);g.fill();g.restore();
 const nodes=[{x:390,y:700,c:C.orange},{x:820,y:390,c:C.green},{x:1420,y:700,c:C.blue}];nodes.forEach((n,i)=>{dot(g,n.x,n.y,22,n.c);agent(g,n.x,n.y-95,58,n.c,i===1?'chevron':'star',.8);txt(g,['Laptop','Phone','Desktop'][i],n.x,n.y+76,27,C.muted,650);});
 stroke(g,[{x:390,y:700},{x:650,y:520},{x:820,y:390},{x:1110,y:520},{x:1420,y:700}],C.green,13,.28);ribbon(g,[{x:390,y:700},{x:650,y:520},{x:820,y:390},{x:1110,y:520},{x:1420,y:700}],q,C.green,16);
 if(t>4.7){const u=out((t-4.7)/1.4);rounded(g,650,820,620,74,37,'#FFFFFF',C.line,2,u);code(g,'P2P -> encrypted relay',690,858,27,C.green);}
}
function question(g:G,t:number){
 title(g,'THE HANDOFF','Ask the right agent.',C.blue);const q=out((t-1.2)/1.7);const r=out((t-3.3)/.65);
 rounded(g,210,350,1500,410,30,'#FFFFFF',C.line,3);rounded(g,260,400,640,310,22,C.terminal,'#FFFFFF',2);code(g,'> coopagents whoami',300,470,31,C.terminalMint);code(g,'> send_request --to codex',300,530,31,C.terminalBlue);code(g,'> Which field holds login status?',300,590,29,C.terminalText);agent(g,700,675,52,C.orange,'star',.7);
 const pts=[{x:930,y:555},{x:1120,y:360},{x:1450,y:555}];ribbon(g,pts,q,C.blue,15);chip(g,mix(930,1450,q),mix(555,555,q)-85,300,'Which field?',C.blue,q,.02);
 if(t>3.25){rounded(g,1030,400,600,310,22,C.sky,C.blue,3,r);code(g,'reply',1080,470,29,C.blue);code(g,'status',1080,555,68,C.green);code(g,'source: API agreement',1080,635,26,C.muted);dot(g,1510,650,28,C.green,r);}
}
function build(g:G,t:number){
 title(g,'THE RESULT','Answer becomes code.',C.green);const q=out((t-1.35)/1.3);const r=out((t-3.4)/.7);
 rounded(g,160,350,730,460,28,'#FFFFFF',C.line,3);code(g,'response.state',220,445,44,C.orange);stroke(g,[{x:220,y:510},{x:760,y:510}],C.coral,7);code(g,'response.status',220,585,44,C.green);stroke(g,[{x:220,y:650},{x:760,y:650}],C.mint,7);
 const x=mix(900,1010,q);stroke(g,[{x:890,y:580},{x,y:580}],C.green,18,.8);chip(g,mix(520,1370,q),280,390,'status + source',C.green,q,.02);
 rounded(g,1030,350,730,460,28,'#FFFFFF',C.line,3);code(g,'login.ts',1090,445,32,C.blue);code(g,'const status = response.status',1090,555,36,C.ink);stroke(g,[{x:1090,y:620},{x:1640,y:620}],C.mint,9);if(t>3.2){dot(g,1610,720,40,C.green,r);stroke(g,[{x:1585,y:720},{x:1603,y:738},{x:1640,y:695}],C.paper,8,r);}
}
function trace(g:G,t:number){
 title(g,'THE THREAD','Work stays attached.',C.green);const q=out((t-1.1)/1.4);const r=out((t-3.2)/1.1);
 const pts=[{x:300,y:620},{x:740,y:380},{x:1180,y:620},{x:1620,y:380}];stroke(g,pts,C.mint,24,.35);ribbon(g,pts,q,C.green,14);
 const labels=[['TASK',C.orange],['CODE',C.blue],['EVIDENCE',C.green],['DECISION',C.lilac]] as const;pts.forEach((pos,i)=>{const a=out((t-i*.22)/.5);dot(g,pos.x,pos.y,70,labels[i][1],a*.18);txt(g,labels[i][0],pos.x,pos.y,24,labels[i][1],800);});
 if(t>3.5){person(g,960,860,130,C.lilac,r);txt(g,'People keep the decision.',960,980,45,C.green,700);}
}
function relief(g:G,t:number){
 title(g,'THE RELEASE','Less relaying. More building.',C.green);const p=out(t/.8);const q=out((t-1.5)/1.2);const r=out((t-3.1)/1.2);
 agent(g,410,560,110,C.orange,'star',1+p*.12);agent(g,1510,560,110,C.blue,'chevron',1+p*.12);stroke(g,[{x:520,y:560},{x:760,y:300},{x:1160,y:300},{x:1400,y:560}],C.green,17,.2);ribbon(g,[{x:520,y:560},{x:760,y:300},{x:1160,y:300},{x:1400,y:560}],q,C.green,16);person(g,960,790,150,C.lilac,1-q*.75);if(t>3.8){rounded(g,690,705,540,105,52,'#FFFFFF',C.green,3,r);txt(g,'You decide.',960,758,45,C.green,800);}}
function brand(g:G,t:number){
 const p=out(t/.8);const q=out((t-1.0)/.9);g.save();g.translate(960,420);g.rotate((1-p)*-.7);for(let i=0;i<5;i++){g.globalAlpha=.13;g.strokeStyle=[C.blue,C.green,C.orange][i%3];g.lineWidth=9;g.beginPath();g.ellipse(0,0,180+i*45,100+i*27,i*.28+t*.2,0,TAU);g.stroke();}g.restore();if(t>.4){g.globalAlpha=q;txt(g,'Coopagents',960,660,150,C.ink,780);g.globalAlpha=1;}if(t>1.8){txt(g,'Less relaying. More building.',960,790,48,C.green,700);}if(t>2.8){code(g,'github.com/Weichenleeeee123/coopagents',960,940,25,C.blue,'center');}}

const scenes=[pain,connect,world,question,build,trace,relief,brand] as const;
export function drawAd(g:G,index:number,frame:number,energy:number){g.setTransform(1,0,0,1,0,0);g.clearRect(0,0,1920,1080);g.lineCap='round';g.lineJoin='round';g.save();const t=frame/60;const pulse=1+energy*.003;g.translate(960,540);g.scale(pulse,pulse);g.translate(-960,-540);backdrop(g,t,energy);scenes[index](g,t);g.restore();}
