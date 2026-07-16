import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import {
  Frame,
  Panel,
  SceneHeadline,
  Shape,
  progressFor,
  sceneTheme,
  type PrimitiveProps,
} from "./shared";

export const Comparison: React.FC<PrimitiveProps> = ({ scene, themeName }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const progress = progressFor(scene, frame, fps);
  const visual = scene.visual;
  const typed =
    "kind" in visual && visual.kind === "comparison" ? visual : null;
  const left = typed?.left ?? {
    label: !("kind" in visual) ? (visual.left ?? "Before") : "Before",
    value: "",
  };
  const right = typed?.right ?? {
    label: !("kind" in visual) ? (visual.right ?? "After") : "After",
    value: "",
  };
  const feature = typed?.feature ?? "straight-edge";
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline scene={scene} tokens={tokens} eyebrow="Side by side" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {[left, right].map((side, index) => (
          <Panel
            key={side.label}
            tokens={tokens}
            style={{
              height: 570,
              padding: 31,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
            }}
          >
            <div
              style={{
                alignSelf: "stretch",
                fontSize: 27,
                color: tokens.muted,
              }}
            >
              {side.label}
            </div>
            <div
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Shape
                feature={feature}
                distorted={index === 1}
                tokens={tokens}
                progress={progress}
              />
            </div>
            <strong style={{ fontSize: 31 }}>{side.value}</strong>
            {"detail" in side && side.detail ? (
              <span style={{ fontSize: 22, color: tokens.muted }}>
                {side.detail}
              </span>
            ) : null}
          </Panel>
        ))}
      </div>
    </Frame>
  );
};

export const LimitationCard: React.FC<PrimitiveProps> = ({
  scene,
  themeName,
}) => {
  const tokens = sceneTheme(scene, themeName);
  const visual = scene.visual;
  const limitation =
    "kind" in visual && visual.kind === "limitation"
      ? visual.limitation
      : !("kind" in visual)
        ? visual.body
        : null;
  const applies =
    "kind" in visual && visual.kind === "limitation"
      ? visual.applies_when
      : null;
  return (
    <Frame scene={scene} tokens={tokens}>
      <Panel
        tokens={tokens}
        style={{
          border: `4px solid ${tokens.warning}`,
          padding: "54px 52px",
          background:
            tokens.motif === "paper" ? "#fff9ec" : `${tokens.panel}fa`,
        }}
      >
        <div
          style={{
            fontSize: 24,
            color: tokens.warning,
            fontWeight: 700,
            letterSpacing: 4,
          }}
        >
          IMPORTANT LIMITATION
        </div>
        <div style={{ margin: "27px 0 34px" }}>
          <SceneHeadline scene={scene} tokens={tokens} />
        </div>
        {limitation ? (
          <p
            style={{
              fontSize: 39,
              lineHeight: 1.33,
              color: tokens.muted,
              margin: 0,
            }}
          >
            {limitation}
          </p>
        ) : null}
        {applies ? (
          <div style={{ marginTop: 30, fontSize: 25, color: tokens.warning }}>
            Applies when: {applies}
          </div>
        ) : null}
      </Panel>
    </Frame>
  );
};

export const BeforeAfterOverlay: React.FC<PrimitiveProps> = ({
  scene,
  themeName,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const progress = progressFor(scene, frame, fps);
  const visual =
    "kind" in scene.visual && scene.visual.kind === "before-after-overlay"
      ? scene.visual
      : null;
  if (!visual) return null;
  const divider = 15 + visual.divider * 70 * progress;
  return (
    <Frame scene={scene} tokens={tokens}>
      <SceneHeadline
        scene={scene}
        tokens={tokens}
        eyebrow="Reveal the difference"
      />
      <Panel
        tokens={tokens}
        style={{ position: "relative", height: 650, overflow: "hidden" }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Shape
            feature={visual.feature}
            distorted
            tokens={tokens}
            progress={1}
          />
          <div
            style={{
              position: "absolute",
              top: 26,
              right: 28,
              color: tokens.warning,
              fontSize: 25,
            }}
          >
            {visual.after_label}
          </div>
        </div>
        <div
          style={{
            position: "absolute",
            inset: 0,
            width: `${divider}%`,
            overflow: "hidden",
            background: tokens.panel,
          }}
        >
          <div
            style={{
              width: 950,
              height: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Shape feature={visual.feature} tokens={tokens} />
          </div>
          <div
            style={{
              position: "absolute",
              top: 26,
              left: 28,
              color: tokens.accent,
              fontSize: 25,
            }}
          >
            {visual.before_label}
          </div>
        </div>
        <div
          style={{
            position: "absolute",
            left: `${divider}%`,
            top: 0,
            bottom: 0,
            width: 7,
            background: tokens.text,
            boxShadow: "0 0 20px #0008",
          }}
        />
      </Panel>
    </Frame>
  );
};
