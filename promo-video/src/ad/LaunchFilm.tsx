import { useLayoutEffect, useRef } from "react";
import {
  AbsoluteFill,
  Img,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Audio } from "@remotion/media";
import { drawLaunch, sat } from "./launchArt";

export const LaunchScene = ({ section }: { section: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ref = useRef<HTMLCanvasElement>(null);
  const seconds = frame / fps;
  const duration = section < 4 ? 8 : 6;
  // Both halves travel left at matching velocity; cut before motion settles.
  const enter = section === 0 ? 0 : 220 * (1 - sat(seconds / 0.25)) ** 4;
  const exit =
    section === 5 ? 0 : 220 * sat((seconds - duration + 0.25) / 0.25) ** 4;
  useLayoutEffect(() => {
    const g = ref.current?.getContext("2d");
    if (g) drawLaunch(g, section, seconds);
  }, [section, seconds]);
  return (
    <AbsoluteFill
      style={{
        transform: `translateX(${enter - exit}px)`,
        filter: `blur(${(Math.max(enter, exit) / 220) * 3}px)`,
      }}
    >
      <canvas
        ref={ref}
        width={1920}
        height={1080}
        style={{ width: "100%", height: "100%" }}
      />
      {section === 5 && seconds >= 2 ? (
        <Img
          src={staticFile("coopagents-icon.png")}
          style={{
            position: "absolute",
            left: 860,
            top: 235,
            width: 200,
            height: 200,
            borderRadius: 46,
            opacity: sat((seconds - 2) / 0.4),
            boxShadow: "0 28px 65px #25314425",
          }}
        />
      ) : null}
    </AbsoluteFill>
  );
};

export const LaunchFilm = () => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: "#F7F8FA" }}>
      <Sequence
        durationInFrames={8 * fps}
        name="01 / The human messenger"
        premountFor={fps}
      >
        <LaunchScene section={0} />
      </Sequence>
      <Sequence
        from={8 * fps}
        durationInFrames={8 * fps}
        name="02 / Let agents talk"
        premountFor={fps}
      >
        <LaunchScene section={1} />
      </Sequence>
      <Sequence
        from={16 * fps}
        durationInFrames={8 * fps}
        name="03 / Different devices and places"
        premountFor={fps}
      >
        <LaunchScene section={2} />
      </Sequence>
      <Sequence
        from={24 * fps}
        durationInFrames={8 * fps}
        name="04 / Question to answer to code"
        premountFor={fps}
      >
        <LaunchScene section={3} />
      </Sequence>
      <Sequence
        from={32 * fps}
        durationInFrames={6 * fps}
        name="05 / People keep the decision"
        premountFor={fps}
      >
        <LaunchScene section={4} />
      </Sequence>
      <Sequence
        from={38 * fps}
        durationInFrames={6 * fps}
        name="06 / Coopagents"
        premountFor={fps}
      >
        <LaunchScene section={5} />
      </Sequence>
      <Audio
        src={staticFile("funk-caravan.m4a")}
        durationInFrames={44 * fps}
        volume={(f) =>
          0.85 *
          Math.min(sat(f / (fps * 0.12)), sat((44 * fps - f) / (3 * fps)))
        }
        name="Funk Caravan / 44 seconds / 3-second fade"
        premountFor={fps}
      />
    </AbsoluteFill>
  );
};
