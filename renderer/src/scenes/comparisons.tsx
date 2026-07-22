import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { RollingShutterHero } from "./hero-object";
import { KineticTag } from "./modern-graphics";
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

export const comparisonCaptureMode = (
  distorted: boolean,
): "rolling" | "shared" => (distorted ? "rolling" : "shared");

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
            position: "relative",
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 0,
            height: 650,
            borderTop: `3px solid ${tokens.panelBorder}`,
            borderBottom: `3px solid ${tokens.panelBorder}`,
            background: `linear-gradient(90deg, ${tokens.background}99 0 50%, ${tokens.panel}bb 50% 100%)`,
            boxShadow: "0 26px 70px #0005",
          }}
        >
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              top: 28,
              bottom: 28,
              left: "50%",
              width: 3,
              background: `linear-gradient(${tokens.accent}, ${tokens.warning})`,
              opacity: 0.76,
            }}
          />
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
                  padding: "24px 20px 20px",
                }}
              >
                <KineticTag
                  tokens={tokens}
                  color={distorted ? tokens.danger : tokens.accent}
                >
                  {side.label}
                </KineticTag>
                <RollingShutterHero
                  tokens={tokens}
                  idPrefix={`${scene.scene_id}-comparison-${index}`}
                  progress={progress}
                  scanProgress={progress}
                  distortion={distorted ? 0.78 : 0}
                  showReference={distorted}
                  captureMode={comparisonCaptureMode(distorted)}
                  width={420}
                  height={425}
                />
                <div
                  style={{
                    textAlign: "center",
                    minHeight: 86,
                    maxWidth: 410,
                  }}
                >
                  <strong style={{ fontSize: 34, lineHeight: 1.05 }}>
                    {side.value}
                  </strong>
                  {"detail" in side && side.detail ? (
                    <div
                      style={{
                        marginTop: 7,
                        fontSize: 25,
                        lineHeight: 1.12,
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
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tokens = sceneTheme(scene, themeName);
  const reveal = progressFor(scene, frame, fps);
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
            borderRadius: Math.max(12, tokens.radius - 4),
            border: `3px solid ${tokens.panelBorder}`,
            background: `linear-gradient(135deg, ${tokens.panel} 0%, ${tokens.panel} 62%, ${tokens.panelBorder}aa 100%)`,
            padding: "52px 54px",
            boxShadow: "0 28px 75px #0006",
          }}
        >
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              bottom: 0,
              width: 13,
              background: tokens.danger,
              transform: `scaleY(${reveal})`,
              transformOrigin: "top",
            }}
          />
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              width: 360,
              height: 360,
              right: -145,
              top: -155,
              borderRadius: "50%",
              border: `64px solid ${tokens.danger}`,
              opacity: 0.13,
            }}
          />
          <KineticTag tokens={tokens} color={tokens.danger}>
            IMPORTANT LIMITATION
          </KineticTag>
          <div style={{ margin: "30px 0 30px" }}>
            <SceneHeadline scene={scene} tokens={tokens} />
          </div>
          {limitation ? (
            <p
              style={{
                maxWidth: 830,
                fontSize: 48,
                lineHeight: 1.22,
                color: tokens.text,
                margin: 0,
                fontWeight: 800,
                opacity: 0.35 + reveal * 0.65,
                transform: `translateY(${(1 - reveal) * 18}px)`,
              }}
            >
              {limitation}
            </p>
          ) : null}
          {applies ? (
            <div
              style={{
                marginTop: 34,
                padding: "19px 0 0",
                borderTop: `3px solid ${tokens.danger}`,
                color: tokens.muted,
                fontSize: 29,
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
  if (themeName === "kinetic-pop") {
    return (
      <Frame scene={scene} tokens={tokens}>
        <SceneHeadline
          scene={scene}
          tokens={tokens}
          eyebrow="Reveal the difference"
        />
        <div
          style={{
            position: "relative",
            height: 650,
            overflow: "hidden",
            borderTop: `3px solid ${tokens.panelBorder}`,
            borderBottom: `3px solid ${tokens.panelBorder}`,
            background: tokens.background,
            boxShadow: "0 26px 70px #0005",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: `linear-gradient(135deg, ${tokens.panel}, ${tokens.background})`,
            }}
          >
            <Shape
              feature={visual.feature}
              distorted
              tokens={tokens}
              progress={1}
            />
            <div style={{ position: "absolute", top: 28, right: 28 }}>
              <KineticTag tokens={tokens} color={tokens.warning}>
                {visual.after_label}
              </KineticTag>
            </div>
          </div>
          <div
            style={{
              position: "absolute",
              inset: 0,
              width: `${divider}%`,
              overflow: "hidden",
              background: `linear-gradient(135deg, ${tokens.background}, ${tokens.panelBorder}66)`,
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
            <div style={{ position: "absolute", top: 28, left: 28 }}>
              <KineticTag tokens={tokens} color={tokens.accent}>
                {visual.before_label}
              </KineticTag>
            </div>
          </div>
          <div
            style={{
              position: "absolute",
              left: `${divider}%`,
              top: 0,
              bottom: 0,
              width: 8,
              background: tokens.text,
              boxShadow: `0 0 24px ${tokens.warning}`,
            }}
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
