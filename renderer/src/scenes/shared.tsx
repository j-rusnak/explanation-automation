import React, { createContext, useContext } from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { SceneData } from "../schemas/project";
import { getTheme, type ThemeName, type ThemeTokens } from "../themes/tokens";
import {
  coldOpenSignal,
  kineticScenePresentationFor,
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

const ThemeGrammarContext = createContext<ThemeName>("blueprint");

export const ThemeGrammarProvider: React.FC<{
  themeName: ThemeName;
  children: React.ReactNode;
}> = ({ themeName, children }) => (
  <ThemeGrammarContext.Provider value={themeName}>
    {children}
  </ThemeGrammarContext.Provider>
);

export const useThemeGrammar = (): ThemeName => useContext(ThemeGrammarContext);

export const isKineticPopTheme = (name: ThemeName): boolean =>
  name === "kinetic-pop";

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

export type KineticChapter = {
  primary: ColorToken;
  secondary: ColorToken;
  anchor: "left" | "right";
};

type KineticChapterInput = Pick<SceneData, "layout" | "order" | "primitive">;

export const kineticChapterFor = (
  scene: KineticChapterInput,
): KineticChapter => {
  if (scene.order === 0) {
    return { primary: "warning", secondary: "accent", anchor: "right" };
  }
  if (scene.layout === "limitation" || scene.primitive === "LimitationCard") {
    return { primary: "danger", secondary: "warning", anchor: "left" };
  }
  if (
    scene.layout === "evidence" ||
    scene.primitive === "SourceReceipt" ||
    scene.primitive === "EvidenceHighlight"
  ) {
    return { primary: "citation", secondary: "warning", anchor: "right" };
  }
  if (scene.layout === "numeric") {
    return { primary: "warning", secondary: "accent", anchor: "left" };
  }
  const chapters: KineticChapter[] = [
    { primary: "accent", secondary: "citation", anchor: "left" },
    { primary: "citation", secondary: "accent", anchor: "right" },
    { primary: "warning", secondary: "accent", anchor: "left" },
  ];
  return chapters[(scene.order - 1) % chapters.length]!;
};

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

export const KineticBackdrop: React.FC<{
  chapter: KineticChapter;
  durationSeconds: number;
  motion: SceneData["motion"];
  sceneOrder: number;
  tokens: ThemeTokens;
}> = ({ chapter, durationSeconds, motion, sceneOrder, tokens }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const durationFrames = Math.max(1, Math.round(durationSeconds * fps));
  const camera = kineticScenePresentationFor(
    frame,
    durationFrames,
    fps,
    motion,
    sceneOrder,
  );
  const primary = color(tokens, chapter.primary);
  const secondary = color(tokens, chapter.secondary);
  const rightAnchored = chapter.anchor === "right";
  return (
    <div
      aria-hidden="true"
      data-kinetic-chapter={`${chapter.primary}-${chapter.secondary}`}
      style={{
        position: "absolute",
        inset: -80,
        zIndex: 0,
        overflow: "hidden",
        pointerEvents: "none",
        background: `linear-gradient(145deg, ${tokens.background} 0%, ${tokens.panel} 56%, ${tokens.background} 100%)`,
      }}
    >
      <div
        style={{
          position: "absolute",
          width: 900,
          height: 900,
          top: -260 + camera.translateY * 1.4,
          [rightAnchored ? "right" : "left"]: -320 + camera.translateX * 1.8,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${primary}d9 0%, ${primary}73 34%, ${primary}00 72%)`,
          transform: `scale(${1 + camera.beat * 0.035})`,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 760,
          height: 760,
          left: rightAnchored ? -310 : 650,
          bottom: -280 - camera.translateY,
          borderRadius: "42% 58% 63% 37%",
          background: `radial-gradient(circle, ${secondary}a8 0%, ${secondary}52 38%, ${secondary}00 72%)`,
          transform: `rotate(${rightAnchored ? -12 : 12}deg) scale(${1 + camera.beat * 0.025})`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: -250,
          right: -250,
          top: 780 + camera.translateY * 2,
          height: 210,
          background: `linear-gradient(90deg, transparent 0%, ${primary}9c 34%, ${secondary}7d 72%, transparent 100%)`,
          transform: `rotate(${rightAnchored ? -9 : 9}deg) translateX(${camera.translateX * 2}px)`,
          clipPath: "polygon(0 42%, 100% 0, 100% 58%, 0 100%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: 0.16,
          backgroundImage: `radial-gradient(${tokens.text} 1.4px, transparent 1.4px)`,
          backgroundSize: "34px 34px",
          transform: `translate(${camera.translateX * 0.45}px, ${camera.translateY * 0.45}px)`,
          maskImage:
            "linear-gradient(125deg, transparent 6%, #000 35%, #000 66%, transparent 94%)",
        }}
      />
    </div>
  );
};

export const SceneHeadline: React.FC<{
  scene: SceneData;
  tokens: ThemeTokens;
  eyebrow?: string;
}> = ({ scene, tokens, eyebrow }) => {
  const frame = useCurrentFrame();
  const themeName = useThemeGrammar();
  const kinetic = isKineticPopTheme(themeName);
  const chapter = kineticChapterFor(scene);
  const chapterColor = color(tokens, chapter.primary);
  const introFrames = scene.order === 0 ? 8 : 14;
  const accentProgress = Math.max(0, Math.min(1, frame / introFrames));
  return (
    <div
      style={{
        maxWidth: kinetic
          ? scene.layout === "full-diagram"
            ? 970
            : 920
          : scene.layout === "full-diagram"
            ? 930
            : 890,
        alignSelf: kinetic && scene.order % 2 === 1 ? "flex-end" : undefined,
        transform:
          kinetic && scene.order % 2 === 1 ? "translateX(22px)" : undefined,
        position: "relative",
      }}
    >
      {eyebrow ? (
        <div
          style={{
            color: kinetic ? tokens.background : tokens.accent,
            background: kinetic ? chapterColor : undefined,
            display: kinetic ? "inline-flex" : undefined,
            clipPath: kinetic
              ? "polygon(0 0, calc(100% - 18px) 0, 100% 50%, calc(100% - 18px) 100%, 0 100%)"
              : undefined,
            padding: kinetic ? "11px 32px 11px 18px" : undefined,
            fontSize: kinetic ? 21 : 23,
            fontWeight: kinetic ? 800 : 700,
            letterSpacing: kinetic ? 3 : 4,
            marginBottom: kinetic ? 20 : 15,
            textTransform: "uppercase",
          }}
        >
          {eyebrow}
        </div>
      ) : null}
      <h1
        style={{
          fontFamily: tokens.headingFont,
          fontSize: kinetic
            ? scene.layout === "hero"
              ? 116
              : 88
            : scene.layout === "hero"
              ? 91
              : 73,
          lineHeight: kinetic ? 0.91 : 0.99,
          margin: 0,
          letterSpacing: kinetic
            ? scene.layout === "hero"
              ? -6
              : -4
            : scene.layout === "hero"
              ? -3
              : -2,
          fontWeight: kinetic ? 850 : undefined,
          textWrap: "balance",
          textShadow: kinetic
            ? `0 12px 45px ${tokens.background}a8`
            : undefined,
        }}
      >
        {scene.on_screen_text}
      </h1>
      <div
        style={{
          width: kinetic
            ? 116 + accentProgress * 250
            : 72 + accentProgress * 188,
          height: kinetic ? 13 : 6,
          marginTop: kinetic ? 26 : 22,
          borderRadius: 999,
          background: kinetic
            ? `linear-gradient(90deg, ${chapterColor}, ${color(tokens, chapter.secondary)})`
            : `linear-gradient(90deg, ${tokens.accent}, ${tokens.warning})`,
          boxShadow: kinetic
            ? `0 10px 32px ${chapterColor}66`
            : `0 0 20px ${tokens.accent}44`,
          transform: kinetic ? "skewX(-18deg)" : undefined,
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
  const kinetic = isKineticPopTheme(useThemeGrammar());
  const chapter = kineticChapterFor(scene);
  return scene.evidence_label ? (
    <div
      style={{
        position: "absolute",
        top: Math.max(76, safeZone.top),
        right: Math.max(62, safeZone.right),
        display: "flex",
        alignItems: "center",
        gap: 12,
        border: kinetic ? "none" : `2px solid ${tokens.citation}`,
        borderRadius: kinetic ? 8 : 999,
        padding: kinetic ? "12px 20px" : "10px 18px",
        color: kinetic ? tokens.background : tokens.citation,
        background: kinetic
          ? `${color(tokens, chapter.primary)}e8`
          : `${tokens.background}d9`,
        boxShadow: kinetic ? `7px 7px 0 ${tokens.background}99` : undefined,
        fontSize: kinetic ? 19 : 21,
        fontWeight: kinetic ? 800 : 700,
        letterSpacing: 1.2,
        zIndex: kinetic ? 4 : undefined,
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
  const kinetic = isKineticPopTheme(useThemeGrammar());
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
  if (kinetic) {
    const chapter = kineticChapterFor(scene);
    const camera = kineticScenePresentationFor(
      frame,
      durationFrames,
      fps,
      scene.motion,
      scene.order,
    );
    const chapterColor = color(tokens, chapter.primary);
    return (
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          zIndex: 1,
          overflow: "hidden",
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: Math.max(116, safeZone.top),
            [chapter.anchor]: Math.max(34, safeZone[chapter.anchor]),
            color: `${tokens.text}20`,
            fontSize: 190,
            fontWeight: 900,
            lineHeight: 0.8,
            letterSpacing: -14,
            transform: `translateY(${camera.translateY * 1.4}px)`,
          }}
        >
          {String(scene.order + 1).padStart(2, "0")}
        </div>
        <div
          style={{
            position: "absolute",
            left: 24,
            top: 235,
            width: 10,
            height: 690,
            borderRadius: 99,
            background: `${tokens.text}28`,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: "100%",
              height: `${progress * 100}%`,
              borderRadius: 99,
              background: chapterColor,
              boxShadow: `0 0 24px ${chapterColor}8f`,
            }}
          />
        </div>
        <div
          style={{
            position: "absolute",
            width: 56 + camera.beat * 34,
            height: 56 + camera.beat * 34,
            [chapter.anchor]: 88 - camera.beat * 17,
            bottom: Math.max(360, safeZone.bottom + 32),
            border: `10px solid ${chapterColor}`,
            borderRadius: "50%",
            boxShadow: `0 0 0 10px ${tokens.background}70`,
          }}
        />
      </div>
    );
  }
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
  const themeName = useThemeGrammar();
  const kinetic = isKineticPopTheme(themeName);
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const durationFrames = Math.max(1, Math.round(scene.duration * fps));
  const camera = kinetic
    ? kineticScenePresentationFor(
        frame,
        durationFrames,
        fps,
        scene.motion,
        scene.order,
      )
    : null;
  const basePadding =
    kinetic && scene.layout === "full-diagram"
      ? { top: 142, right: 40, bottom: 330, left: 42 }
      : kinetic && scene.layout === "evidence"
        ? { top: 154, right: 50, bottom: 342, left: 50 }
        : kinetic
          ? { top: 150, right: 52, bottom: 350, left: 52 }
          : scene.layout === "full-diagram"
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
        ...(kinetic ? {} : motifStyle(tokens)),
      }}
    >
      {kinetic ? (
        <KineticBackdrop
          chapter={kineticChapterFor(scene)}
          durationSeconds={scene.duration}
          motion={scene.motion}
          sceneOrder={scene.order}
          tokens={tokens}
        />
      ) : null}
      <PacingDecorations scene={scene} tokens={tokens} />
      <EvidenceBadge scene={scene} tokens={tokens} />
      {kinetic ? (
        <div
          data-kinetic-content="true"
          style={{
            position: "relative",
            zIndex: 2,
            minHeight: 0,
            flex: 1,
            display: "flex",
            flexDirection: "column",
            justifyContent: scene.layout === "hero" ? "center" : "flex-start",
            gap: scene.layout === "hero" ? 52 : 34,
            transform: `translate3d(${camera?.translateX ?? 0}px, ${camera?.translateY ?? 0}px, 0) scale(${camera?.scale ?? 1})`,
            transformOrigin:
              scene.order % 2 === 0 ? "left center" : "right center",
          }}
        >
          {children}
        </div>
      ) : (
        children
      )}
    </div>
  );
};

export const Panel: React.FC<{
  tokens: ThemeTokens;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ tokens, children, style }) => {
  const kinetic = isKineticPopTheme(useThemeGrammar());
  return (
    <div
      style={{
        background: kinetic
          ? `linear-gradient(145deg, ${tokens.panel}d9, ${tokens.background}9e)`
          : `${tokens.panel}f2`,
        border: kinetic ? "none" : `2px solid ${tokens.panelBorder}`,
        borderLeft: kinetic ? `9px solid ${tokens.accent}` : undefined,
        borderBottom: kinetic ? `3px solid ${tokens.panelBorder}c4` : undefined,
        borderRadius: kinetic ? 9 : tokens.radius,
        clipPath: kinetic
          ? "polygon(0 0, calc(100% - 32px) 0, 100% 32px, 100% 100%, 0 100%)"
          : undefined,
        boxShadow: kinetic
          ? `18px 22px 0 ${tokens.background}52, 0 28px 70px #0005`
          : tokens.motif === "paper"
            ? "0 18px 44px #5c51402a"
            : "0 24px 60px #0005",
        ...style,
      }}
    >
      {children}
    </div>
  );
};

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
