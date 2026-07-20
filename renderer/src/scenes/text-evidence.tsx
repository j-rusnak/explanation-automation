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
