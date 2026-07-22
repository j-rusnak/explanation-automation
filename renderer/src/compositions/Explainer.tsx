import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {
  activeEmphasisTokenIndexes,
  captionTokenPresentation,
} from "../captions/emphasis";
import type {
  CaptionTokenData,
  ProjectData,
  SceneData,
} from "../schemas/project";
import {
  PacingProvider,
  captionMotionFor,
  kineticEntrancePresentationFor,
  type KineticEntrancePresentation,
  transitionFramesFor,
  transitionPresentationFor,
} from "../pacing/rhythm";
import { RetentionOverlay } from "../engagement/RetentionOverlay";
import { Primitive } from "../scenes/primitives";
import { ThemeGrammarProvider, isKineticPopTheme } from "../scenes/shared";
import { SafeZoneProvider, useSafeZone } from "../safe-zone";
import { getTheme } from "../themes/tokens";

export const kineticSceneBoundaryStyleFor = (
  entrance: KineticEntrancePresentation,
): Pick<React.CSSProperties, "clipPath" | "transform"> => ({
  // Intentionally omit scale and vertical translation. Once the short reveal
  // window ends, this evaluates to a stable identity transform for every frame.
  transform: `translate3d(${entrance.translateX}px, 0, 0)`,
  clipPath: `inset(0 ${entrance.revealInsetRight}% 0 ${entrance.revealInsetLeft}%)`,
});

export const activeKeywordTokenIndexFor = (
  tokens: readonly CaptionTokenData[],
  activeTokenIndexes: readonly number[],
): number | null => {
  let selected: number | null = null;
  let selectedLength = -1;
  for (const tokenIndex of activeTokenIndexes) {
    const token = tokens[tokenIndex];
    if (!token) continue;
    const meaningfulLength = token.text.replace(/[^\p{L}\p{N}]/gu, "").length;
    if (meaningfulLength > selectedLength) {
      selected = tokenIndex;
      selectedLength = meaningfulLength;
    }
  }
  return selected;
};

const CaptionCard: React.FC<{
  cue: ProjectData["captions"][number];
  currentTime: number;
  tokens: ReturnType<typeof getTheme>;
  themeName: ProjectData["theme"];
}> = ({ cue, currentTime, tokens, themeName }) => {
  const motion = captionMotionFor(currentTime, cue.start, cue.end);
  const safeZone = useSafeZone();
  const kinetic = isKineticPopTheme(themeName);
  const activeTokenIndexes = new Set(
    activeEmphasisTokenIndexes(cue.tokens, currentTime, cue.end),
  );
  const activeKeywordTokenIndex = kinetic
    ? activeKeywordTokenIndexFor(cue.tokens, [...activeTokenIndexes])
    : null;
  return (
    <div
      data-caption-index={cue.index}
      data-caption-id={cue.cueId ?? `caption-${cue.index}`}
      data-caption-segment-id={cue.segmentId}
      data-caption-timing-source={cue.timingSource}
      style={{
        position: "absolute",
        left: Math.max(kinetic ? 76 : 62, safeZone.left),
        right: Math.max(62, safeZone.right),
        bottom: Math.max(145, safeZone.bottom),
        minHeight: kinetic ? 148 : 170,
        display: "flex",
        alignItems: "center",
        justifyContent: kinetic ? "flex-start" : "center",
        textAlign: kinetic ? "left" : "center",
        padding: kinetic ? "20px 30px 24px 34px" : "22px 34px",
        borderRadius: kinetic ? 8 : 24,
        border: kinetic ? "none" : `2px solid ${tokens.panelBorder}`,
        borderLeft: kinetic ? `10px solid ${tokens.warning}` : undefined,
        background:
          themeName === "technical-editorial"
            ? "#172033f2"
            : `${tokens.background}f2`,
        color: "#f7f9ff",
        fontSize: kinetic ? 45 : 42,
        fontWeight: kinetic ? 750 : 700,
        lineHeight: kinetic ? 1.16 : 1.22,
        overflow: "hidden",
        overflowWrap: "anywhere",
        boxShadow: "0 10px 36px #0008",
        opacity: kinetic ? 1 : motion.opacity,
        transform: kinetic
          ? "translate3d(0, 0, 0)"
          : `translateY(${motion.translateY}px)`,
        zIndex: 20,
      }}
    >
      <span data-caption-text="true">
        {cue.tokens.length > 0
          ? cue.tokens.map((token, tokenIndex) => {
              const active = kinetic
                ? tokenIndex === activeKeywordTokenIndex
                : activeTokenIndexes.has(tokenIndex);
              return (
                <React.Fragment
                  key={`${cue.cueId ?? cue.index}-token-${tokenIndex}`}
                >
                  {tokenIndex > 0 ? " " : null}
                  <span
                    data-caption-token-index={tokenIndex}
                    data-caption-token-group={token.group}
                    data-caption-token-active={active ? "true" : "false"}
                    style={{
                      ...captionTokenPresentation(
                        active,
                        themeName === "technical-editorial"
                          ? "#ffd166"
                          : tokens.warning,
                      ),
                      ...(kinetic
                        ? {
                            color: active ? tokens.warning : "#f7f9ff",
                            background: active
                              ? `${tokens.warning}24`
                              : "transparent",
                            borderRadius: 5,
                            padding: "0 2px",
                            textDecorationLine: "none" as const,
                          }
                        : {}),
                    }}
                  >
                    {token.text}
                  </span>
                </React.Fragment>
              );
            })
          : cue.text}
      </span>
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
  themeName: ProjectData["theme"];
  children: React.ReactNode;
}> = ({ scene, pacing, themeName, children }) => {
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
  const kinetic = isKineticPopTheme(themeName);
  const kineticEntrance = kinetic
    ? kineticEntrancePresentationFor(
        frame,
        transitionFrames,
        scene.order,
        scene.order === 0 ? "cut" : scene.transition,
      )
    : null;
  const kineticBoundaryStyle = kineticEntrance
    ? kineticSceneBoundaryStyleFor(kineticEntrance)
    : null;
  return (
    <AbsoluteFill
      style={{
        opacity: presentation.opacity,
        transform: kineticBoundaryStyle
          ? kineticBoundaryStyle.transform
          : `translateX(${presentation.translateX}px)`,
        clipPath: kineticBoundaryStyle?.clipPath,
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
      <ThemeGrammarProvider themeName={data.theme}>
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
                <SceneTransition
                  scene={scene}
                  pacing={data.pacing}
                  themeName={data.theme}
                >
                  <Primitive scene={scene} themeName={data.theme} />
                </SceneTransition>
              </Sequence>
            ))}
            <RetentionOverlay
              retention={data.retention}
              themeName={data.theme}
            />
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
      </ThemeGrammarProvider>
    </AbsoluteFill>
  );
};
