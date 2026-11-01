export type Vec3 = {x:number;y:number;z:number};
type Point = Vec3 & {scale:number};
type Surface = CanvasRenderingContext2D;
export const PALETTE = {ink:'#151916',paper:'#EFEFE7',lime:'#D7FF69',lilac:'#B8ACFF',blue:'#4C61FF',soft:'#AAC6B4'};
const tau=Math.PI*2;
const bound=(n:number)=>Math.max(0,Math.min(1,n));
const smooth=(n:number)=>{const x=bound(n);return x*x*(3-2*x);};
const lerp=(a:number,b:number,p:number)=>a+(b-a)*p;
const random=(n:number)=>{const a=Math.sin(n*78.233+12.91)*43758.5453;return a-Math.floor(a);};
const point=(x:number,y:number,z=0):Vec3=>({x,y,z});
const project=(v:Vec3,yaw:number,pitch:number,zoom=1):Point=>{
 const x=v.x*Math.cos(yaw)+v.z*Math.sin(yaw); const z0=-v.x*Math.sin(yaw)+v.z*Math.cos(yaw);
 const y=v.y*Math.cos(pitch)-z0*Math.sin(pitch); const z=v.y*Math.sin(pitch)+z0*Math.cos(pitch);
 const scale=1800/(1800+z)*zoom;return {x:960+x*scale,y:540+y*scale,z,scale};
};
const rgba=(hex:string,alpha:number)=>{const n=parseInt(hex.slice(1),16);return `rgba(${n>>16},${(n>>8)&255},${n&255},${alpha})`;};
const segment=(ctx:Surface,a:Point,b:Point,color:string,width=2,alpha=1)=>{ctx.globalAlpha=alpha;ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();ctx.globalAlpha=1;};

const orb=(ctx:Surface,p:Point,r:number,color:string,alpha=1)=>{
 const radius=r*p.scale; if(radius<.5)return;
 ctx.save();ctx.globalAlpha=alpha;
 if(radius>35){ctx.shadowBlur=radius*.48;ctx.shadowColor=rgba(color,.18);ctx.shadowOffsetY=radius*.15;}
 const grad=ctx.createRadialGradient(p.x-radius*.36,p.y-radius*.42,radius*.02,p.x+radius*.12,p.y+radius*.17,radius*1.14);
 grad.addColorStop(0,'#FFFFFF');grad.addColorStop(.12,color);grad.addColorStop(.68,color);grad.addColorStop(1,color===PALETTE.paper?'#8E978C':'#29352B');
 ctx.fillStyle=grad;ctx.beginPath();ctx.arc(p.x,p.y,radius,0,tau);ctx.fill();ctx.shadowBlur=0;
 if(radius>20){ctx.lineWidth=Math.max(1,radius*.035);ctx.strokeStyle='rgba(255,255,255,.55)';ctx.beginPath();ctx.ellipse(p.x-radius*.23,p.y-radius*.28,radius*.38,radius*.20,-.6,3.7,5.6);ctx.stroke();}
 ctx.restore();
};

const strokePath=(ctx:Surface,pts:Point[],color:string,width:number,alpha=1)=>{
 if(pts.length<2)return;ctx.save();ctx.globalAlpha=alpha;ctx.lineWidth=width;ctx.lineCap='round';ctx.lineJoin='round';ctx.strokeStyle=color;ctx.beginPath();
 pts.forEach((v,i)=>i?ctx.lineTo(v.x,v.y):ctx.moveTo(v.x,v.y));ctx.stroke();ctx.restore();
};

const glyph=(ctx:Surface,x:number,y:number,size:number,type:number,color:string,alpha=1)=>{
 ctx.save();ctx.translate(x,y);ctx.strokeStyle=color;ctx.fillStyle=color;ctx.globalAlpha=alpha;ctx.lineWidth=size*.07;ctx.lineCap='round';ctx.lineJoin='round';
 if(type===0){ctx.beginPath();ctx.moveTo(-size*.05,-size*.3);ctx.lineTo(-size*.3,0);ctx.lineTo(-size*.05,size*.3);ctx.moveTo(size*.05,-size*.3);ctx.lineTo(size*.3,0);ctx.lineTo(size*.05,size*.3);ctx.stroke();}
 else if(type===1){ctx.beginPath();ctx.moveTo(-size*.3,0);ctx.lineTo(-size*.06,size*.23);ctx.lineTo(size*.33,-size*.27);ctx.stroke();}
 else if(type===2){[-.24,0,.24].forEach(a=>{ctx.beginPath();ctx.arc(a*size,0,size*.065,0,tau);ctx.fill();});}
 else {ctx.beginPath();ctx.moveTo(-size*.22,-size*.25);ctx.lineTo(-size*.22,size*.25);ctx.moveTo(-size*.22,0);ctx.quadraticCurveTo(size*.22,0,size*.22,-size*.25);ctx.stroke();[[-.22,-.25],[-.22,.25],[.22,-.25]].forEach(([a,b])=>{ctx.beginPath();ctx.arc(a*size,b*size,size*.08,0,tau);ctx.fill();});}
 ctx.restore();
};

const tile=(ctx:Surface,p:Point,size:number,rotation:number,color:string,icon:number,depth=.0)=>{
 ctx.save();ctx.translate(p.x,p.y);ctx.rotate(rotation);ctx.scale(p.scale,p.scale);ctx.transform(1,depth,0,1,0,0);
 ctx.shadowColor='#0000002A';ctx.shadowBlur=28;ctx.shadowOffsetY=20;
 const gradient=ctx.createLinearGradient(-size/2,-size/2,size/2,size/2);gradient.addColorStop(0,color);gradient.addColorStop(1,color===PALETTE.ink?'#313A32':color);
 ctx.fillStyle=gradient;ctx.beginPath();ctx.roundRect(-size*.5,-size*.5,size,size,size*.19);ctx.fill();ctx.shadowBlur=0;ctx.shadowOffsetY=0;
 ctx.strokeStyle=color===PALETTE.ink?'#687869':'#FFFFFFAA';ctx.lineWidth=1.6;ctx.stroke();glyph(ctx,0,0,size*.63,icon,color===PALETTE.ink?PALETTE.lime:PALETTE.ink);ctx.restore();
};

const ambience=(ctx:Surface,t:number,dark:boolean,energy:number)=>{
 ctx.fillStyle=dark?PALETTE.ink:PALETTE.paper;ctx.fillRect(0,0,1920,1080);
 const grad=ctx.createRadialGradient(1120+Math.sin(t*.2)*200,480,0,960,540,1080);
 grad.addColorStop(0,dark?`rgba(98,131,71,${.10+energy*.04})`:'rgba(255,255,255,.68)');grad.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=grad;ctx.fillRect(0,0,1920,1080);
 ctx.fillStyle=dark?'#C4D0BD':'#596253';ctx.globalAlpha=.10;
 for(let i=0;i<95;i++){const x=random(i)*1920;const y=(random(i+251)*1080+t*(2+random(i)*5))%1080;ctx.fillRect(x,y,1.5,1.5);}ctx.globalAlpha=1;
};

const torus=(ctx:Surface,t:number,energy:number,outro=false)=>{
 const reveal=smooth(t/.9);const phase=outro?t*.42:t*.50;
 const zoom=outro?lerp(1.25,.8,smooth(t/4)):lerp(2.5,1,smooth(t/3));
 const yaw=.3+Math.sin(phase)*.4;const pitch=.33+Math.cos(t*.25)*.25;
 const pts=Array.from({length:210},(_,i)=>{const a=(-.76+((i/209)*5.24))*reveal;return {...project(point(Math.cos(a)*310,Math.sin(a)*310,Math.sin(a*2+phase)*66),yaw,pitch,zoom),a};});
 for(let ring=0;ring<4;ring++){const rt=380+ring*44+energy*10;const path=Array.from({length:180},(_,i)=>{const a=i/179*tau;return project(point(Math.cos(a)*rt,Math.sin(a)*rt,0),yaw+ring*.12,pitch,zoom);});strokePath(ctx,path,PALETTE.lime,1.3,.14-ring*.02);}
 for(let i=1;i<pts.length;i++){const light=(Math.sin(pts[i].a-1.1)+1)/2;const shade=Math.round(lerp(71,244,light));segment(ctx,pts[i-1],pts[i],`rgb(${shade},${Math.min(255,shade+8)},${shade})`,74*pts[i].scale,1);}
 for(let i=1;i<pts.length;i++){const light=(Math.sin(pts[i].a-1.2)+1)/2;segment(ctx,{...pts[i-1],y:pts[i-1].y-18*pts[i-1].scale},{...pts[i],y:pts[i].y-18*pts[i].scale},'#FFFFFF',2*pts[i].scale,light*.46);}
 const a=-.15+Math.sin(t)*.08;orb(ctx,project(point(Math.cos(a)*313,Math.sin(a)*313,90),yaw,pitch,zoom),43,PALETTE.lime);
 for(let i=0;i<7;i++){const angle=t*.28+i*tau/7;orb(ctx,project(point(Math.cos(angle)*560,Math.sin(angle)*440,Math.sin(angle)*200),yaw,pitch,zoom),8+i%3*4,i%2?PALETTE.paper:PALETTE.lime,.75);}
};

const agents=(ctx:Surface,t:number,energy:number)=>{
 const yaw=Math.sin(t*.23)*.28;const pitch=.2;const zoom=.88+Math.sin(t*.4)*.08;
 const colors=[PALETTE.ink,PALETTE.lime,PALETTE.lilac];
 const location=(i:number,time:number)=>{const phase=time*.45+i*tau/3;const convergence=smooth((time-8)/4);return point(Math.cos(phase)*lerp(620,270,convergence),Math.sin(phase)*270,Math.sin(phase*.7)*200);};
 for(let i=0;i<3;i++){
  const trail=Array.from({length:80},(_,k)=>project(location(i,t-k*.022),yaw,pitch,zoom));strokePath(ctx,trail,colors[i],3,.22);
 }
 const nodes=colors.map((color,i)=>({p:project(location(i,t),yaw,pitch,zoom),i,color})).sort((a,b)=>b.p.z-a.p.z);
 nodes.forEach(({p,i,color})=>{orb(ctx,p,105+energy*6,color);const label=project({...location(i,t),y:location(i,t).y+170},yaw,pitch,zoom);ctx.font='24px "Cascadia Code",Consolas';ctx.textAlign='center';ctx.fillStyle='#64705F';ctx.fillText(['Claude Code','Codex','Your team'][i],label.x,label.y);});
 const cube=enterAt(t,4,2);if(cube>0){tile(ctx,project(point(Math.sin(t*.6)*65,Math.cos(t*.7)*55,120),yaw,pitch,zoom),140*cube,t*.18,PALETTE.paper,0);}
};
const enterAt=(t:number,start:number,length:number)=>smooth((t-start)/length);

const network=(ctx:Surface,t:number,energy:number,large=false)=>{
 const count=large?110:18;const radius=large?590:500;const yaw=t*(large?.15:.21);const pitch=Math.sin(t*.13)*.3;
 const zoom=large?lerp(1.7,.98,smooth(t/4))+.06*Math.sin(t*.6):1.05+Math.sin(t*.3)*.08;
 const pts=Array.from({length:count},(_,i)=>{const phi=Math.acos(1-2*(i+.5)/count);const a=i*2.399963;const r=radius*(1+.025*Math.sin(t*2+i));return point(r*Math.sin(phi)*Math.cos(a),r*Math.cos(phi),r*Math.sin(phi)*Math.sin(a));});
 const p=pts.map(v=>project(v,yaw,pitch,zoom));const limit=large?320:570;
 for(let i=0;i<count;i++)for(let j=i+1;j<count;j++){
  const d=Math.hypot(pts[i].x-pts[j].x,pts[i].y-pts[j].y,pts[i].z-pts[j].z);
  if(d<limit){const lit=((t*.25+i*.13+j*.07)%1)<.12;const progress=enterAt(t,(i%7)*.1,.8);segment(ctx,p[i],{...p[j],x:lerp(p[i].x,p[j].x,progress),y:lerp(p[i].y,p[j].y,progress)},lit?PALETTE.lime:'#8A9B7D',lit?2.2:1.2,lit?.7:.17);if(lit){const q=(t*.5+i*.17)%1;orb(ctx,{x:lerp(p[i].x,p[j].x,q),y:lerp(p[i].y,p[j].y,q),z:0,scale:1},4,PALETTE.lime);}}
 }
 p.map((a,i)=>({a,i})).sort((a,b)=>b.a.z-a.a.z).forEach(({a,i})=>orb(ctx,a,(large?6:24)+(i%5===0?energy*8:0),i%5===0?PALETTE.lime:PALETTE.paper,.48+.5*bound((800-a.z)/1400)));
 if(!large)tile(ctx,project(point(0,0,0),yaw,pitch,zoom),195,Math.sin(t*.3)*.16,PALETTE.lime,3);
};

const context=(ctx:Surface,t:number,energy:number)=>{
 const spread=lerp(1.7,.7,smooth((t-2)/5));const yaw=-.48+Math.sin(t*.28)*.42;const pitch=.28;
 const panels=Array.from({length:11},(_,i)=>{const angle=i*tau/11+t*.2;const r=lerp(600,390,smooth((t-5)/3));return {p:point(Math.cos(angle)*r,Math.sin(angle)*250,Math.sin(angle)*280),i};});
 panels.map(({p,i})=>({v:project({...p,y:p.y*spread},yaw,pitch,1),i})).sort((a,b)=>b.v.z-a.v.z).forEach(({v,i})=>tile(ctx,v,144+energy*7,Math.sin(t*.3+i)*.20,i%4===0?PALETTE.lime:PALETTE.paper,i%4,.06));
 const center=project(point(0,0,-80),yaw,pitch,1);orb(ctx,center,90,PALETTE.ink);
 for(let i=0;i<6;i++){const a=i*tau/6+t*.2;const pts=Array.from({length:70},(_,n)=>{const q=n/69;return project(point(Math.cos(a)*q*600,Math.sin(a)*q*300,Math.sin(q*Math.PI)*190),yaw,pitch,1);});strokePath(ctx,pts,'#698A5A',1.5,.3);const q=(t*.7+i*.17)%1;const at=pts[Math.floor(q*69)];orb(ctx,at,5,PALETTE.ink);}
};

const dialogue=(ctx:Surface,t:number,energy:number)=>{
 const yaw=Math.sin(t*.12)*.22;const pitch=.12;const zoom=1+Math.sin(t*.25)*.07;
 const left=project(point(-620,0,0),yaw,pitch,zoom);const right=project(point(620,0,0),yaw,pitch,zoom);
 orb(ctx,left,115,PALETTE.paper);orb(ctx,right,115,PALETTE.lime);
 for(let lane=0;lane<2;lane++){
  const pts=Array.from({length:100},(_,i)=>{const q=i/99;return project(point(lerp(-620,620,q),Math.sin(q*Math.PI)*(lane?-300:300),Math.sin(q*Math.PI)*-120),yaw,pitch,zoom);});strokePath(ctx,pts,lane?PALETTE.lime:'#B6BCB1',2.3,.48);
  for(let i=0;i<5;i++){const q=(t*.14+i*.2)%1;const position=lane?1-q:q;const at=pts[Math.floor(position*99)];ctx.save();ctx.translate(at.x,at.y);ctx.rotate(Math.cos(position*Math.PI)*(lane?-.6:.6));ctx.fillStyle=lane?PALETTE.lime:PALETTE.paper;ctx.shadowColor=rgba(ctx.fillStyle as string,.2);ctx.shadowBlur=20;ctx.beginPath();ctx.roundRect(-52,-30,104+energy*9,60,28);ctx.fill();ctx.shadowBlur=0;glyph(ctx,0,0,53,2,PALETTE.ink);ctx.restore();}
 }
};

const work=(ctx:Surface,t:number,energy:number)=>{
 const yaw=-.32+Math.sin(t*.16)*.22;const pitch=.55+Math.sin(t*.24)*.16;const zoom=1.08+Math.sin(t*.2)*.12;
 const grid=Array.from({length:28},(_,i)=>{const col=i%7,row=Math.floor(i/7);const wave=Math.sin(t*2-col*.52-row*.55);return {p:point((col-3)*205,(row-1.5)*200,wave*90),i};});
 const cameraSlide=Math.sin(t*.19)*90;
 grid.map(({p,i})=>({p:project({...p,x:p.x+cameraSlide},yaw,pitch,zoom),i})).sort((a,b)=>b.p.z-a.p.z).forEach(({p,i})=>{const active=(Math.floor(t*2.1)+i)%11<5;tile(ctx,p,140+energy*(active?10:0),Math.sin(t*.45+i*.12)*.06,active?PALETTE.lime:PALETTE.ink,active?1:0);});
};

const evidence=(ctx:Surface,t:number,energy:number)=>{
 const yaw=-.2+Math.sin(t*.2)*.2;const pitch=.24;const zoom=lerp(1.4,.95,smooth(t/5));
 const count=6;const drift=Math.sin(t*.23)*160;
 const pts=Array.from({length:count},(_,i)=>point((i-2.5)*270+drift,Math.sin(i*.8+t*.25)*160,(i-2.5)*80));
 const p=pts.map(v=>project(v,yaw,pitch,zoom));
 for(let i=1;i<count;i++){
  const curve=Array.from({length:70},(_,j)=>{const q=j/69;return project(point(lerp(pts[i-1].x,pts[i].x,q),lerp(pts[i-1].y,pts[i].y,q)+Math.sin(q*Math.PI)*-70,lerp(pts[i-1].z,pts[i].z,q)),yaw,pitch,zoom);});strokePath(ctx,curve,PALETTE.lime,4,.65);const q=(t*.7+i*.13)%1;orb(ctx,curve[Math.floor(q*69)],7,PALETTE.lime);
 }
 p.forEach((v,i)=>{tile(ctx,v,146+energy*6,Math.sin(t*.3+i)*.07,i===2?PALETTE.lime:PALETTE.ink,i%4);ctx.font='24px "Cascadia Code",Consolas';ctx.textAlign='center';ctx.fillStyle='#B5C3A9';ctx.fillText(['task','branch','commit','PR','review','release'][i],v.x,v.y+125*v.scale);});
};

const cursor=(ctx:Surface,x:number,y:number,size:number,angle:number)=>{
 ctx.save();ctx.translate(x,y);ctx.rotate(angle);ctx.scale(size,size);ctx.shadowBlur=28;ctx.shadowOffsetY=15;ctx.shadowColor='#00000035';ctx.fillStyle=PALETTE.ink;ctx.strokeStyle='#F7F8ED';ctx.lineWidth=.025;ctx.beginPath();ctx.moveTo(-.38,-.5);ctx.lineTo(.42,.06);ctx.lineTo(.07,.15);ctx.lineTo(.23,.48);ctx.lineTo(.06,.56);ctx.lineTo(-.10,.23);ctx.lineTo(-.34,.48);ctx.closePath();ctx.fill();ctx.stroke();ctx.restore();
};

const control=(ctx:Surface,t:number,energy:number)=>{
 const click=smooth((t-3)/1.1);const yaw=.12*Math.sin(t*.3);const pitch=.28;
 for(let ring=0;ring<4;ring++){const radius=200+ring*105+(1-click)*100;const pts=Array.from({length:150},(_,i)=>{const a=i/149*tau;return project(point(Math.cos(a)*radius,Math.sin(a)*radius,0),yaw,pitch,1);});strokePath(ctx,pts,'#86997F',ring===0?3:1.4,ring===0?.6:.28);}
 const center=project(point(0,0,0),yaw,pitch,1);orb(ctx,center,140+energy*8,PALETTE.lime);glyph(ctx,center.x,center.y,145,click>.5?1:2,PALETTE.ink);
 for(let i=0;i<8;i++){const a=t*.22+i*tau/8;tile(ctx,project(point(Math.cos(a)*505,Math.sin(a)*360,Math.sin(a)*150),yaw,pitch,1),84,Math.sin(a)*.15,i%2?PALETTE.paper:PALETTE.lime,click>.5?1:0);}
 cursor(ctx,lerp(1500,1080,smooth(t/3))+Math.sin(t*.8)*8,lerp(870,600,smooth(t/3))+Math.cos(t*.6)*8,210*(1-Math.sin(click*Math.PI)*.08),-.13);
};

export function drawMotion(ctx:Surface,mode:number,t:number,low:number,energy:number,high:number){
 ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,1920,1080);ctx.lineCap='round';ctx.lineJoin='round';
 const dark=[0,2,4,6,7,9].includes(mode);ambience(ctx,t,dark,energy);
 ctx.save();
 const pulse=1+low*.009;ctx.translate(960,540);ctx.scale(pulse,pulse);ctx.translate(-960,-540);
 if(mode===0)torus(ctx,t,low);
 else if(mode===1)agents(ctx,t,low);
 else if(mode===2)network(ctx,t,low);
 else if(mode===3)context(ctx,t,low);
 else if(mode===4)dialogue(ctx,t,low);
 else if(mode===5)work(ctx,t,low);
 else if(mode===6)evidence(ctx,t,low);
 else if(mode===7)network(ctx,t,low,true);
 else if(mode===8)control(ctx,t,low);
 else torus(ctx,t,low,true);
 ctx.restore();
 // Short high-frequency pinlights: actual music energy, never a full-screen flash.
 ctx.globalAlpha=high*.28;ctx.fillStyle=dark?PALETTE.lime:PALETTE.ink;
 for(let i=0;i<8;i++){const x=80+random(i+23)*1760,y=120+random(i+91)*840;ctx.fillRect(x-2,y,4,1);ctx.fillRect(x,y-2,1,4);}ctx.globalAlpha=1;
}
