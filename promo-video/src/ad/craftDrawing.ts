import {C} from '../story/palette';

type G=CanvasRenderingContext2D;
type P={x:number;y:number};
const TAU=Math.PI*2;
const clamp=(v:number)=>Math.max(0,Math.min(1,v));
const smooth=(v:number)=>{const t=clamp(v);return t*t*(3-2*t);};
const out=(v:number)=>1-(1-clamp(v))**3;
const mix=(a:number,b:number,t:number)=>a+(b-a)*t;
const sans='"Segoe UI Variable","Segoe UI",sans-serif';
const mono='"Cascadia Code",Consolas,monospace';

function text(g:G,value:string,x:number,y:number,size:number,color:string=C.ink,weight=650,align:CanvasTextAlign='center'){
 g.save();g.fillStyle=color;g.font=`${weight} ${size}px ${sans}`;g.textAlign=align;g.textBaseline='middle';g.fillText(value,x,y);g.restore();
}
function code(g:G,value:string,x:number,y:number,size:number,color:string=C.ink,align:CanvasTextAlign='center'){
 g.save();g.fillStyle=color;g.font=`500 ${size}px ${mono}`;g.textAlign=align;g.textBaseline='middle';g.fillText(value,x,y);g.restore();
}
function roundRect(g:G,x:number,y:number,w:number,h:number,r:number,fill:string,stroke?:string,line=2,alpha=1){
 g.save();g.globalAlpha*=alpha;g.beginPath();g.roundRect(x,y,w,h,r);if(fill){g.fillStyle=fill;g.fill();}if(stroke){g.strokeStyle=stroke;g.lineWidth=line;g.stroke();}g.restore();
}
function line(g:G,a:P,b:P,color:string,width=4,alpha=1){g.save();g.globalAlpha*=alpha;g.strokeStyle=color;g.lineWidth=width;g.lineCap='round';g.beginPath();g.moveTo(a.x,a.y);g.lineTo(b.x,b.y);g.stroke();g.restore();}
function dot(g:G,x:number,y:number,r:number,color:string,alpha=1){g.save();g.globalAlpha*=alpha;g.fillStyle=color;g.beginPath();g.arc(x,y,r,0,TAU);g.fill();g.restore();}
function shadow(g:G,blur:number,color:string){g.shadowBlur=blur;g.shadowColor=color;}
function person(g:G,x:number,y:number,s:number,color:string,alpha=1){g.save();g.globalAlpha*=alpha;dot(g,x,y-s*.58,s*.18,color);g.fillStyle=color;g.beginPath();g.moveTo(x-s*.46,y+s*.42);g.quadraticCurveTo(x-s*.42,y-s*.05,x,y-s*.05);g.quadraticCurveTo(x+s*.42,y-s*.05,x+s*.46,y+s*.42);g.closePath();g.fill();g.restore();}
function device(g:G,x:number,y:number,w:number,h:number,kind:'laptop'|'desktop'|'phone',accent:string,scale=1){
 g.save();g.translate(x,y);g.scale(scale,scale);shadow(g,38,'#20212418');
 if(kind==='phone'){
  roundRect(g,-w/2,-h/2,w,h,28,C.panel,accent,5);roundRect(g,-w*.33,-h*.29,w*.66,h*.58,14,C.sky,'#FFFFFF',2);dot(g,0,-h*.37,4,accent);line(g,{x:0,y:h*.36},{x:0,y:h*.36},accent,4,.8);
 }else{
  roundRect(g,-w/2,-h/2,w,h,18,C.panel,accent,6);roundRect(g,-w*.42,-h*.34,w*.84,h*.61,10,kind==='laptop'?C.coral:'#E8F0FF','#FFFFFF',3,.98);
  if(kind==='desktop'){line(g,{x:-w*.15,y:h*.3},{x:-w*.15,y:h*.5},accent,6);line(g,{x:-w*.3,y:h*.5},{x:w*.3,y:h*.5},accent,6);}else{line(g,{x:-w*.56,y:h*.5},{x:w*.56,y:h*.5},accent,6);}
 }
 g.restore();
}
function capsule(g:G,x:number,y:number,w:number,h:number,fill:string,label:string,progress=1,angle=0){
 g.save();g.translate(x,y);g.rotate(angle);shadow(g,26,fill+'55');roundRect(g,-w/2,-h/2,w,h,h/2,fill);dot(g,-w*.33,0,10,C.paper,.9);text(g,label,-w*.03,0,28,C.paper,750,'center');line(g,{x:w*.25,y:0},{x:w*.37,y:0},C.paper,5,.75);g.restore();
 if(progress<1){line(g,{x:x-w*.38,y:y+h*.72},{x:x-w*.38+w*.76*progress,y:y+h*.72},fill,7,.8);}
}
function thread(g:G,points:P[],t:number,color:string,width=12){
 g.save();g.lineCap='round';g.lineJoin='round';g.strokeStyle=color;g.lineWidth=width;g.beginPath();points.forEach((p,i)=>i?g.lineTo(p.x,p.y):g.moveTo(p.x,p.y));g.stroke();
 const idx=Math.floor(clamp(t)*Math.max(1,points.length-1));const p=points[idx]??points[points.length-1];dot(g,p.x,p.y,20,color,.95);dot(g,p.x,p.y,8,C.paper,.9);g.restore();
}
function bg(g:G,t:number,energy:number){
 const grad=g.createLinearGradient(0,0,1920,1080);grad.addColorStop(0,C.paper);grad.addColorStop(.55,'#FFFFFF');grad.addColorStop(1,'#F2F6FF');g.fillStyle=grad;g.fillRect(0,0,1920,1080);
 const glow=g.createRadialGradient(350,180,10,350,180,520);glow.addColorStop(0,C.coral+'90');glow.addColorStop(1,C.coral+'00');g.fillStyle=glow;g.fillRect(0,0,1000,700);
 const glow2=g.createRadialGradient(1700,890,10,1700,890,600);glow2.addColorStop(0,C.mint+'AA');glow2.addColorStop(1,C.mint+'00');g.fillStyle=glow2;g.fillRect(900,400,1020,680);
 for(let i=0;i<24;i++){const x=(i*211+t*26)%1920;const y=100+((i*97)%840);dot(g,x,y,1.5,C.blue,.08+energy*.03);}
}
function shotPain(g:G,t:number){
 const humanX=mix(990,1180,smooth((t-3.1)/1.2));
 text(g,'You became the relay.',120,125,52,C.muted,650,'left');
 text(g,'COPY.  PASTE.  EXPLAIN.',120,190,90,C.ink,780,'left');
 device(g,300,610,500,340,'laptop',C.orange,1.05);device(g,1620,610,500,340,'desktop',C.blue,1.05);
 person(g,humanX,680,180,C.lilac,1);
 capsule(g,mix(330,980,smooth((t-.7)/1.5)),470,470,86,C.orange,'new requirement',smooth((t-.7)/1.5),-.05);
 capsule(g,mix(980,1590,smooth((t-2.4)/1.6)),470,470,86,C.blue,'same requirement',smooth((t-2.4)/1.6),.03);
 line(g,{x:490,y:400},{x:humanX-150,y:520},C.orange,10,.28);line(g,{x:humanX+150,y:520},{x:1430,y:400},C.blue,10,.28);
 if(t>3.7){text(g,'One person. Two conversations.',960,940,42,C.muted,650);}
}
function shotConnection(g:G,t:number){
 const threadP=smooth((t-1.0)/2.5);const cam=1+0.04*smooth((t-2.6)/1.4);
 g.save();g.translate(960,540);g.scale(cam,cam);g.translate(-960,-540);
 text(g,'One context thread.',120,125,52,C.muted,650,'left');
 text(g,'ACROSS AGENTS. DEVICES. REGIONS.',120,190,72,C.ink,780,'left');
 device(g,300,590,380,280,'laptop',C.orange,.95);device(g,960,350,320,500,'phone',C.green,.88);device(g,1600,590,380,280,'desktop',C.blue,.95);
 const pts=[{x:490,y:590},{x:710,y:430},{x:960,y:350},{x:1210,y:430},{x:1430,y:590}];
 line(g,pts[0],pts[1],C.coral,18,.2);line(g,pts[1],pts[2],C.mint,18,.2);line(g,pts[2],pts[3],C.mint,18,.2);line(g,pts[3],pts[4],C.sky,18,.2);
 thread(g,pts,threadP,C.green,14);
 capsule(g,mix(490,960,threadP),mix(590,350,threadP),360,76,C.green,'shared context',threadP,-.12+threadP*.24);
 if(t>3.8){text(g,'The message becomes infrastructure.',960,950,42,C.green,700);}
 g.restore();
}
function shotPayoff(g:G,t:number){
 const reveal=out(t/.7);const codeIn=out((t-1.0)/.8);const checkIn=out((t-2.55)/.55);const humanIn=out((t-3.6)/.7);
 text(g,'From relay to result.',120,125,52,C.muted,650,'left');
 text(g,'ASK. ANSWER. BUILD.',120,190,90,C.ink,780,'left');
 roundRect(g,170,345,740,410,28,C.panel,C.line,3);code(g,'response.status',230,430,54,C.orange,'left');line(g,{x:230,y:495},{x:760,y:495},C.coral,8,.8);code(g,'status',230,555,74,C.green,'left');code(g,'source: api-agreement',230,640,32,C.muted,'left');
 roundRect(g,1030,345,720,410,28,C.panel,C.line,3);code(g,'login.ts',1090,420,34,C.blue,'left');code(g,'const status = response.status',1090,500,38,C.ink,'left');line(g,{x:1090,y:545},{x:1640,y:545},C.mint,9,.9);code(g,'verified change',1090,630,34,C.green,'left');
 const lineX=mix(910,1030,codeIn);line(g,{x:910,y:520},{x:lineX,y:520},C.green,18,.8);capsule(g,mix(550,1320,codeIn),270,360,76,C.green,'answer + source',codeIn,.02);
 if(checkIn){dot(g,1630,700,52,C.green,checkIn);line(g,{x:1600,y:700},{x:1625,y:725},C.paper,9,checkIn);line(g,{x:1625,y:725},{x:1670,y:670},C.paper,9,checkIn);}
 person(g,960,910,120,C.lilac,humanIn);text(g,'You decide.',960,1020,46,C.green,700);
 if(reveal){thread(g,[{x:550,y:310},{x:960,y:270},{x:1320,y:310}],reveal,C.green,10);}
}
export function drawCraft(g:G,t:number,energy:number){
 g.setTransform(1,0,0,1,0,0);g.clearRect(0,0,1920,1080);g.lineCap='round';g.lineJoin='round';bg(g,t,energy);
 const local=((t%15)+15)%15;
 if(local<5){shotPain(g,local);}
 else if(local<10){shotConnection(g,local-5);}
 else {shotPayoff(g,local-10);}
}
