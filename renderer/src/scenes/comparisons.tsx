import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
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

export const comparisonSideIsDistorted = (
  distorted: boolean | null | undefined,
  index: number,
): boolean => distorted ?? index === 1;

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
  if (themeName === "kinetic-pop") {
    return (
      <Frame scene={scene} tokens={tokens}>
        <SceneHeadline scene={scene} tokens={tokens} eyebrow="Side by side" />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 20,
            height: 650,
          }}
        >
          {[left, right].map((side, index) => {
            const distorted = comparisonSideIsDistorted(
              "distorted" in side ? side.distorted : undefined,
              index,
            );
            return (
              <div
                key={side.label}
                style={{
                  minWidth: 0,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "space-between",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    alignSelf: "stretch",
                    color: distorted ? tokens.danger : tokens.accent,
                    fontSize: 28,
                    fontWeight: 900,
                    textAlign: "center",
                  }}
                >
                  {side.label}
                </div>
                <RollingShutterHero
                  tokens={tokens}
                  idPrefix={`${scene.scene_id}-comparison-${index}`}
                  progress={progress}
                  scanProgress={progress}
                  distortion={distorted ? 0.78 : 0}
                  showReference={distorted}
                  width={435}
                  height={440}
                />
                <div style={{ textAlign: "center", minHeight: 86 }}>
                  <strong style={{ fontSize: 31 }}>{side.value}</strong>
                  {"detail" in side && side.detail ? (
                    <div
                      style={{
                        marginTop: 7,
                        fontSize: 21,
                        color: tokens.muted,
                      }}
                    >
                      {side.detail}
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </Frame>
    );
  }
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
                distorted={comparisonSideIsDistorted(
                  "distorted" in side ? side.distorted : undefined,
                  index,
                )}
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
  if (themeName === "kinetic-pop") {
    return (
      <Frame scene={scene} tokens={tokens}>
        <div
          style={{
            minHeight: 690,
            position: "relative",
            overflow: "hidden",
            borderRadius: tokens.radius,
            border: `6px solid ${tokens.danger}`,
            background: `linear-gradient(145deg, ${tokens.panelBorder} 0%, ${tokens.panelBorder} 48%, ${tokens.panel} 48%, ${tokens.panel} 100%)`,
            padding: "49px 47px",
            boxShadow: `18px 18px 0 ${tokens.danger}`,
          }}
        >
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              height: 21,
              background: `repeating-linear-gradient(135deg, ${tokens.warning} 0 22px, ${tokens.background} 22px 44px)`,
            }}
          />
          <div
            style={{
              display: "inline-block",
              padding: "10px 16px",
              background: tokens.warning,
              color: tokens.background,
              fontSize: 24,
              fontWeight: 900,
              letterSpacing: 3,
              transform: "rotate(-2deg)",
            }}
          >
            SCOPE RESET
          </div>
          <div style={{ margin: "28px 0 30px" }}>
            <SceneHeadline scene={scene} tokens={tokens} />
          </div>
          {limitation ? (
            <p
              style={{
                maxWidth: 830,
                fontSize: 43,
                lineHeight: 1.22,
                color: tokens.text,
                margin: 0,
                fontWeight: 800,
              }}
            >
              {limitation}
            </p>
          ) : null}
          {applies ? (
            <div
              style={{
                marginTop: 34,
                padding: "15px 19px",
                borderLeft: `8px solid ${tokens.danger}`,
                background: `${tokens.background}bb`,
                color: tokens.warning,
                fontSize: 25,
                fontWeight: 800,
              }}
            >
              Applies when: {applies}
            </div>
          ) : null}
        </div>
      </Frame>
    );
  }
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
