import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { ProjectData, SceneData } from "../schemas/project";
import {
  PacingProvider,
  captionMotionFor,
  transitionFramesFor,
  transitionPresentationFor,
} from "../pacing/rhythm";
import { RetentionOverlay } from "../engagement/RetentionOverlay";
import { Primitive } from "../scenes/primitives";
import { SafeZoneProvider, useSafeZone } from "../safe-zone";
import { getTheme } from "../themes/tokens";

const CaptionCard: React.FC<{
  cue: ProjectData["captions"][number];
  currentTime: number;
  tokens: ReturnType<typeof getTheme>;
  themeName: ProjectData["theme"];
}> = ({ cue, currentTime, tokens, themeName }) => {
  const motion = captionMotionFor(currentTime, cue.start, cue.end);
  const safeZone = useSafeZone();
  return (
    <div
      data-caption-index={cue.index}
      style={{
        position: "absolute",
        left: Math.max(62, safeZone.left),
        right: Math.max(62, safeZone.right),
        bottom: Math.max(145, safeZone.bottom),
        minHeight: 170,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: "22px 34px",
        borderRadius: 24,
        border: `2px solid ${tokens.panelBorder}`,
        background:
          themeName === "technical-editorial"
            ? "#172033f2"
            : `${tokens.background}f2`,
        color: "#f7f9ff",
        fontSize: 42,
        fontWeight: 700,
        lineHeight: 1.22,
        overflow: "hidden",
        overflowWrap: "anywhere",
        boxShadow: "0 10px 36px #0008",
        opacity: motion.opacity,
        transform: `translateY(${motion.translateY}px)`,
        zIndex: 20,
      }}
    >
      {cue.text}
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          left: 0,
          bottom: 0,
          width: `${motion.progress * 100}%`,
          height: 6,
          background: `linear-gradient(90deg, ${tokens.accent}, ${tokens.warning})`,
        }}
      />
    </div>
  );
};

const SceneTransition: React.FC<{
  scene: SceneData;
  pacing: ProjectData["pacing"];
  children: React.ReactNode;
}> = ({ scene, pacing, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const transitionFrames = transitionFramesFor(scene, fps, pacing);
  // Entry-only transitions keep the preceding shot visually complete until the
  // cut. Fading both ends created a blank flash between adjacent sequences.
  const presentation = transitionPresentationFor(
    frame,
    transitionFrames,
    scene.transition,
    scene.motion,
    scene.order === 0,
  );
  return (
    <AbsoluteFill
      style={{
        opacity: presentation.opacity,
        transform: `translateX(${presentation.translateX}px)`,
      }}
    >
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
  const tokens = getTheme(data.theme);
  return (
    <AbsoluteFill
      style={{
        background: tokens.backgroundCss,
        color: tokens.text,
        fontFamily: tokens.font,
      }}
    >
      <PacingProvider preset={data.pacing}>
        <SafeZoneProvider insets={data.safeZone}>
          {data.audioPath ? <Audio src={staticFile(data.audioPath)} /> : null}
          {data.soundDesignPath ? (
            <Audio src={staticFile(data.soundDesignPath)} />
          ) : null}
          {data.scenes.map((scene) => (
            <Sequence
              key={scene.scene_id}
              from={Math.round(scene.start_time * data.fps)}
              durationInFrames={Math.max(
                1,
                Math.round(scene.duration * data.fps),
              )}
              premountFor={data.fps}
            >
              <SceneTransition scene={scene} pacing={data.pacing}>
                <Primitive scene={scene} themeName={data.theme} />
              </SceneTransition>
            </Sequence>
          ))}
          <RetentionOverlay retention={data.retention} themeName={data.theme} />
          {activeCue ? (
            <CaptionCard
              cue={activeCue}
              currentTime={currentTime}
              tokens={tokens}
              themeName={data.theme}
            />
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
                zIndex: 30,
              }}
            >
              UNREVIEWED
            </div>
          ) : null}
        </SafeZoneProvider>
      </PacingProvider>
    </AbsoluteFill>
  );
};
