import {AbsoluteFill} from 'remotion';
import type {TransitionPresentation, TransitionPresentationComponentProps} from '@remotion/transitions';

type Props={direction:1|-1};
const MatchMove=({children,presentationDirection,presentationProgress,passedProps}:TransitionPresentationComponentProps<Props>)=>{
 const entering=presentationDirection==='entering';const p=presentationProgress;
 const scale=entering?.94+p*.06:1+p*.06;
 const shift=passedProps.direction*(entering?56*(1-p):-56*p);
 return <AbsoluteFill style={{opacity:entering?Math.min(1,p*2):1,transform:`translateX(${shift}px) scale(${scale})`}}>{children}</AbsoluteFill>;
};
export const matchMove=(direction:1|-1=1):TransitionPresentation<Props>=>({component:MatchMove,props:{direction}});
