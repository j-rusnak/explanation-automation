import React from "react";
import { interpolate } from "remotion";
import type { SceneData } from "../schemas/project";
import { getTheme, type ThemeName, type ThemeTokens } from "../themes/tokens";

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
}> = ({ scene, tokens, eyebrow }) => (
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
  </div>
);

const titleCase = (value: string): string =>
  value.charAt(0) + value.slice(1).toLowerCase();

const EvidenceBadge: React.FC<{ scene: SceneData; tokens: ThemeTokens }> = ({
  scene,
  tokens,
}) =>
  scene.evidence_label ? (
    <div
      style={{
        position: "absolute",
        top: 76,
        right: 62,
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

export const Frame: React.FC<{
  scene: SceneData;
  tokens: ThemeTokens;
  children: React.ReactNode;
}> = ({ scene, tokens, children }) => {
  const padding =
    scene.layout === "full-diagram"
      ? "155px 54px 345px"
      : scene.layout === "evidence"
        ? "170px 62px 360px"
        : "175px 64px 370px";
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
        ...motifStyle(tokens),
      }}
    >
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
