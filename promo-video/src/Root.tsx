import { Composition, Folder } from "remotion";
import { Film } from "./Film";
import { AdScene } from "./ad/AdCut";
import { LaunchScene } from "./ad/LaunchFilm";

export const RemotionRoot = () => (
  <>
    <Composition
      id="CoopagentsPromo"
      component={Film}
      durationInFrames={2640}
      fps={60}
      width={1920}
      height={1080}
    />
    <Folder name="Launch-Scenes">
      <Composition
        id="Launch-Pain"
        component={LaunchScene}
        defaultProps={{ section: 0 }}
        durationInFrames={480}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Launch-Connect"
        component={LaunchScene}
        defaultProps={{ section: 1 }}
        durationInFrames={480}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Launch-Distance"
        component={LaunchScene}
        defaultProps={{ section: 2 }}
        durationInFrames={480}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Launch-Exchange"
        component={LaunchScene}
        defaultProps={{ section: 3 }}
        durationInFrames={480}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Launch-Payoff"
        component={LaunchScene}
        defaultProps={{ section: 4 }}
        durationInFrames={360}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Launch-Brand"
        component={LaunchScene}
        defaultProps={{ section: 5 }}
        durationInFrames={360}
        fps={60}
        width={1920}
        height={1080}
      />
    </Folder>
    <Folder name="Archive-54s">
      <Composition
        id="Ad-Pain"
        component={AdScene}
        defaultProps={{ scene: 0 }}
        durationInFrames={420}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Ad-Connect"
        component={AdScene}
        defaultProps={{ scene: 1 }}
        durationInFrames={420}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Ad-World"
        component={AdScene}
        defaultProps={{ scene: 2 }}
        durationInFrames={420}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Ad-Question"
        component={AdScene}
        defaultProps={{ scene: 3 }}
        durationInFrames={420}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Ad-Build"
        component={AdScene}
        defaultProps={{ scene: 4 }}
        durationInFrames={420}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Ad-Trace"
        component={AdScene}
        defaultProps={{ scene: 5 }}
        durationInFrames={360}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Ad-Relief"
        component={AdScene}
        defaultProps={{ scene: 6 }}
        durationInFrames={420}
        fps={60}
        width={1920}
        height={1080}
      />
      <Composition
        id="Ad-Brand"
        component={AdScene}
        defaultProps={{ scene: 7 }}
        durationInFrames={360}
        fps={60}
        width={1920}
        height={1080}
      />
    </Folder>
  </>
);
