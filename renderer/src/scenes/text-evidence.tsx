import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { sceneProgressFor } from "../pacing/rhythm";
import {
  Frame,
  Panel,
  SceneHeadline,
  sceneTheme,
  type PrimitiveProps,
} from "./shared";

export type ReceiptPayoff = {
  duration: string;
  offset: string;
};

export const receiptPayoffFromText = (
  onScreenText: string,
  excerpt: string,
): ReceiptPayoff | null => {
  const relationship =
    /(\d+(?:\.\d+)?)\s*(ms|milliseconds?)\s*(?:→|->|â†’|to|corresponds?\s+to|means?)\s*(?:(about|approximately|roughly|~|≈)\s*)?(\d+(?:\.\d+)?)\s*%/iu;
  for (const suppliedText of [onScreenText, excerpt]) {
    const match = relationship.exec(suppliedText);
    if (!match) continue;
    const [, duration, , qualifier, offset] = match;
    return {
      duration: `${duration} ms`,
      offset: `${qualifier ? "~" : ""}${offset}%`,
    };
  }
  return null;
};

export const KineticText: React.FC<PrimitiveProps> = ({ scene, themeName }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const scale = spring({
    frame,
    fps,
    config:
      scene.motion === "energetic"
        ? { damping: 12, stiffness: 150 }
        : { damping: 18 },
  });
  const visual = scene.visual;
  const supporting =
    "kind" in visual && visual.kind === "kinetic-text"
      ? visual.supporting_text
      : null;
  return (
    <Frame scene={scene} tokens={tokens}>
      <div
        style={{
          transform: `scale(${0.92 + scale * 0.08})`,
          transformOrigin: "left center",
        }}
      >
        <SceneHeadline scene={scene} tokens={tokens} eyebrow="The idea" />
      </div>
      {supporting ? (
        <p
          style={{
            fontSize: 39,
            color: tokens.muted,
            lineHeight: 1.25,
            margin: 0,
            maxWidth: 820,
          }}
        >
          {supporting}
        </p>
      ) : null}
      {"kind" in visual &&
      visual.kind === "kinetic-text" &&
      visual.emphasis.length ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
          {visual.emphasis.map((item, index) => (
            <span
              key={item}
              style={{
                border: `2px solid ${tokens.accent}`,
                borderRadius: 999,
                padding: "11px 19px",
                fontSize: 27,
                color: tokens.accent,
                opacity: interpolate(
                  frame,
                  [8 + index * 6, 18 + index * 6],
                  [0, 1],
                  {
                    extrapolateLeft: "clamp",
                    extrapolateRight: "clamp",
                  },
                ),
              }}
            >
              {item}
            </span>
          ))}
        </div>
      ) : null}
    </Frame>
  );
};

export const SourceReceipt: React.FC<PrimitiveProps> = ({
  scene,
  themeName,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const visual = scene.visual;
  const typed =
    "kind" in visual && visual.kind === "source-receipt" ? visual : null;
  const excerpt =
    typed?.excerpt ??
    (!("kind" in visual) ? (visual.evidence_excerpt ?? visual.body) : "") ??
    "";
  const locator =
    typed?.locator ?? (!("kind" in visual) ? visual.source_locator : null);
  const sourceTitle = typed?.source_title ?? "Source excerpt";
  const highlightStart =
    typed?.highlight == null ? -1 : excerpt.indexOf(typed.highlight);
  const opacity = interpolate(frame, [0, 18], [0, 1], {
    extrapolateRight: "clamp",
  });
  if (themeName === "kinetic-pop") {
    const progress = sceneProgressFor(
      frame,
      Math.max(1, Math.round(scene.duration * fps)),
    );
    const highlightReveal = interpolate(progress, [0.08, 0.34], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    const collapse = interpolate(progress, [0.46, 0.72], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    const payoff = receiptPayoffFromText(scene.on_screen_text, excerpt);
    return (
      <Frame scene={scene} tokens={tokens}>
        <SceneHeadline
          scene={scene}
          tokens={tokens}
          eyebrow="Visible evidence"
        />
        <div
          style={{
            position: "relative",
            height: 675,
            display: "flex",
            justifyContent: "center",
            alignItems: "flex-start",
          }}
        >
          <div
            style={{
              width: 835,
              minHeight: 430,
              boxSizing: "border-box",
              padding: "39px 43px 45px",
              color: "#172033",
              backgroundColor: "#fff9df",
              backgroundImage:
                "radial-gradient(circle at 10px 0, transparent 9px, #fff9df 10px)",
              backgroundSize: "20px 14px",
              borderLeft: `5px solid ${tokens.danger}`,
              borderRight: `5px solid ${tokens.accent}`,
              boxShadow: "16px 20px 0 #00000055",
              fontFamily: '"Courier New", Courier, monospace',
              opacity,
              transformOrigin: "center top",
              transform: `translateY(${-collapse * 48}px) scale(${1 - collapse * 0.17}) rotate(${(1 - collapse) * -1.1}deg)`,
              zIndex: 2,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 20,
                paddingBottom: 20,
                borderBottom: "3px dashed #59627388",
                fontSize: 20,
                fontWeight: 900,
                letterSpacing: 1.8,
                color: "#4d596b",
              }}
            >
              <span>{sourceTitle}</span>
              <span>{locator}</span>
            </div>
            <p
              style={{
                fontSize: 31,
                lineHeight: 1.42,
                margin: "27px 0 24px",
                fontWeight: 700,
              }}
            >
              “
              {highlightStart >= 0 && typed?.highlight ? (
                <>
                  {excerpt.slice(0, highlightStart)}
                  <mark
                    style={{
                      color: "#172033",
                      padding: "2px 4px",
                      background: `linear-gradient(90deg, ${tokens.warning} 0%, ${tokens.warning} ${highlightReveal * 100}%, transparent ${highlightReveal * 100}%, transparent 100%)`,
                      boxDecorationBreak: "clone",
                    }}
                  >
                    {typed.highlight}
                  </mark>
                  {excerpt.slice(highlightStart + typed.highlight.length)}
                </>
              ) : (
                excerpt
              )}
              ”
            </p>
            <div
              style={{
                paddingTop: 18,
                borderTop: "3px dashed #59627388",
                color: "#4d596b",
                fontSize: 19,
                letterSpacing: 2,
                textAlign: "center",
              }}
            >
              VERIFIED PHRASE
            </div>
          </div>
          {payoff ? (
            <div
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                bottom: 0,
                display: "flex",
                alignItems: "baseline",
                justifyContent: "center",
                gap: 19,
                opacity: collapse,
                transform: `translateY(${(1 - collapse) * 45}px) scale(${0.82 + collapse * 0.18})`,
                fontWeight: 900,
                letterSpacing: -3,
                zIndex: 3,
              }}
            >
              <span style={{ color: tokens.accent, fontSize: 73 }}>
                {payoff.duration}
              </span>
              <span style={{ color: tokens.warning, fontSize: 65 }}>→</span>
              <span style={{ color: tokens.danger, fontSize: 96 }}>
                {payoff.offset}
              </span>
            </div>
          ) : null}
        </div>
      </Frame>
    );
  }
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline scene={scene} tokens={tokens} eyebrow="Visible evidence" />
      <Panel
        tokens={tokens}
        style={{
          opacity,
          padding: "42px 46px",
          background: tokens.motif === "paper" ? "#fffdf7" : "#f6f1e7",
          color: "#172033",
        }}
      >
        <div
          style={{
            fontSize: 22,
            fontWeight: 700,
            letterSpacing: 2.5,
            color: "#4d596b",
          }}
        >
          {sourceTitle}
        </div>
        <p style={{ fontSize: 39, lineHeight: 1.35, margin: "24px 0" }}>
          “
          {highlightStart >= 0 && typed?.highlight ? (
            <>
              {excerpt.slice(0, highlightStart)}
              <mark
                style={{
                  background: tokens.warning,
                  color: "#172033",
                  padding: "1px 3px",
                }}
              >
                {typed.highlight}
              </mark>
              {excerpt.slice(highlightStart + typed.highlight.length)}
            </>
          ) : (
            excerpt
          )}
          ”
        </p>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 20,
            fontSize: 23,
            color: "#4d596b",
          }}
        >
          <span>{locator}</span>
          <span>Evidence excerpt</span>
        </div>
      </Panel>
    </Frame>
  );
};

const HighlightedExcerpt: React.FC<{
  excerpt: string;
  ranges: Array<{ start: number; end: number }>;
  highlightColor: string;
}> = ({ excerpt, ranges, highlightColor }) => {
  const sorted = [...ranges].sort((left, right) => left.start - right.start);
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((range, index) => {
    if (range.start > cursor)
      parts.push(
        <React.Fragment key={`plain-${index}`}>
          {excerpt.slice(cursor, range.start)}
        </React.Fragment>,
      );
    parts.push(
      <mark
        key={`mark-${index}`}
        style={{
          background: highlightColor,
          color: "#172033",
          padding: "1px 3px",
        }}
      >
        {excerpt.slice(range.start, range.end)}
      </mark>,
    );
    cursor = Math.max(cursor, range.end);
  });
  if (cursor < excerpt.length)
    parts.push(
      <React.Fragment key="plain-end">{excerpt.slice(cursor)}</React.Fragment>,
    );
  return <>{parts}</>;
};

export const EvidenceHighlight: React.FC<PrimitiveProps> = ({
  scene,
  themeName,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const progress = Math.min(
    1,
    sceneProgressFor(frame, Math.max(1, Math.round(scene.duration * fps))) *
      1.2,
  );
  const visual =
    "kind" in scene.visual && scene.visual.kind === "evidence-highlight"
      ? scene.visual
      : null;
  if (!visual) return null;
  const visibleRanges = visual.highlights.slice(
    0,
    Math.ceil(progress * visual.highlights.length),
  );
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline scene={scene} tokens={tokens} eyebrow="Read the receipt" />
      <Panel
        tokens={tokens}
        style={{
          background: "#fffdf7",
          color: "#172033",
          padding: "42px 45px",
        }}
      >
        <div
          style={{
            fontSize: 22,
            color: "#566071",
            fontWeight: 700,
            letterSpacing: 2,
          }}
        >
          {visual.source_title}
        </div>
        <p
          style={{
            fontFamily: "Georgia, serif",
            fontSize: 37,
            lineHeight: 1.52,
            margin: "29px 0",
          }}
        >
          <HighlightedExcerpt
            excerpt={visual.excerpt}
            ranges={visibleRanges}
            highlightColor={tokens.warning}
          />
        </p>
        <div style={{ fontSize: 23, color: "#566071" }}>{visual.locator}</div>
      </Panel>
    </Frame>
  );
};
