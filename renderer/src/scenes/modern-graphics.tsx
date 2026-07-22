import React from "react";
import type { ThemeTokens } from "../themes/tokens";

export const clampUnit = (value: number): number =>
  Math.max(0, Math.min(1, value));

export const stagedReveal = (
  progress: number,
  index: number,
  count: number,
): number => clampUnit(clampUnit(progress) * Math.max(1, count) - index + 0.3);

export const KineticTag: React.FC<{
  children: React.ReactNode;
  color: string;
  tokens: ThemeTokens;
}> = ({ children, color, tokens }) => (
  <div
    style={{
      display: "inline-flex",
      alignItems: "center",
      minHeight: 46,
      padding: "8px 16px",
      borderLeft: `7px solid ${color}`,
      background: `${tokens.background}e8`,
      color: tokens.text,
      fontSize: 25,
      fontWeight: 850,
      letterSpacing: 0.4,
      boxShadow: "0 12px 32px #0005",
    }}
  >
    {children}
  </div>
);

export const ProgressRail: React.FC<{
  progress: number;
  startLabel: string;
  endLabel: string;
  tokens: ThemeTokens;
  color?: string;
}> = ({ progress, startLabel, endLabel, tokens, color = tokens.warning }) => {
  const complete = clampUnit(progress);
  return (
    <div style={{ width: "100%", maxWidth: 300 }}>
      <div
        style={{
          position: "relative",
          height: 12,
          borderRadius: 999,
          background: tokens.panelBorder,
          boxShadow: `inset 0 0 0 2px ${tokens.background}77`,
        }}
      >
        <div
          style={{
            width: `${complete * 100}%`,
            height: "100%",
            borderRadius: 999,
            background: color,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: `${complete * 100}%`,
            top: "50%",
            width: 24,
            height: 24,
            borderRadius: "50%",
            background: tokens.text,
            border: `6px solid ${color}`,
            transform: "translate(-50%, -50%)",
            boxShadow: "0 6px 18px #0007",
          }}
        />
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 14,
          marginTop: 12,
          color: tokens.muted,
          fontSize: 22,
          fontWeight: 750,
        }}
      >
        <span>{startLabel}</span>
        <span style={{ textAlign: "right" }}>{endLabel}</span>
      </div>
    </div>
  );
};

export const SequenceRail: React.FC<{
  items: Array<{ id: string; label: string; active?: boolean }>;
  progress: number;
  tokens: ThemeTokens;
}> = ({ items, progress, tokens }) => (
  <div
    style={{
      position: "relative",
      display: "grid",
      gridTemplateColumns: `repeat(${Math.max(1, items.length)}, minmax(0, 1fr))`,
      width: "100%",
      minHeight: 92,
      gap: 10,
    }}
  >
    <div
      aria-hidden="true"
      style={{
        position: "absolute",
        top: 18,
        left: `${50 / Math.max(1, items.length)}%`,
        right: `${50 / Math.max(1, items.length)}%`,
        height: 5,
        background: tokens.panelBorder,
      }}
    >
      <div
        style={{
          width: `${clampUnit(progress) * 100}%`,
          height: "100%",
          background: tokens.warning,
        }}
      />
    </div>
    {items.map((item, index) => {
      const reveal = stagedReveal(progress, index, items.length);
      const active = item.active || reveal > 0.88;
      return (
        <div
          key={item.id}
          style={{
            position: "relative",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            textAlign: "center",
            color: active ? tokens.text : tokens.muted,
            opacity: 0.45 + reveal * 0.55,
          }}
        >
          <div
            style={{
              zIndex: 1,
              width: 41,
              height: 41,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: active ? tokens.warning : tokens.background,
              color: active ? tokens.background : tokens.text,
              border: `4px solid ${active ? tokens.warning : tokens.panelBorder}`,
              fontSize: 18,
              fontWeight: 900,
              boxShadow: "0 8px 22px #0007",
            }}
          >
            {index + 1}
          </div>
          <div
            style={{
              marginTop: 10,
              maxWidth: 220,
              fontSize: 24,
              lineHeight: 1.08,
              fontWeight: 800,
            }}
          >
            {item.label}
          </div>
        </div>
      );
    })}
  </div>
);
