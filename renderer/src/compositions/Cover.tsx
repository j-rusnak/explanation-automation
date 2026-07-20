import React from "react";
import { AbsoluteFill } from "remotion";
import type { CoverCandidate, ProjectData } from "../schemas/project";
import { getTheme } from "../themes/tokens";

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
              border: `3px solid ${item.distorted ? tokens.warning : tokens.accent}`,
              borderRadius: tokens.radius,
              background: `${tokens.panel}ed`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              position: "relative",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: 25,
                left: 28,
                color: item.distorted ? tokens.warning : tokens.accent,
                fontSize: 27,
                fontWeight: 700,
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
    return (
      <div
        style={{
          height: 720,
          width: "100%",
          borderRadius: tokens.radius,
          border: `3px solid ${tokens.panelBorder}`,
          background: tokens.panel,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          overflow: "hidden",
        }}
      >
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
      </div>
    );
  }
  return (
    <div
      style={{
        height: 700,
        width: "100%",
        position: "relative",
        borderRadius: tokens.radius,
        background: tokens.panel,
        border: `3px solid ${tokens.panelBorder}`,
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
            borderRadius: 16,
            background:
              node.state === "active" ? tokens.accent : tokens.background,
            color: node.state === "active" ? tokens.background : tokens.text,
            border: `3px solid ${node.state === "active" ? tokens.accent : tokens.panelBorder}`,
            fontSize: 28,
            fontWeight: 700,
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
  return (
    <AbsoluteFill
      style={{
        background: tokens.backgroundCss,
        color: tokens.text,
        fontFamily: tokens.font,
        padding:
          candidate.layout === "editorial"
            ? "165px 72px 135px"
            : "125px 64px 120px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "flex-start",
        overflow: "hidden",
      }}
    >
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
      <div style={{ position: "relative", zIndex: 1 }}>
        <div
          style={{
            color: tokens.accent,
            fontSize: 25,
            fontWeight: 700,
            letterSpacing: 4,
            textTransform: "uppercase",
            marginBottom: 24,
          }}
        >
          Technical explainer
        </div>
        <h1
          style={{
            fontFamily: tokens.headingFont,
            fontSize: candidate.layout === "editorial" ? 108 : 92,
            lineHeight: 0.95,
            letterSpacing: -4,
            textWrap: "balance",
            margin: 0,
            maxWidth: 950,
          }}
        >
          {candidate.headline}
        </h1>
        {candidate.subheadline ? (
          <p
            style={{
              fontSize: 36,
              lineHeight: 1.2,
              color: tokens.muted,
              maxWidth: 870,
              margin: "30px 0 0",
            }}
          >
            {candidate.subheadline}
          </p>
        ) : null}
      </div>
      <div style={{ position: "relative", zIndex: 1, marginTop: 86 }}>
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
