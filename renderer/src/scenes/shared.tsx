import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { SceneData } from "../schemas/project";
import { getTheme, type ThemeName, type ThemeTokens } from "../themes/tokens";
import {
  coldOpenSignal,
  microBeatSignal,
  pacingProfiles,
  patternInterruptFor,
  sceneProgressFor,
  usePacing,
} from "../pacing/rhythm";
import { useSafeZone } from "../safe-zone";

export type PrimitiveProps = { scene: SceneData; themeName: ThemeName };
export type ColorToken =
  | "background"
  | "panel"
  | "text"
  | "muted"
  | "accent"
  | "warning"
  | "danger"
  | "citation";

const SAFE_COLOR = /^#[0-9a-f]{6}$/i;
export const sceneTheme = (scene: SceneData, name: ThemeName): ThemeTokens => {
  const base = getTheme(name);
  const override = scene.theme_overrides;
  return {
    ...base,
    ...Object.fromEntries(
      Object.entries(override).filter(
        ([key, value]) => key in base && SAFE_COLOR.test(value),
      ),
    ),
  };
};

export const color = (tokens: ThemeTokens, token: ColorToken): string =>
  tokens[token];

const revealWindow = (scene: SceneData, fps: number): [number, number] => {
  const factor =
    scene.motion === "calm" ? 0.7 : scene.motion === "energetic" ? 0.34 : 0.48;
  return [
    Math.round(fps * 0.1),
    Math.max(2, Math.round(scene.duration * fps * factor)),
  ];
};

export const progressFor = (
  scene: SceneData,
  frame: number,
  fps: number,
): number => {
  const [start, end] = revealWindow(scene, fps);
  return interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
};

const motifStyle = (tokens: ThemeTokens): React.CSSProperties => {
  if (tokens.motif === "paper") {
    return {
      backgroundImage:
        "repeating-linear-gradient(0deg, transparent 0, transparent 47px, #1720330d 48px)",
    };
  }
  if (tokens.motif === "signal") {
    return {
      backgroundImage:
        "linear-gradient(#6df7ad0a 1px, transparent 1px), linear-gradient(90deg, #6df7ad0a 1px, transparent 1px)",
      backgroundSize: "54px 54px",
    };
  }
  return {
    backgroundImage:
      "linear-gradient(#a8b7ff0b 1px, transparent 1px), linear-gradient(90deg, #a8b7ff0b 1px, transparent 1px)",
    backgroundSize: "72px 72px",
  };
};

export const SceneHeadline: React.FC<{
  scene: SceneData;
  tokens: ThemeTokens;
  eyebrow?: string;
}> = ({ scene, tokens, eyebrow }) => {
  const frame = useCurrentFrame();
  const introFrames = scene.order === 0 ? 8 : 14;
  const accentProgress = Math.max(0, Math.min(1, frame / introFrames));
  return (
    <div style={{ maxWidth: scene.layout === "full-diagram" ? 930 : 890 }}>
      {eyebrow ? (
        <div
          style={{
            color: tokens.accent,
            fontSize: 23,
            fontWeight: 700,
            letterSpacing: 4,
            marginBottom: 15,
            textTransform: "uppercase",
          }}
        >
          {eyebrow}
        </div>
      ) : null}
      <h1
        style={{
          fontFamily: tokens.headingFont,
          fontSize: scene.layout === "hero" ? 91 : 73,
          lineHeight: 0.99,
          margin: 0,
          letterSpacing: scene.layout === "hero" ? -3 : -2,
          textWrap: "balance",
        }}
      >
        {scene.on_screen_text}
      </h1>
      <div
        style={{
          width: 72 + accentProgress * 188,
          height: 6,
          marginTop: 22,
          borderRadius: 999,
          background: `linear-gradient(90deg, ${tokens.accent}, ${tokens.warning})`,
          boxShadow: `0 0 20px ${tokens.accent}44`,
        }}
      />
    </div>
  );
};

const titleCase = (value: string): string =>
  value.charAt(0) + value.slice(1).toLowerCase();

const EvidenceBadge: React.FC<{ scene: SceneData; tokens: ThemeTokens }> = ({
  scene,
  tokens,
}) => {
  const safeZone = useSafeZone();
  return scene.evidence_label ? (
    <div
      style={{
        position: "absolute",
        top: Math.max(76, safeZone.top),
        right: Math.max(62, safeZone.right),
        display: "flex",
        alignItems: "center",
        gap: 12,
        border: `2px solid ${tokens.citation}`,
        borderRadius: 999,
        padding: "10px 18px",
        color: tokens.citation,
        background: `${tokens.background}d9`,
        fontSize: 21,
        fontWeight: 700,
        letterSpacing: 1.2,
      }}
    >
      <span aria-hidden="true">●</span>
      {titleCase(scene.evidence_label)} evidence
      {scene.citation_label ? ` · ${scene.citation_label}` : ""}
    </div>
  ) : null;
};

const PacingDecorations: React.FC<{
  scene: SceneData;
  tokens: ThemeTokens;
}> = ({ scene, tokens }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const preset = usePacing();
  const safeZone = useSafeZone();
  const profile = pacingProfiles[preset];
  const durationFrames = Math.max(1, Math.round(scene.duration * fps));
  const progress = sceneProgressFor(frame, durationFrames);
  const beat = microBeatSignal(frame, durationFrames, fps, preset);
  const cold = scene.order === 0 ? coldOpenSignal(frame, fps) : 0;
  const treatment = patternInterruptFor(scene.order);
  const opacity = profile.decorationOpacity * (0.36 + beat * 0.64);
  const shift = profile.decorationShift * beat;
  return (
    <div
      aria-hidden="true"
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        pointerEvents: "none",
      }}
    >
      {cold > 0 ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 0,
            height: 960,
            opacity: cold * 0.15,
            background: `linear-gradient(125deg, ${tokens.accent}88, transparent 58%)`,
          }}
        />
      ) : null}
      <div
        style={{
          position: "absolute",
          left: 20,
          top: 215,
          width: 7,
          height: 790,
          borderRadius: 99,
          background: `${tokens.panelBorder}88`,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: "100%",
            height: `${progress * 100}%`,
            borderRadius: 99,
            background: tokens.accent,
          }}
        />
      </div>
      {treatment === "accent-rail" ? (
        <div
          style={{
            position: "absolute",
            top: 135 + shift,
            left: 0,
            width: `${24 + progress * 58}%`,
            height: 4,
            opacity: 0.28 + opacity,
            background: `linear-gradient(90deg, ${tokens.accent}, transparent)`,
          }}
        />
      ) : null}
      {treatment === "corner-brackets" ? (
        <>
          <div
            style={{
              position: "absolute",
              left: 44 + shift,
              top: 145,
              width: 92,
              height: 92,
              borderLeft: `5px solid ${tokens.citation}`,
              borderTop: `5px solid ${tokens.citation}`,
              opacity: 0.24 + opacity,
            }}
          />
          <div
            style={{
              position: "absolute",
              right: Math.max(44, safeZone.right) + shift,
              bottom: Math.max(355, safeZone.bottom + 24),
              width: 92,
              height: 92,
              borderRight: `5px solid ${tokens.citation}`,
              borderBottom: `5px solid ${tokens.citation}`,
              opacity: 0.24 + opacity,
            }}
          />
        </>
      ) : null}
      {treatment === "focus-ring" ? (
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: "46%",
            width: 570 + shift * 3,
            height: 570 + shift * 3,
            transform: "translate(-50%, -50%)",
            borderRadius: "50%",
            border: `4px solid ${tokens.warning}`,
            opacity,
          }}
        />
      ) : null}
    </div>
  );
};

export const Frame: React.FC<{
  scene: SceneData;
  tokens: ThemeTokens;
  children: React.ReactNode;
}> = ({ scene, tokens, children }) => {
  const safeZone = useSafeZone();
  const basePadding =
    scene.layout === "full-diagram"
      ? { top: 155, right: 54, bottom: 345, left: 54 }
      : scene.layout === "evidence"
        ? { top: 170, right: 62, bottom: 360, left: 62 }
        : { top: 175, right: 64, bottom: 370, left: 64 };
  const padding = `${Math.max(basePadding.top, safeZone.top)}px ${Math.max(basePadding.right, safeZone.right)}px ${Math.max(basePadding.bottom, safeZone.bottom)}px ${Math.max(basePadding.left, safeZone.left)}px`;
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        padding,
        display: "flex",
        flexDirection: "column",
        justifyContent: scene.layout === "hero" ? "center" : "flex-start",
        gap: scene.layout === "hero" ? 56 : 38,
        color: tokens.text,
        isolation: "isolate",
        ...motifStyle(tokens),
      }}
    >
      <PacingDecorations scene={scene} tokens={tokens} />
      <EvidenceBadge scene={scene} tokens={tokens} />
      {children}
    </div>
  );
};

export const Panel: React.FC<{
  tokens: ThemeTokens;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ tokens, children, style }) => (
  <div
    style={{
      background: `${tokens.panel}f2`,
      border: `2px solid ${tokens.panelBorder}`,
      borderRadius: tokens.radius,
      boxShadow:
        tokens.motif === "paper"
          ? "0 18px 44px #5c51402a"
          : "0 24px 60px #0005",
      ...style,
    }}
  >
    {children}
  </div>
);

export const Shape: React.FC<{
  feature: "straight-edge" | "grid" | "rotor" | "signal" | "generic";
  distorted?: boolean;
  tokens: ThemeTokens;
  progress?: number;
}> = ({ feature, distorted = false, tokens, progress = 1 }) => {
  if (feature === "grid") {
    return (
      <div
        style={{
          width: 250,
          height: 310,
          display: "grid",
          gridTemplateColumns: "repeat(5, 1fr)",
          gridTemplateRows: "repeat(7, 1fr)",
          transform: distorted ? `skewX(${-16 * progress}deg)` : undefined,
        }}
      >
        {Array.from({ length: 35 }, (_, index) => (
          <div key={index} style={{ border: `2px solid ${tokens.accent}88` }} />
        ))}
      </div>
    );
  }
  if (feature === "rotor") {
    return (
      <div
        style={{
          position: "relative",
          width: 290,
          height: 290,
          transform: distorted ? `skewX(${-18 * progress}deg)` : "rotate(8deg)",
        }}
      >
        {[0, 60, 120].map((rotation) => (
          <div
            key={rotation}
            style={{
              position: "absolute",
              left: 137,
              top: 18,
              width: 18,
              height: 254,
              borderRadius: 20,
              background: tokens.accent,
              transform: `rotate(${rotation}deg)`,
            }}
          />
        ))}
        <div
          style={{
            position: "absolute",
            left: 112,
            top: 112,
            width: 68,
            height: 68,
            borderRadius: "50%",
            background: tokens.warning,
          }}
        />
      </div>
    );
  }
  if (feature === "signal") {
    return (
      <svg width="300" height="230" aria-hidden="true">
        {Array.from({ length: 17 }, (_, index) => {
          const x = index * 18;
          const y =
            115 + Math.sin(index * 0.9) * (distorted ? 65 * progress : 38);
          const nextY =
            115 +
            Math.sin((index + 1) * 0.9) * (distorted ? 65 * progress : 38);
          return (
            <line
              key={index}
              x1={x}
              y1={y}
              x2={x + 18}
              y2={nextY}
              stroke={tokens.accent}
              strokeWidth={8}
              strokeLinecap="round"
            />
          );
        })}
      </svg>
    );
  }
  if (feature === "straight-edge" && distorted) {
    const bend = 82 * progress;
    return (
      <svg width="250" height="340" viewBox="0 0 250 340" aria-hidden="true">
        <path
          d={`M 76 310 Q ${76 + bend * 0.12} 172 ${76 + bend} 30`}
          fill="none"
          stroke={tokens.warning}
          strokeWidth={24}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 18px ${tokens.warning}66)` }}
        />
      </svg>
    );
  }
  return (
    <div
      style={{
        width: 24,
        height: 320,
        borderRadius: 15,
        background: distorted ? tokens.warning : tokens.accent,
        transform: distorted ? `skewX(${-20 * progress}deg)` : undefined,
        boxShadow: `0 0 32px ${distorted ? tokens.warning : tokens.accent}55`,
      }}
    />
  );
};
