export const EASE=(n:number)=>{const x=Math.max(0,Math.min(1,n));return x*x*(3-2*x);};
export const TRAVEL=24;
export type MotionStyle='dock'|'zoom'|'orbit'|'lift'|'paper';
export const MOTIONS:readonly MotionStyle[]=['zoom','zoom','orbit','dock','zoom','zoom','dock','dock','zoom','paper','paper','orbit','paper','zoom','lift','dock','paper','lift','lift','zoom','lift','dock','zoom','zoom','lift','zoom','orbit','paper','orbit','zoom','dock'];
export function stageMotion(id:number,frame:number,duration:number){
 const enter=EASE(frame/TRAVEL);const leave=EASE((frame-duration)/TRAVEL);const direction=id%2?1:-1;
 const kind=MOTIONS[id];
 let x=0,y=0,rotate=0,scale=1,tilt=0;
 if(kind==='dock'){y=(1-enter)*14-leave*18;scale=1+.012*(frame/Math.max(1,duration));}
 if(kind==='zoom'){scale=.94+enter*.06+leave*.085;x=direction*((1-enter)*35-leave*45);}
 if(kind==='orbit'){x=direction*((1-enter)*180-leave*190);rotate=direction*((1-enter)*4-leave*5);tilt=direction*((1-enter)*10-leave*12);}
 if(kind==='lift'){y=(1-enter)*110-leave*100;scale=.97+enter*.03;tilt=(1-enter)*-7+leave*7;}
 if(kind==='paper'){x=direction*((1-enter)*100-leave*70);rotate=direction*((1-enter)*-5+leave*3);y=(1-enter)*30;}
 const settle=EASE((frame-TRAVEL)/Math.max(1,duration-TRAVEL));
 if(kind!=='dock'){scale+=settle*.025;x+=direction*settle*18;}
 return {transform:`perspective(2300px) translate(${x}px,${y}px) rotate(${rotate}deg) rotateY(${tilt}deg) scale(${scale})`,opacity:Math.min(1,enter*2.8)*(1-leave)};
}
