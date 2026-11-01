import {Composition, Folder} from 'remotion';
import {Film} from './Film';
import {Opening} from './film/Opening';
import {Friction} from './film/Friction';
import {Connection} from './film/Connection';
import {Context} from './film/Context';
import {Dialogue} from './film/Dialogue';
import {Tasks} from './film/Tasks';
import {Evidence} from './film/Evidence';
import {Modes} from './film/Modes';
import {Control} from './film/Control';
import {Closing} from './film/Closing';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="CoopagentsPromo" component={Film} durationInFrames={5400} fps={30} width={1920} height={1080}/>
      <Folder name="Scenes">
        <Composition id="Opening" component={Opening} durationInFrames={450} fps={30} width={1920} height={1080}/>
        <Composition id="Friction" component={Friction} durationInFrames={540} fps={30} width={1920} height={1080}/>
        <Composition id="Connection" component={Connection} durationInFrames={600} fps={30} width={1920} height={1080}/>
        <Composition id="Context" component={Context} durationInFrames={600} fps={30} width={1920} height={1080}/>
        <Composition id="Dialogue" component={Dialogue} durationInFrames={600} fps={30} width={1920} height={1080}/>
        <Composition id="Tasks" component={Tasks} durationInFrames={600} fps={30} width={1920} height={1080}/>
        <Composition id="Evidence" component={Evidence} durationInFrames={600} fps={30} width={1920} height={1080}/>
        <Composition id="Modes" component={Modes} durationInFrames={510} fps={30} width={1920} height={1080}/>
        <Composition id="Control" component={Control} durationInFrames={450} fps={30} width={1920} height={1080}/>
        <Composition id="Closing" component={Closing} durationInFrames={450} fps={30} width={1920} height={1080}/>
      </Folder>
    </>
  );
};
