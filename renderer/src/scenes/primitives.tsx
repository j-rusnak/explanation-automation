import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { SceneData } from "../schemas/project";
import { theme } from "../themes/tokens";

type ColorToken = Exclude<keyof typeof theme, "font">;
const SAFE_COLOR = /^#[0-9a-f]{3,8}$/i;
const sceneColor = (scene: SceneData, token: ColorToken): string => {
  const override = scene.theme_overrides[token];
  return override && SAFE_COLOR.test(override) ? override : theme[token];
};
const sceneBackground = (scene: SceneData): string | undefined => {
  const override = scene.theme_overrides.background;
  return override && SAFE_COLOR.test(override) ? override : undefined;
};

const Title: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <h1 style={{ fontSize: 94, lineHeight: 1.02, margin: 0, letterSpacing: -3 }}>
    {children}
  </h1>
);
const Citation: React.FC<{ scene: SceneData }> = ({ scene }) =>
  scene.evidence_label ? (
    <div
      style={{
        position: "absolute",
        top: 92,
        right: 64,
        color: sceneColor(scene, "citation"),
        fontSize: 24,
        letterSpacing: 2,
      }}
    >
      {scene.evidence_label} · {scene.claim_ids.join(", ")}
    </div>
  ) : null;
const Frame: React.FC<{ scene: SceneData; children: React.ReactNode }> = ({
  scene,
  children,
}) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      padding: "190px 68px 390px",
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      gap: 62,
      background: sceneBackground(scene),
    }}
  >
    <Citation scene={scene} />
    {children}
  </div>
);

export const KineticText: React.FC<{ scene: SceneData }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = spring({ frame, fps, config: { damping: 16 } });
  return (
    <Frame scene={scene}>
      <div style={{ transform: `scale(${scale})` }}>
        <Title>{scene.visual.title}</Title>
      </div>
      <p style={{ fontSize: 46, color: sceneColor(scene, "muted") }}>
        {scene.visual.body}
      </p>
    </Frame>
  );
};
export const SourceReceipt: React.FC<{ scene: SceneData }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 18], [0, 1], {
    extrapolateRight: "clamp",
  });
  return (
    <Frame scene={scene}>
      <Title>{scene.visual.title}</Title>
      <div
        style={{
          opacity,
          background: "#f5f1e8",
          color: "#172033",
          padding: 52,
          borderRadius: 18,
          boxShadow: "0 26px 70px #0008",
        }}
      >
        <div style={{ fontSize: 24, letterSpacing: 3 }}>SOURCE RECEIPT</div>
        <p style={{ fontSize: 42, lineHeight: 1.35 }}>
          {scene.visual.evidence_excerpt ?? scene.visual.body}
        </p>
        <code style={{ fontSize: 25 }}>
          {scene.visual.evidence_id} · {scene.visual.source_locator}
        </code>
      </div>
    </Frame>
  );
};
export const MechanismDiagram: React.FC<{ scene: SceneData }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [5, 45], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <Frame scene={scene}>
      <Title>{scene.visual.title}</Title>
      <div
        style={{
          position: "relative",
          height: 620,
          background: sceneColor(scene, "panel"),
          borderRadius: 32,
        }}
      >
        <svg
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
          }}
        >
          {scene.visual.edges.map((edge, index) => {
            const source = scene.visual.nodes.find(
              (node) => node.id === edge.source,
            );
            const target = scene.visual.nodes.find(
              (node) => node.id === edge.target,
            );
            if (!source || !target) return null;
            return (
              <line
                key={`${edge.source}-${edge.target}-${index}`}
                x1={`${source.x * 80 + 10}%`}
                y1={`${source.y * 80 + 10}%`}
                x2={`${target.x * 80 + 10}%`}
                y2={`${target.y * 80 + 10}%`}
                pathLength={1}
                stroke={sceneColor(scene, "warning")}
                strokeWidth={8}
                strokeLinecap="round"
                strokeDasharray={1}
                strokeDashoffset={1 - progress}
              />
            );
          })}
        </svg>
        {scene.visual.edges.map((edge, index) => {
          const source = scene.visual.nodes.find(
            (node) => node.id === edge.source,
          );
          const target = scene.visual.nodes.find(
            (node) => node.id === edge.target,
          );
          if (!source || !target || !edge.label) return null;
          return (
            <div
              key={`label-${edge.source}-${edge.target}-${index}`}
              style={{
                position: "absolute",
                left: `${((source.x + target.x) / 2) * 80 + 10}%`,
                top: `${((source.y + target.y) / 2) * 80 + 5}%`,
                transform: "translate(-50%, -50%)",
                padding: "7px 14px",
                borderRadius: 12,
                background: sceneColor(scene, "background"),
                color: sceneColor(scene, "warning"),
                fontSize: 24,
                opacity: progress,
              }}
            >
              {edge.label}
            </div>
          );
        })}
        {scene.visual.nodes.map((node, i) => (
          <div
            key={node.id}
            style={{
              position: "absolute",
              left: `${node.x * 80 + 10}%`,
              top: `${node.y * 80 + 10}%`,
              transform: `translate(-50%,-50%) scale(${i === 0 ? 1 : 0.7 + 0.3 * progress})`,
              padding: "28px 34px",
              borderRadius: 18,
              fontSize: 30,
              background:
                node.state === "active"
                  ? sceneColor(scene, "accent")
                  : "#26395f",
              color:
                node.state === "active"
                  ? sceneColor(scene, "background")
                  : sceneColor(scene, "text"),
            }}
          >
            {node.label}
          </div>
        ))}
      </div>
    </Frame>
  );
};
export const ChartReveal: React.FC<{ scene: SceneData }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [8, 55], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const max = Math.max(...scene.visual.series, 1);
  return (
    <Frame scene={scene}>
      <Title>{scene.visual.title}</Title>
      <div style={{ height: 620, display: "flex", alignItems: "end", gap: 22 }}>
        {scene.visual.series.map((value, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              height: `${(value / max) * progress * 100}%`,
              minHeight: 8,
              background:
                i === scene.visual.series.length - 1
                  ? sceneColor(scene, "warning")
                  : sceneColor(scene, "accent"),
              borderRadius: "12px 12px 0 0",
              position: "relative",
            }}
          >
            <span
              style={{
                position: "absolute",
                bottom: -55,
                width: "100%",
                textAlign: "center",
                fontSize: 22,
              }}
            >
              {scene.visual.labels[i]}
            </span>
          </div>
        ))}
      </div>
    </Frame>
  );
};
export const ParameterSimulation: React.FC<{ scene: SceneData }> = ({
  scene,
}) => {
  const frame = useCurrentFrame();
  const offset = Math.sin(frame / 12) * 90 * (scene.visual.parameter ?? 0.5);
  return (
    <Frame scene={scene}>
      <Title>{scene.visual.title}</Title>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 26 }}>
        {[scene.visual.left, scene.visual.right].map((label, index) => (
          <div
            key={`${label}-${index}`}
            style={{
              height: 650,
              background: sceneColor(scene, "panel"),
              borderRadius: 30,
              padding: 28,
              overflow: "hidden",
            }}
          >
            <h2 style={{ fontSize: 32 }}>{label}</h2>
            {Array.from({ length: 14 }, (_, row) => (
              <div
                key={row}
                style={{
                  height: 32,
                  margin: 8,
                  background:
                    index === 0
                      ? sceneColor(scene, "accent")
                      : sceneColor(scene, "citation"),
                  transform: `translateX(${index === 0 ? (offset * row) / 14 : 0}px)`,
                }}
              />
            ))}
          </div>
        ))}
      </div>
    </Frame>
  );
};
export const Comparison: React.FC<{ scene: SceneData }> = ({ scene }) => (
  <Frame scene={scene}>
    <Title>{scene.visual.title}</Title>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 28 }}>
      <div
        style={{
          background: sceneColor(scene, "panel"),
          padding: 45,
          height: 580,
          borderRadius: 28,
        }}
      >
        <h2 style={{ fontSize: 42 }}>{scene.visual.left}</h2>
        <div
          style={{
            height: 350,
            borderLeft: `20px solid ${sceneColor(scene, "accent")}`,
            margin: "60px 0 0 44%",
          }}
        />
      </div>
      <div
        style={{
          background: sceneColor(scene, "panel"),
          padding: 45,
          height: 580,
          borderRadius: 28,
        }}
      >
        <h2 style={{ fontSize: 42 }}>{scene.visual.right}</h2>
        <div
          style={{
            height: 350,
            borderLeft: `20px solid ${sceneColor(scene, "warning")}`,
            transform: "skewX(-18deg)",
            margin: "60px 0 0 44%",
          }}
        />
      </div>
    </div>
  </Frame>
);
export const LimitationCard: React.FC<{ scene: SceneData }> = ({ scene }) => (
  <Frame scene={scene}>
    <div
      style={{
        border: `4px solid ${sceneColor(scene, "warning")}`,
        borderRadius: 38,
        padding: 58,
        background: "#2b2431",
      }}
    >
      <div
        style={{
          fontSize: 26,
          color: sceneColor(scene, "warning"),
          letterSpacing: 4,
        }}
      >
        IMPORTANT LIMITATION
      </div>
      <Title>{scene.visual.title}</Title>
      <p
        style={{
          fontSize: 43,
          lineHeight: 1.35,
          color: sceneColor(scene, "muted"),
        }}
      >
        {scene.visual.body}
      </p>
    </div>
  </Frame>
);

export const Primitive: React.FC<{ scene: SceneData }> = ({ scene }) => {
  const components = {
    KineticText,
    SourceReceipt,
    MechanismDiagram,
    ChartReveal,
    ParameterSimulation,
    Comparison,
    LimitationCard,
  };
  const Component = components[scene.primitive];
  return <Component scene={scene} />;
};
