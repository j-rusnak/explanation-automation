import React from "react";
import { AbsoluteFill } from "remotion";
import { safeZonePixels } from "../safe-zone";
import type { CoverCandidate, ProjectData } from "../schemas/project";
import {
  KineticBackdrop,
  isKineticPopTheme,
  kineticChapterFor,
} from "../scenes/shared";
import { RollingShutterHero } from "../scenes/hero-object";
import { getTheme } from "../themes/tokens";

export const KINETIC_COVER_CHAPTER = kineticChapterFor({
  layout: "hero",
  order: 0,
  primitive: "KineticText",
});

export const coverPaddingFor = (
  data: Pick<ProjectData, "safeZone" | "width" | "height">,
  layout: CoverCandidate["layout"],
): { top: number; right: number; bottom: number; left: number } => {
  const safe = safeZonePixels(data.safeZone, data.width, data.height);
  const minimum =
    layout === "editorial"
      ? { top: 165, right: 72, bottom: 135, left: 72 }
      : { top: 125, right: 64, bottom: 120, left: 64 };
  return {
    top: Math.max(minimum.top, safe.top),
    right: Math.max(minimum.right, safe.right),
    bottom: Math.max(minimum.bottom, safe.bottom),
    left: Math.max(minimum.left, safe.left),
  };
};

const CoverShape: React.FC<{
  feature: "straight-edge" | "grid" | "rotor" | "signal";
  distorted: boolean;
  accent: string;
  warning: string;
}> = ({ feature, distorted, accent, warning }) => {
  const active = distorted ? warning : accent;
  if (feature === "grid") {
    return (
      <div
        style={{
          width: 340,
          height: 430,
          display: "grid",
          gridTemplateColumns: "repeat(6, 1fr)",
          gridTemplateRows: "repeat(8, 1fr)",
          transform: distorted ? "skewX(-15deg)" : undefined,
        }}
      >
        {Array.from({ length: 48 }, (_, index) => (
          <div key={index} style={{ border: `2px solid ${active}` }} />
        ))}
      </div>
    );
  }
  if (feature === "rotor") {
    return (
      <div
        style={{
          position: "relative",
          width: 390,
          height: 390,
          transform: distorted ? "skewX(-18deg)" : undefined,
        }}
      >
        {[0, 60, 120].map((angle) => (
          <div
            key={angle}
            style={{
              position: "absolute",
              left: 184,
              top: 18,
              width: 24,
              height: 354,
              borderRadius: 20,
              background: active,
              transform: `rotate(${angle}deg)`,
            }}
          />
        ))}
        <div
          style={{
            position: "absolute",
            left: 151,
            top: 151,
            width: 90,
            height: 90,
            borderRadius: "50%",
            background: distorted ? accent : warning,
          }}
        />
      </div>
    );
  }
  if (feature === "signal") {
    return (
      <svg width="410" height="320" aria-hidden="true">
        {Array.from({ length: 20 }, (_, index) => {
          const x = index * 21;
          const amplitude = distorted ? 92 : 52;
          return (
            <line
              key={index}
              x1={x}
              y1={160 + Math.sin(index * 0.8) * amplitude}
              x2={x + 21}
              y2={160 + Math.sin((index + 1) * 0.8) * amplitude}
              stroke={active}
              strokeWidth={11}
              strokeLinecap="round"
            />
          );
        })}
      </svg>
    );
  }
  if (feature === "straight-edge" && distorted) {
    return (
      <svg width="390" height="540" viewBox="0 0 390 540" aria-hidden="true">
        <path
          d="M 108 505 Q 118 275 272 35"
          fill="none"
          stroke={active}
          strokeWidth={36}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 24px ${active}66)` }}
        />
      </svg>
    );
  }
  return (
    <div
      style={{
        width: 36,
        height: 520,
        borderRadius: 20,
        background: active,
        transform: distorted ? "skewX(-21deg)" : undefined,
        boxShadow: `0 0 55px ${active}77`,
      }}
    />
  );
};

const Hero: React.FC<{ candidate: CoverCandidate }> = ({ candidate }) => {
  const tokens = getTheme(candidate.palette);
  const kinetic = isKineticPopTheme(candidate.palette);
  const hero = candidate.hero;
  if (hero.kind === "comparison") {
    return (
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          width: "100%",
          gap: 26,
        }}
      >
        {[
          { label: hero.before_label, distorted: false },
          { label: hero.after_label, distorted: true },
        ].map((item) => (
          <div
            key={item.label}
            style={{
              height: 720,
              border: kinetic
                ? "none"
                : `3px solid ${item.distorted ? tokens.warning : tokens.accent}`,
              borderRadius: kinetic ? 36 : tokens.radius,
              background: kinetic
                ? `radial-gradient(circle, ${item.distorted ? tokens.warning : tokens.accent}54 0%, ${tokens.panel}7a 48%, transparent 74%)`
                : `${tokens.panel}ed`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              position: "relative",
              overflow: "hidden",
              transform: kinetic
                ? `translateY(${item.distorted ? 35 : -20}px) rotate(${item.distorted ? 3 : -3}deg)`
                : undefined,
            }}
          >
            <div
              style={{
                position: "absolute",
                top: 25,
                left: 28,
                color: item.distorted ? tokens.warning : tokens.accent,
                background: kinetic ? tokens.background : undefined,
                padding: kinetic ? "9px 14px" : undefined,
                fontSize: kinetic ? 25 : 27,
                fontWeight: kinetic ? 800 : 700,
                letterSpacing: kinetic ? 1.5 : undefined,
              }}
            >
              {item.label}
            </div>
            <CoverShape
              feature={hero.feature}
              distorted={item.distorted}
              accent={tokens.accent}
              warning={tokens.warning}
            />
          </div>
        ))}
      </div>
    );
  }
  if (hero.kind === "scanline") {
    const feature =
      hero.subject === "blade" || hero.subject === "pole"
        ? "straight-edge"
        : hero.subject;
    const useSensorHero =
      kinetic &&
      (hero.subject === "grid" ||
        hero.subject === "blade" ||
        hero.subject === "pole");
    return (
      <div
        style={{
          height: kinetic ? 670 : 720,
          width: "100%",
          borderRadius: kinetic ? 40 : tokens.radius,
          border: kinetic ? "none" : `3px solid ${tokens.panelBorder}`,
          background: kinetic
            ? `radial-gradient(circle at 60% 45%, ${tokens.accent}2e 0%, ${tokens.panel}99 48%, transparent 76%)`
            : tokens.panel,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          overflow: "hidden",
          isolation: "isolate",
        }}
      >
        {useSensorHero ? (
          <RollingShutterHero
            tokens={tokens}
            idPrefix="kinetic-cover-sensor"
            progress={1}
            scanProgress={0.62}
            distortion={hero.distortion}
            immediateProof
            showReference
            captureMode="rolling"
            width={720}
            height={590}
          />
        ) : (
          <>
            <CoverShape
              feature={feature}
              distorted={hero.distortion !== 0}
              accent={tokens.accent}
              warning={tokens.warning}
            />
            {Array.from({ length: 22 }, (_, index) => (
              <div
                key={index}
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  top: `${(index / 21) * 100}%`,
                  height: index === 11 ? 7 : 2,
                  background:
                    index === 11 ? tokens.warning : `${tokens.citation}38`,
                }}
              />
            ))}
          </>
        )}
      </div>
    );
  }
  return (
    <div
      style={{
        height: 700,
        width: "100%",
        position: "relative",
        borderRadius: kinetic ? 0 : tokens.radius,
        background: kinetic
          ? `radial-gradient(circle at center, ${tokens.accent}3d, transparent 63%)`
          : tokens.panel,
        border: kinetic ? "none" : `3px solid ${tokens.panelBorder}`,
      }}
    >
      <svg
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
        }}
        aria-hidden="true"
      >
        {hero.edges.map((edge, index) => {
          const source = hero.nodes.find((node) => node.id === edge.source);
          const target = hero.nodes.find((node) => node.id === edge.target);
          if (!source || !target) return null;
          return (
            <line
              key={`${edge.source}-${edge.target}-${index}`}
              x1={`${source.x * 84 + 8}%`}
              y1={`${source.y * 80 + 10}%`}
              x2={`${target.x * 84 + 8}%`}
              y2={`${target.y * 80 + 10}%`}
              stroke={tokens.warning}
              strokeWidth={9}
              strokeLinecap="round"
            />
          );
        })}
      </svg>
      {hero.nodes.map((node) => (
        <div
          key={node.id}
          style={{
            position: "absolute",
            left: `${node.x * 84 + 8}%`,
            top: `${node.y * 80 + 10}%`,
            transform: "translate(-50%,-50%)",
            padding: "24px 30px",
            borderRadius: kinetic ? 8 : 16,
            background:
              node.state === "active" ? tokens.accent : tokens.background,
            color: node.state === "active" ? tokens.background : tokens.text,
            border: `3px solid ${node.state === "active" ? tokens.accent : tokens.panelBorder}`,
            fontSize: 28,
            fontWeight: kinetic ? 850 : 700,
            boxShadow: kinetic
              ? `10px 12px 0 ${node.state === "active" ? tokens.warning : tokens.panel}`
              : undefined,
          }}
        >
          {node.label}
        </div>
      ))}
    </div>
  );
};

export const Cover: React.FC<ProjectData> = (data) => {
  const selected = data.cover?.candidates.find(
    (candidate) => candidate.candidate_id === data.cover?.selected_candidate_id,
  );
  if (!selected) {
    throw new Error(
      "TechShortCover requires a validated, explicitly selected cover candidate",
    );
  }
  const candidate = selected;
  const tokens = getTheme(candidate.palette);
  const kinetic = isKineticPopTheme(candidate.palette);
  const padding = coverPaddingFor(data, candidate.layout);
  return (
    <AbsoluteFill
      style={{
        background: tokens.backgroundCss,
        color: tokens.text,
        fontFamily: tokens.font,
        padding: `${padding.top}px ${padding.right}px ${padding.bottom}px ${padding.left}px`,
        display: "flex",
        flexDirection: "column",
        justifyContent: "flex-start",
        overflow: "hidden",
      }}
    >
      {kinetic ? (
        <KineticBackdrop
          chapter={KINETIC_COVER_CHAPTER}
          durationSeconds={5}
          motion="energetic"
          sceneOrder={0}
          tokens={tokens}
        />
      ) : (
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            width: 670,
            height: 670,
            right: -280,
            top: -240,
            borderRadius: "50%",
            border: `90px solid ${tokens.accent}18`,
          }}
        />
      )}
      <div style={{ position: "relative", zIndex: 1 }}>
        <div
          style={{
            color: kinetic ? tokens.background : tokens.accent,
            background: kinetic ? tokens.warning : undefined,
            display: kinetic ? "inline-flex" : undefined,
            clipPath: kinetic
              ? "polygon(0 0, calc(100% - 18px) 0, 100% 50%, calc(100% - 18px) 100%, 0 100%)"
              : undefined,
            padding: kinetic ? "12px 34px 12px 18px" : undefined,
            fontSize: kinetic ? 22 : 25,
            fontWeight: kinetic ? 850 : 700,
            letterSpacing: kinetic ? 3 : 4,
            textTransform: "uppercase",
            marginBottom: kinetic ? 28 : 24,
          }}
        >
          Technical explainer
        </div>
        <h1
          style={{
            fontFamily: tokens.headingFont,
            fontSize: kinetic
              ? candidate.layout === "editorial"
                ? 126
                : 116
              : candidate.layout === "editorial"
                ? 108
                : 92,
            lineHeight: kinetic ? 0.87 : 0.95,
            letterSpacing: kinetic ? -7 : -4,
            fontWeight: kinetic ? 900 : undefined,
            textWrap: "balance",
            margin: 0,
            maxWidth: kinetic ? 910 : 950,
            textShadow: kinetic
              ? `0 14px 50px ${tokens.background}b8`
              : undefined,
          }}
        >
          {candidate.headline}
        </h1>
        {candidate.subheadline ? (
          <p
            style={{
              fontSize: kinetic ? 33 : 36,
              lineHeight: kinetic ? 1.12 : 1.2,
              color: kinetic ? tokens.text : tokens.muted,
              maxWidth: kinetic ? 760 : 870,
              margin: kinetic ? "24px 0 0" : "30px 0 0",
              fontWeight: kinetic ? 650 : undefined,
            }}
          >
            {candidate.subheadline}
          </p>
        ) : null}
        {kinetic ? (
          <div
            aria-hidden="true"
            style={{
              width: 260,
              height: 12,
              marginTop: 24,
              borderRadius: 999,
              background: `linear-gradient(90deg, ${tokens.warning}, ${tokens.accent})`,
              boxShadow: `0 10px 34px ${tokens.accent}55`,
            }}
          />
        ) : null}
      </div>
      <div
        style={{
          position: "relative",
          zIndex: 1,
          marginTop: kinetic ? 18 : 86,
          marginLeft: kinetic ? -20 : undefined,
          marginRight: kinetic ? -12 : undefined,
        }}
      >
        <Hero candidate={candidate} />
      </div>
      <div
        style={{
          marginTop: "auto",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          color: tokens.muted,
          fontSize: 24,
          position: "relative",
          zIndex: 2,
        }}
      >
        <span>{data.title}</span>
        <span
          style={{
            border: `2px solid ${tokens.citation}`,
            borderRadius: 999,
            padding: "9px 16px",
            color: tokens.citation,
          }}
        >
          Evidence-linked
        </span>
      </div>
      {data.watermarked ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            zIndex: 5,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transform: "rotate(-24deg)",
            fontSize: 116,
            fontWeight: 700,
            letterSpacing: 8,
            color: `${tokens.text}24`,
            border: `14px solid ${tokens.text}18`,
            pointerEvents: "none",
          }}
        >
          UNREVIEWED
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
