import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { sceneProgressFor } from "../pacing/rhythm";
import type { SceneData } from "../schemas/project";
import type { ThemeTokens } from "../themes/tokens";
import {
  Frame,
  Panel,
  SceneHeadline,
  color,
  progressFor,
  sceneTheme,
  type PrimitiveProps,
} from "./shared";

const LegacyChart: React.FC<{ scene: SceneData; tokens: ThemeTokens }> = ({
  scene,
  tokens,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = progressFor(scene, frame, fps);
  const visual = !("kind" in scene.visual) ? scene.visual : null;
  const values = visual?.series ?? [];
  const max = Math.max(...values, 1);
  return (
    <Panel
      tokens={tokens}
      style={{
        height: 610,
        padding: "35px 35px 58px",
        display: "flex",
        alignItems: "end",
        gap: 20,
      }}
    >
      {values.map((value, index) => (
        <div
          key={index}
          style={{
            flex: 1,
            height: "100%",
            display: "flex",
            flexDirection: "column",
            justifyContent: "flex-end",
          }}
        >
          <div style={{ textAlign: "center", fontSize: 24, marginBottom: 10 }}>
            {value}
          </div>
          <div
            style={{
              height: `${Math.max(2, (value / max) * progress * 86)}%`,
              background:
                index === values.length - 1 ? tokens.warning : tokens.accent,
              borderRadius: "12px 12px 3px 3px",
            }}
          />
          <div
            style={{
              textAlign: "center",
              color: tokens.muted,
              fontSize: 22,
              marginTop: 12,
            }}
          >
            {visual?.labels[index]}
          </div>
        </div>
      ))}
    </Panel>
  );
};

export const ChartReveal: React.FC<PrimitiveProps> = ({ scene, themeName }) => {
  if ("kind" in scene.visual && scene.visual.kind === "annotated-chart") {
    return <AnnotatedChart scene={scene} themeName={themeName} />;
  }
  const tokens = sceneTheme(scene, themeName);
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline scene={scene} tokens={tokens} eyebrow="Measured pattern" />
      <LegacyChart scene={scene} tokens={tokens} />
    </Frame>
  );
};

export function AnnotatedChart({
  scene,
  themeName,
}: PrimitiveProps): React.ReactElement | null {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const progress = progressFor(scene, frame, fps);
  const sceneProgress = sceneProgressFor(
    frame,
    Math.max(1, Math.round(scene.duration * fps)),
  );
  const annotationProgress = Math.max(
    0,
    Math.min(1, (sceneProgress - 0.38) / 0.24),
  );
  const visual =
    "kind" in scene.visual && scene.visual.kind === "annotated-chart"
      ? scene.visual
      : null;
  if (!visual) return null;
  const points = visual.series.flatMap((series) => series.points);
  const minX = Math.min(...points.map((point) => point.x));
  const maxX = Math.max(...points.map((point) => point.x));
  const minY = Math.min(0, ...points.map((point) => point.y));
  const maxY = Math.max(...points.map((point) => point.y), 1);
  const xAt = (x: number) =>
    95 + ((x - minX) / Math.max(1e-9, maxX - minX)) * 740;
  const yAt = (y: number) =>
    500 - ((y - minY) / Math.max(1e-9, maxY - minY)) * 390;
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline
        scene={scene}
        tokens={tokens}
        eyebrow="Data, with context"
      />
      <Panel
        tokens={tokens}
        style={{ height: 650, padding: 25, position: "relative" }}
      >
        <svg
          width="100%"
          height="100%"
          viewBox="0 0 900 590"
          aria-label={`${visual.y_axis.label} by ${visual.x_axis.label}`}
        >
          {[0, 1, 2, 3, 4].map((tick) => (
            <line
              key={tick}
              x1={90}
              x2={850}
              y1={110 + tick * 98}
              y2={110 + tick * 98}
              stroke={tokens.panelBorder}
              strokeWidth={2}
            />
          ))}
          <line
            x1={90}
            y1={500}
            x2={850}
            y2={500}
            stroke={tokens.text}
            strokeWidth={4}
          />
          <line
            x1={90}
            y1={95}
            x2={90}
            y2={500}
            stroke={tokens.text}
            strokeWidth={4}
          />
          {visual.series.map((series, seriesIndex) => {
            const seriesColor = color(tokens, series.color);
            return series.points.map((point, index) => {
              const px = xAt(point.x);
              const py = yAt(point.y);
              if (visual.chart_type === "bar") {
                return (
                  <rect
                    key={`${series.label}-${index}`}
                    x={px - 22 + seriesIndex * 12}
                    y={py + (500 - py) * (1 - progress)}
                    width={38}
                    height={(500 - py) * progress}
                    rx={7}
                    fill={seriesColor}
                  />
                );
              }
              const previous = series.points[index - 1];
              return (
                <React.Fragment key={`${series.label}-${index}`}>
                  {previous && visual.chart_type === "line" ? (
                    <line
                      x1={xAt(previous.x)}
                      y1={yAt(previous.y)}
                      x2={px}
                      y2={py}
                      pathLength={1}
                      stroke={seriesColor}
                      strokeWidth={8}
                      strokeDasharray={1}
                      strokeDashoffset={1 - progress}
                    />
                  ) : null}
                  <circle
                    cx={px}
                    cy={py}
                    r={10 * progress}
                    fill={seriesColor}
                  />
                </React.Fragment>
              );
            });
          })}
          {visual.annotations.map((annotation, index) => {
            const pointX = xAt(annotation.x);
            const pointY = yAt(annotation.y);
            const placeLeft = pointX > 650;
            const direction = placeLeft ? -1 : 1;
            return (
              <g
                key={`${annotation.label}-${index}`}
                opacity={annotationProgress}
              >
                <line
                  x1={pointX}
                  y1={pointY}
                  x2={pointX + direction * 50}
                  y2={Math.max(28, pointY - 50)}
                  stroke={tokens.warning}
                  strokeWidth={4}
                />
                <text
                  x={pointX + direction * 57}
                  y={Math.max(26, pointY - 52)}
                  textAnchor={placeLeft ? "end" : "start"}
                  fill={tokens.warning}
                  fontSize={22}
                  fontWeight={700}
                >
                  {annotation.label}
                </text>
              </g>
            );
          })}
          <text
            x={470}
            y={570}
            textAnchor="middle"
            fill={tokens.muted}
            fontSize={24}
          >
            {visual.x_axis.label}
            {visual.x_axis.unit ? ` (${visual.x_axis.unit})` : ""}
          </text>
          <text
            x={24}
            y={300}
            textAnchor="middle"
            fill={tokens.muted}
            fontSize={24}
            transform="rotate(-90 24 300)"
          >
            {visual.y_axis.label}
            {visual.y_axis.unit ? ` (${visual.y_axis.unit})` : ""}
          </text>
        </svg>
      </Panel>
    </Frame>
  );
}

export const Timeline: React.FC<PrimitiveProps> = ({ scene, themeName }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const progress = Math.min(
    1,
    sceneProgressFor(frame, Math.max(1, Math.round(scene.duration * fps))) *
      1.2,
  );
  const visual =
    "kind" in scene.visual && scene.visual.kind === "timeline"
      ? scene.visual
      : null;
  if (!visual) return null;
  const values = visual.events.map((event) => event.time);
  const min = Math.min(...values);
  const max = Math.max(...values);
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline
        scene={scene}
        tokens={tokens}
        eyebrow="Events in sequence"
      />
      <Panel
        tokens={tokens}
        style={{ height: 650, position: "relative", padding: "42px 54px" }}
      >
        <div
          style={{
            position: "absolute",
            left: 120,
            top: 75,
            bottom: 75,
            width: 7,
            borderRadius: 7,
            background: tokens.panelBorder,
          }}
        >
          <div
            style={{
              width: "100%",
              height: `${progress * 100}%`,
              background: tokens.accent,
              borderRadius: 7,
            }}
          />
        </div>
        {visual.events.map((event) => {
          const ratio = (event.time - min) / Math.max(1e-9, max - min);
          const visible = progress >= ratio * 0.9;
          return (
            <div
              key={`${event.time}-${event.label}`}
              style={{
                position: "absolute",
                left: 96,
                right: 45,
                top: 64 + ratio * 500,
                display: "grid",
                gridTemplateColumns: "56px 150px 1fr",
                alignItems: "center",
                gap: 18,
                opacity: visible ? 1 : 0.18,
                transform: `translateX(${visible ? 0 : 25}px)`,
              }}
            >
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: "50%",
                  background: visible ? tokens.warning : tokens.panelBorder,
                  border: `7px solid ${tokens.panel}`,
                }}
              />
              <strong style={{ fontSize: 24, color: tokens.warning }}>
                {event.time} {visual.unit}
              </strong>
              <div>
                <div style={{ fontSize: 29, fontWeight: 700 }}>
                  {event.label}
                </div>
                {event.detail ? (
                  <div style={{ fontSize: 21, color: tokens.muted }}>
                    {event.detail}
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </Panel>
    </Frame>
  );
};
