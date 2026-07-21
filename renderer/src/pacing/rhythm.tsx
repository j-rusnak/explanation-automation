import React, { createContext, useContext } from "react";
import type { PacingPreset, SceneData } from "../schemas/project";

export type PatternInterrupt = "accent-rail" | "corner-brackets" | "focus-ring";

type PacingProfile = {
  microBeatCount: 2 | 3 | 4;
  transitionSeconds: number;
  decorationOpacity: number;
  decorationShift: number;
};

export const pacingProfiles: Record<PacingPreset, PacingProfile> = {
  measured: {
    microBeatCount: 2,
    transitionSeconds: 0.34,
    decorationOpacity: 0.055,
    decorationShift: 4,
  },
  brisk: {
    microBeatCount: 3,
    transitionSeconds: 0.24,
    decorationOpacity: 0.08,
    decorationShift: 6,
  },
  "high-retention": {
    microBeatCount: 4,
    transitionSeconds: 0.18,
    decorationOpacity: 0.105,
    decorationShift: 8,
  },
};

const PacingContext = createContext<PacingPreset>("brisk");

export const PacingProvider: React.FC<{
  preset: PacingPreset;
  children: React.ReactNode;
}> = ({ preset, children }) => (
  <PacingContext.Provider value={preset}>{children}</PacingContext.Provider>
);

export const usePacing = (): PacingPreset => useContext(PacingContext);

export const patternInterruptFor = (sceneOrder: number): PatternInterrupt => {
  const treatments: PatternInterrupt[] = [
    "accent-rail",
    "corner-brackets",
    "focus-ring",
  ];
  return treatments[
    ((sceneOrder % treatments.length) + treatments.length) % treatments.length
  ]!;
};

export const sceneProgressFor = (
  frame: number,
  durationFrames: number,
): number => {
  if (durationFrames <= 1) return 1;
  return Math.max(0, Math.min(1, frame / (durationFrames - 1)));
};

export const microBeatFrames = (
  durationFrames: number,
  fps: number,
  preset: PacingPreset,
): number[] => {
  if (durationFrames < Math.round(fps * 1.8)) return [];
  const profile = pacingProfiles[preset];
  const edge = Math.max(8, Math.round(fps * 0.55));
  const minimumSpacing = Math.max(12, Math.round(fps * 0.8));
  const usable = durationFrames - edge * 2;
  if (usable <= 0) return [];
  const maximumCount = Math.max(1, Math.floor(usable / minimumSpacing) + 1);
  const count = Math.min(profile.microBeatCount, maximumCount);
  return Array.from({ length: count }, (_, index) =>
    Math.round(edge + (usable * (index + 1)) / (count + 1)),
  );
};

export const microBeatSignal = (
  frame: number,
  durationFrames: number,
  fps: number,
  preset: PacingPreset,
): number => {
  const halfWidth = Math.max(8, Math.round(fps * 0.24));
  return microBeatFrames(durationFrames, fps, preset).reduce(
    (strongest, beat) => {
      const distance = Math.abs(frame - beat);
      const value = Math.max(0, 1 - distance / halfWidth);
      return Math.max(strongest, value);
    },
    0,
  );
};

/**
 * Kinetic Pop uses fewer, larger state changes than the ambient pacing
 * decorations. Dividing the scene into equal sections keeps every interior
 * beat 1.5–2.5 seconds from its neighbours for normal explainer scenes while
 * avoiding a gratuitous beat in shots shorter than three seconds.
 */
export const kineticMicroBeatFrames = (
  durationFrames: number,
  fps: number,
): number[] => {
  if (durationFrames < Math.round(fps * 3)) return [];
  const sections = Math.max(2, Math.ceil(durationFrames / (fps * 2.5)));
  return Array.from({ length: sections - 1 }, (_, index) =>
    Math.round((durationFrames * (index + 1)) / sections),
  );
};

export const kineticMicroBeatSignal = (
  frame: number,
  durationFrames: number,
  fps: number,
): number => {
  // A broad 0.72-second focus movement reads as a camera reframe, not a flash.
  const halfWidth = Math.max(1, Math.round(fps * 0.36));
  return kineticMicroBeatFrames(durationFrames, fps).reduce(
    (strongest, beat) => {
      const distance = Math.abs(frame - beat);
      const linear = Math.max(0, 1 - distance / halfWidth);
      const eased = linear * linear * (3 - 2 * linear);
      return Math.max(strongest, eased);
    },
    0,
  );
};

export type KineticScenePresentation = {
  scale: number;
  translateX: number;
  translateY: number;
  beat: number;
};

export const kineticScenePresentationFor = (
  frame: number,
  durationFrames: number,
  fps: number,
  motion: SceneData["motion"],
  sceneOrder: number,
): KineticScenePresentation => {
  const progress = sceneProgressFor(frame, durationFrames);
  const beat = kineticMicroBeatSignal(frame, durationFrames, fps);
  const direction = sceneOrder % 2 === 0 ? 1 : -1;
  const intensity =
    motion === "calm" ? 0.56 : motion === "energetic" ? 1 : 0.78;
  return {
    scale: 1 + (progress * 0.012 + beat * 0.016) * intensity,
    translateX: direction * (progress * 8 + beat * 9) * intensity,
    translateY: -(progress * 5 + beat * 6) * intensity,
    beat,
  };
};

export const kineticEntrancePresentationFor = (
  frame: number,
  transitionFrames: number,
  sceneOrder: number,
): Pick<KineticScenePresentation, "scale" | "translateX" | "translateY"> => {
  const linear = Math.max(
    0,
    Math.min(1, frame / Math.max(1, transitionFrames)),
  );
  const entrance = linear * linear * (3 - 2 * linear);
  const direction = sceneOrder % 2 === 0 ? 1 : -1;
  return {
    scale: 0.972 + entrance * 0.028,
    translateX: direction * (1 - entrance) * 28,
    translateY: (1 - entrance) * 18,
  };
};

export const coldOpenSignal = (frame: number, fps: number): number =>
  Math.max(0, Math.min(1, 1 - frame / Math.max(1, Math.round(fps * 0.7))));

export const captionMotionFor = (
  currentTime: number,
  start: number,
  end: number,
): { opacity: number; translateY: number; progress: number } => {
  const duration = Math.max(0.001, end - start);
  const elapsed = Math.max(0, currentTime - start);
  const entrance = Math.max(
    0,
    Math.min(1, elapsed / Math.min(0.2, duration * 0.2)),
  );
  return {
    // Captions remain readable on their first frame; motion only reinforces
    // the cue change instead of hiding text.
    opacity: 0.86 + entrance * 0.14,
    translateY: (1 - entrance) * 10,
    progress: Math.max(0, Math.min(1, elapsed / duration)),
  };
};

export const transitionFramesFor = (
  scene: Pick<SceneData, "duration" | "motion">,
  fps: number,
  preset: PacingPreset,
): number => {
  const profile = pacingProfiles[preset];
  const motionFactor =
    scene.motion === "calm" ? 1.22 : scene.motion === "energetic" ? 0.82 : 1;
  const durationFrames = Math.max(1, Math.round(scene.duration * fps));
  return Math.max(
    1,
    Math.min(
      Math.round(fps * profile.transitionSeconds * motionFactor),
      Math.max(1, Math.floor(durationFrames / 3)),
    ),
  );
};

export const transitionPresentationFor = (
  frame: number,
  transitionFrames: number,
  transition: SceneData["transition"],
  motion: SceneData["motion"],
  coldOpen: boolean,
): { opacity: number; translateX: number } => {
  if (coldOpen || transition === "cut") return { opacity: 1, translateX: 0 };
  const entrance = Math.max(
    0,
    Math.min(1, frame / Math.max(1, transitionFrames)),
  );
  return {
    // Adjacent sequences do not overlap, so fading a whole scene from zero
    // exposes a bare-background flash at every cut. Keep the scene opaque and
    // reserve the bounded entrance motion for slide transitions.
    opacity: 1,
    translateX:
      transition === "slide"
        ? (1 - entrance) * (motion === "energetic" ? 36 : 48)
        : 0,
  };
};
