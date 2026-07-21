import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { sceneProgressFor } from "../pacing/rhythm";
import type { SceneData } from "../schemas/project";
import type { ThemeTokens } from "../themes/tokens";
import { RollingShutterHero } from "./hero-object";
import {
  Frame,
  Panel,
  SceneHeadline,
  Shape,
  progressFor,
  sceneTheme,
  type PrimitiveProps,
} from "./shared";

type Graph = {
  nodes: Array<{
    id: string;
    label: string;
    x: number;
    y: number;
    state: "normal" | "active" | "muted";
  }>;
  edges: Array<{ source: string; target: string; label?: string | null }>;
  activeStep?: string | null;
};

const graphFromScene = (scene: SceneData): Graph => {
  const visual = scene.visual;
  if (
    "kind" in visual &&
    (visual.kind === "mechanism-diagram" || visual.kind === "process-flow")
  ) {
    return {
      nodes: visual.nodes,
      edges: visual.edges,
      activeStep: "active_step_id" in visual ? visual.active_step_id : null,
    };
  }
  if (!("kind" in visual)) return { nodes: visual.nodes, edges: visual.edges };
  return { nodes: [], edges: [] };
};

const GraphView: React.FC<{
  scene: SceneData;
  tokens: ThemeTokens;
  sequential?: boolean;
  bare?: boolean;
}> = ({ scene, tokens, sequential = false, bare = false }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = progressFor(scene, frame, fps);
  const graph = graphFromScene(scene);
  const content = (
    <>
      <svg
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
        }}
      >
        {graph.edges.map((edge, index) => {
          const source = graph.nodes.find((node) => node.id === edge.source);
          const target = graph.nodes.find((node) => node.id === edge.target);
          if (!source || !target) return null;
          const edgeProgress = sequential
            ? Math.max(0, Math.min(1, progress * graph.edges.length - index))
            : progress;
          return (
            <line
              key={`${edge.source}-${edge.target}-${index}`}
              x1={`${source.x * 84 + 8}%`}
              y1={`${source.y * 80 + 10}%`}
              x2={`${target.x * 84 + 8}%`}
              y2={`${target.y * 80 + 10}%`}
              pathLength={1}
              stroke={tokens.warning}
              strokeWidth={7}
              strokeLinecap="round"
              strokeDasharray={1}
              strokeDashoffset={1 - edgeProgress}
            />
          );
        })}
      </svg>
      {graph.nodes.map((node, index) => {
        const nodeProgress = Math.max(
          0,
          Math.min(1, progress * graph.nodes.length - index),
        );
        const active = node.state === "active" || graph.activeStep === node.id;
        return (
          <div
            key={node.id}
            style={{
              position: "absolute",
              left: `${node.x * 84 + 8}%`,
              top: `${node.y * 80 + 10}%`,
              transform: `translate(-50%,-50%) scale(${0.8 + 0.2 * (sequential ? nodeProgress : progress)})`,
              opacity: sequential ? 0.25 + nodeProgress * 0.75 : 1,
              padding: "22px 29px",
              minWidth: 135,
              textAlign: "center",
              borderRadius: Math.max(12, tokens.radius - 6),
              border: `3px solid ${active ? tokens.accent : tokens.panelBorder}`,
              fontSize: 28,
              fontWeight: 700,
              background: active ? tokens.accent : tokens.background,
              color: active
                ? tokens.background
                : node.state === "muted"
                  ? tokens.muted
                  : tokens.text,
            }}
          >
            {node.label}
          </div>
        );
      })}
    </>
  );
  const style: React.CSSProperties = {
    position: "relative",
    height: 650,
    overflow: "hidden",
  };
  return bare ? (
    <div style={style}>{content}</div>
  ) : (
    <Panel tokens={tokens} style={style}>
      {content}
    </Panel>
  );
};

const KineticMechanismHero: React.FC<{
  scene: SceneData;
  tokens: ThemeTokens;
}> = ({ scene, tokens }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = progressFor(scene, frame, fps);
  const graph = graphFromScene(scene);
  return (
    <div
      style={{
        position: "relative",
        height: 660,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <RollingShutterHero
        tokens={tokens}
        idPrefix={`${scene.scene_id}-mechanism`}
        progress={progress}
        scanProgress={progress}
        distortion={0.68}
        showReference
        width={660}
        height={535}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          display: "flex",
          justifyContent: "center",
          gap: 13,
          flexWrap: "wrap",
        }}
      >
        {graph.nodes.map((node, index) => {
          const reveal = Math.max(
            0,
            Math.min(1, progress * graph.nodes.length - index + 0.45),
          );
          const active =
            node.state === "active" || graph.activeStep === node.id;
          return (
            <div
              key={node.id}
              style={{
                padding: "12px 17px",
                borderRadius: 999,
                border: `3px solid ${active ? tokens.warning : tokens.accent}`,
                background: active ? tokens.warning : `${tokens.background}ee`,
                color: active ? tokens.background : tokens.text,
                fontSize: 21,
                fontWeight: 800,
                opacity: 0.28 + reveal * 0.72,
                transform: `translateY(${(1 - reveal) * 16}px)`,
              }}
            >
              {node.label}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export const MechanismDiagram: React.FC<PrimitiveProps> = ({
  scene,
  themeName,
}) => {
  const tokens = sceneTheme(scene, themeName);
  const useHero = themeName === "kinetic-pop" && scene.layout === "hero";
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline scene={scene} tokens={tokens} eyebrow="How it works" />
      {useHero ? (
        <KineticMechanismHero scene={scene} tokens={tokens} />
      ) : (
        <GraphView
          scene={scene}
          tokens={tokens}
          bare={themeName === "kinetic-pop"}
        />
      )}
    </Frame>
  );
};

export const ProcessFlow: React.FC<PrimitiveProps> = ({ scene, themeName }) => {
  const tokens = sceneTheme(scene, themeName);
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline scene={scene} tokens={tokens} eyebrow="Step by step" />
      <GraphView scene={scene} tokens={tokens} sequential />
    </Frame>
  );
};

export const ParameterSimulation: React.FC<PrimitiveProps> = ({
  scene,
  themeName,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const visual = scene.visual;
  const typed =
    "kind" in visual && visual.kind === "parameter-simulation" ? visual : null;
  const normalized = typed
    ? (typed.value - typed.minimum) / (typed.maximum - typed.minimum)
    : !("kind" in visual)
      ? (visual.parameter ?? 0.5)
      : 0.5;
  const offset = Math.sin(frame / 18) * 75 * normalized;
  const labels = typed
    ? [typed.left_label, typed.right_label]
    : !("kind" in visual)
      ? [visual.left, visual.right]
      : ["Low", "High"];
  if (themeName === "kinetic-pop") {
    const progress = progressFor(scene, frame, fps);
    return (
      <Frame scene={scene} tokens={tokens}>
        <SceneHeadline
          scene={scene}
          tokens={tokens}
          eyebrow="Parameter simulation"
        />
        <div
          style={{
            height: 650,
            display: "grid",
            gridTemplateColumns: "0.62fr 1.38fr",
            alignItems: "center",
            gap: 20,
          }}
        >
          <div>
            {typed ? (
              <>
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 11,
                    color: tokens.warning,
                  }}
                >
                  <span style={{ fontSize: 88, fontWeight: 900 }}>
                    {typed.value}
                  </span>
                  <span style={{ fontSize: 31, fontWeight: 800 }}>
                    {typed.unit}
                  </span>
                </div>
                <div
                  style={{
                    color: tokens.muted,
                    fontSize: 24,
                    lineHeight: 1.2,
                  }}
                >
                  {typed.parameter_label}
                </div>
              </>
            ) : null}
            <div
              style={{
                marginTop: 31,
                color: tokens.accent,
                fontSize: 25,
                fontWeight: 800,
              }}
            >
              {labels[0]} → {labels[1]}
            </div>
          </div>
          <RollingShutterHero
            tokens={tokens}
            idPrefix={`${scene.scene_id}-parameter`}
            progress={progress}
            scanProgress={progress}
            distortion={normalized * 0.82}
            showReference
            width={595}
            height={535}
          />
        </div>
      </Frame>
    );
  }
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline
        scene={scene}
        tokens={tokens}
        eyebrow="Parameter simulation"
      />
      {typed ? (
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 17,
            color: tokens.warning,
          }}
        >
          <span style={{ fontSize: 67, fontWeight: 700 }}>{typed.value}</span>
          <span style={{ fontSize: 28 }}>{typed.unit}</span>
          <span style={{ fontSize: 24, color: tokens.muted }}>
            {typed.parameter_label}
          </span>
        </div>
      ) : null}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {labels.map((label, index) => (
          <Panel
            key={`${label}-${index}`}
            tokens={tokens}
            style={{ height: 510, padding: 28, overflow: "hidden" }}
          >
            <h2 style={{ fontSize: 31, margin: "0 0 36px" }}>{label}</h2>
            {Array.from({ length: 13 }, (_, row) => (
              <div
                key={row}
                style={{
                  height: 23,
                  margin: "10px 16px",
                  borderRadius: 4,
                  background: index === 0 ? tokens.accent : tokens.citation,
                  transform: `translateX(${index === 1 ? (offset * row) / 13 : 0}px)`,
                }}
              />
            ))}
          </Panel>
        ))}
      </div>
    </Frame>
  );
};

export const RasterScan: React.FC<PrimitiveProps> = ({ scene, themeName }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const progress = progressFor(scene, frame, fps);
  const scanProgress = Math.min(
    1,
    sceneProgressFor(frame, Math.max(1, Math.round(scene.duration * fps))) *
      1.15,
  );
  const visual =
    "kind" in scene.visual && scene.visual.kind === "raster-scan"
      ? scene.visual
      : null;
  if (!visual) return null;
  const feature =
    visual.subject === "blade" || visual.subject === "pole"
      ? "straight-edge"
      : visual.subject;
  if (themeName === "kinetic-pop") {
    return (
      <Frame scene={scene} tokens={tokens}>
        <SceneHeadline
          scene={scene}
          tokens={tokens}
          eyebrow="Readout over time"
        />
        <div
          style={{
            height: 665,
            position: "relative",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          <RollingShutterHero
            tokens={tokens}
            idPrefix={`${scene.scene_id}-raster`}
            progress={progress}
            scanProgress={scanProgress}
            distortion={visual.distortion}
            direction={visual.direction}
            immediateProof={scene.order === 0}
            showReference
            width={745}
            height={610}
          />
          <div
            style={{
              position: "absolute",
              left: 92,
              top: 42,
              padding: "12px 17px",
              borderRadius: 999,
              background: tokens.accent,
              color: tokens.background,
              fontSize: 23,
              fontWeight: 900,
            }}
          >
            {visual.before_label}
          </div>
          <div
            style={{
              position: "absolute",
              right: 92,
              bottom: 44,
              maxWidth: 230,
              textAlign: "right",
              color: tokens.warning,
              fontSize: 25,
              fontWeight: 900,
              padding: "10px 13px",
              borderRadius: 12,
              background: `${tokens.background}e8`,
            }}
          >
            {visual.after_label}
            <div style={{ color: tokens.muted, fontSize: 20, marginTop: 7 }}>
              {visual.scan_label}
            </div>
          </div>
        </div>
      </Frame>
    );
  }
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline
        scene={scene}
        tokens={tokens}
        eyebrow="Readout over time"
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 23 }}>
        {[false, true].map((distorted, panelIndex) => (
          <Panel
            key={String(distorted)}
            tokens={tokens}
            style={{
              position: "relative",
              height: 610,
              overflow: "hidden",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: 25,
                left: 28,
                zIndex: 2,
                color: tokens.muted,
                fontSize: 25,
              }}
            >
              {distorted ? visual.after_label : visual.before_label}
            </div>
            <Shape
              feature={feature}
              distorted={distorted}
              tokens={tokens}
              progress={progress * visual.distortion}
            />
            {distorted
              ? Array.from({ length: visual.rows }, (_, row) => {
                  const ratio = row / Math.max(1, visual.rows - 1);
                  const active =
                    visual.direction === "bottom-to-top"
                      ? ratio >= 1 - scanProgress
                      : ratio <= scanProgress;
                  const horizontalScan = visual.direction !== "left-to-right";
                  return (
                    <div
                      key={row}
                      style={{
                        position: "absolute",
                        left: horizontalScan ? 0 : `${ratio * 100}%`,
                        right: horizontalScan ? 0 : undefined,
                        top: horizontalScan ? `${12 + ratio * 84}%` : 0,
                        bottom: horizontalScan ? undefined : 0,
                        width: horizontalScan ? undefined : 2,
                        height: horizontalScan ? 2 : undefined,
                        background: active
                          ? tokens.warning
                          : `${tokens.citation}26`,
                        boxShadow:
                          active && Math.abs(ratio - scanProgress) < 0.06
                            ? `0 0 20px ${tokens.warning}`
                            : undefined,
                      }}
                    />
                  );
                })
              : null}
            {panelIndex === 1 ? (
              <div
                style={{
                  position: "absolute",
                  bottom: 24,
                  right: 25,
                  color: tokens.warning,
                  fontSize: 21,
                }}
              >
                {visual.scan_label}
              </div>
            ) : null}
          </Panel>
        ))}
      </div>
    </Frame>
  );
};

export const TimeSlice: React.FC<PrimitiveProps> = ({ scene, themeName }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const progress = Math.min(
    1,
    sceneProgressFor(frame, Math.max(1, Math.round(scene.duration * fps))) *
      1.2,
  );
  const visual =
    "kind" in scene.visual && scene.visual.kind === "time-slice"
      ? scene.visual
      : null;
  if (!visual) return null;
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline
        scene={scene}
        tokens={tokens}
        eyebrow="One frame, many moments"
      />
      <Panel
        tokens={tokens}
        style={{
          padding: 35,
          minHeight: 620,
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 17,
        }}
      >
        {visual.slices.map((slice, index) => {
          const shown = Math.max(
            0,
            Math.min(1, progress * visual.slices.length - index),
          );
          return (
            <div
              key={`${slice.time}-${slice.label}`}
              style={{
                opacity: 0.15 + shown * 0.85,
                borderLeft: `5px solid ${tokens.accent}`,
                background: `${tokens.background}aa`,
                borderRadius: 12,
                padding: "22px 24px",
                transform: `translateX(${slice.offset * 45 * shown}px)`,
              }}
            >
              <div
                style={{ color: tokens.warning, fontSize: 22, fontWeight: 700 }}
              >
                {slice.time} {visual.unit}
              </div>
              <div style={{ fontSize: 29, marginTop: 8 }}>{slice.label}</div>
            </div>
          );
        })}
      </Panel>
    </Frame>
  );
};

const Grid: React.FC<{
  rows: number;
  columns: number;
  skew: number;
  curvature: number;
  tokens: ThemeTokens;
  progress: number;
}> = ({ rows, columns, skew, curvature, tokens, progress }) => (
  <div
    style={{
      width: 330,
      height: 450,
      display: "grid",
      gridTemplateColumns: `repeat(${columns}, 1fr)`,
      gridTemplateRows: `repeat(${rows}, 1fr)`,
    }}
  >
    {Array.from({ length: rows * columns }, (_, index) => {
      const row = Math.floor(index / columns);
      const column = index % columns;
      const rowRatio = row / Math.max(1, rows - 1);
      const columnRatio = column / Math.max(1, columns - 1);
      const x =
        (skew * rowRatio * 40 +
          curvature * Math.sin(columnRatio * Math.PI) * 25) *
        progress;
      return (
        <div
          key={index}
          style={{
            border: `1.5px solid ${tokens.accent}99`,
            transform: `translateX(${x}px)`,
          }}
        />
      );
    })}
  </div>
);

export const GridWarp: React.FC<PrimitiveProps> = ({ scene, themeName }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const progress = progressFor(scene, frame, fps);
  const visual =
    "kind" in scene.visual && scene.visual.kind === "grid-warp"
      ? scene.visual
      : null;
  if (!visual) return null;
  if (themeName === "kinetic-pop") {
    return (
      <Frame scene={scene} tokens={tokens}>
        <SceneHeadline
          scene={scene}
          tokens={tokens}
          eyebrow="Geometry changes"
        />
        <div
          style={{
            height: 650,
            position: "relative",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <RollingShutterHero
            tokens={tokens}
            idPrefix={`${scene.scene_id}-grid-warp`}
            progress={progress}
            scanProgress={progress}
            distortion={visual.skew}
            curvature={visual.curvature}
            showReference
            width={720}
            height={590}
          />
          <div
            style={{
              position: "absolute",
              left: 88,
              top: 52,
              color: tokens.accent,
              fontSize: 24,
              fontWeight: 900,
              padding: "9px 12px",
              borderRadius: 12,
              background: `${tokens.background}e8`,
            }}
          >
            {visual.before_label}
          </div>
          <div
            style={{
              position: "absolute",
              right: 88,
              bottom: 50,
              color: tokens.warning,
              fontSize: 26,
              fontWeight: 900,
              padding: "9px 12px",
              borderRadius: 12,
              background: `${tokens.background}e8`,
            }}
          >
            {visual.after_label}
          </div>
        </div>
      </Frame>
    );
  }
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline scene={scene} tokens={tokens} eyebrow="Geometry changes" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 23 }}>
        {[
          { label: visual.before_label, skew: 0, curvature: 0 },
          {
            label: visual.after_label,
            skew: visual.skew,
            curvature: visual.curvature,
          },
        ].map((item) => (
          <Panel
            key={item.label}
            tokens={tokens}
            style={{ height: 590, padding: 28, overflow: "hidden" }}
          >
            <div
              style={{ color: tokens.muted, fontSize: 25, marginBottom: 27 }}
            >
              {item.label}
            </div>
            <div style={{ display: "flex", justifyContent: "center" }}>
              <Grid
                rows={visual.rows}
                columns={visual.columns}
                skew={item.skew}
                curvature={item.curvature}
                tokens={tokens}
                progress={progress}
              />
            </div>
          </Panel>
        ))}
      </div>
    </Frame>
  );
};
