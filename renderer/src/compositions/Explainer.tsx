import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { ProjectData, SceneData } from "../schemas/project";
import { Primitive } from "../scenes/primitives";
import { theme } from "../themes/tokens";

const SceneTransition: React.FC<{
  scene: SceneData;
  children: React.ReactNode;
}> = ({ scene, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const duration = Math.max(1, Math.round(scene.duration * fps));
  const transitionFrames = Math.max(
    1,
    Math.min(Math.round(fps * 0.3), Math.floor(duration / 2)),
  );
  if (scene.transition === "cut") return <>{children}</>;
  const opacity = interpolate(
    frame,
    [0, transitionFrames, duration - transitionFrames, duration],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const slide =
    scene.transition === "slide"
      ? interpolate(frame, [0, transitionFrames], [90, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 0;
  return (
    <AbsoluteFill style={{ opacity, transform: `translateX(${slide}px)` }}>
      {children}
    </AbsoluteFill>
  );
};

export const Explainer: React.FC<ProjectData> = (data) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;
  const activeCue = data.captions.find(
    (cue) => currentTime >= cue.start && currentTime < cue.end,
  );
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 80% 12%, #183866 0, ${theme.background} 48%)`,
        color: theme.text,
        fontFamily: theme.font,
      }}
    >
      {data.audioPath ? <Audio src={staticFile(data.audioPath)} /> : null}
      {data.scenes.map((scene) => (
        <Sequence
          key={scene.scene_id}
          from={Math.round(scene.start_time * data.fps)}
          durationInFrames={Math.max(1, Math.round(scene.duration * data.fps))}
          premountFor={data.fps}
        >
          <SceneTransition scene={scene}>
            <Primitive scene={scene} />
          </SceneTransition>
        </Sequence>
      ))}
      {activeCue ? (
        <div
          data-caption-index={activeCue.index}
          style={{
            position: "absolute",
            left: 62,
            right: 62,
            bottom: 145,
            minHeight: 170,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
            padding: "22px 34px",
            borderRadius: 24,
            background: "#020817ed",
            fontSize: 42,
            fontWeight: 700,
            lineHeight: 1.22,
            overflowWrap: "anywhere",
            boxShadow: "0 10px 36px #0008",
          }}
        >
          {activeCue.text}
        </div>
      ) : null}
      {data.watermarked ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transform: "rotate(-24deg)",
            fontSize: 116,
            fontWeight: 700,
            letterSpacing: 8,
            color: "#ffffff25",
            border: "14px solid #ffffff18",
          }}
        >
          UNREVIEWED
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
