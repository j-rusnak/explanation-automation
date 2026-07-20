import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { useSafeZone } from "../safe-zone";
import type { ProjectData, RetentionEventData } from "../schemas/project";
import { getTheme } from "../themes/tokens";

export const RETENTION_PULSE_SECONDS = 0.72;
export const RETENTION_RAMP_SECONDS = 0.3;

export const retentionEventStartFrame = (
  event: RetentionEventData,
  fps: number,
): number => Math.ceil(event.scheduledAtSeconds * fps);

export const activeRetentionEvent = (
  events: readonly RetentionEventData[],
  frame: number,
  fps: number,
): RetentionEventData | null => {
  const pulseFrames = Math.max(1, Math.ceil(RETENTION_PULSE_SECONDS * fps));
  // Walk backward so overlapping windows still produce exactly one overlay:
  // the most recently scheduled, explicitly declared event.
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]!;
    const start = retentionEventStartFrame(event, fps);
    if (frame >= start && frame < start + pulseFrames) return event;
  }
  return null;
};

const smoothstep = (value: number): number => {
  const bounded = Math.min(1, Math.max(0, value));
  return bounded * bounded * (3 - 2 * bounded);
};

export const retentionPulseProgress = (
  event: RetentionEventData,
  frame: number,
  fps: number,
): number => {
  const elapsed = (frame - retentionEventStartFrame(event, fps)) / fps;
  if (elapsed < 0 || elapsed >= RETENTION_PULSE_SECONDS) return 0;
  if (elapsed < RETENTION_RAMP_SECONDS) {
    return smoothstep(elapsed / RETENTION_RAMP_SECONDS);
  }
  const remaining = RETENTION_PULSE_SECONDS - elapsed;
  if (remaining < RETENTION_RAMP_SECONDS) {
    return smoothstep(remaining / RETENTION_RAMP_SECONDS);
  }
  return 1;
};

const DeviceGlyph: React.FC<{
  device: RetentionEventData["device"];
  color: string;
}> = ({ device, color }) => {
  const line = { background: color, borderRadius: 999 } as const;
  const outline = {
    border: `4px solid ${color}`,
    boxSizing: "border-box",
  } as const;
  switch (device) {
    case "question-pivot":
      return (
        <>
          <div
            style={{
              ...outline,
              position: "absolute",
              inset: 10,
              borderRadius: "50%",
            }}
          />
          <div
            style={{
              ...line,
              position: "absolute",
              width: 10,
              height: 10,
              left: 31,
              bottom: 8,
            }}
          />
        </>
      );
    case "visual-mode-change":
      return (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, 19px)",
            gap: 7,
          }}
        >
          {[0, 1, 2, 3].map((item) => (
            <div
              key={item}
              style={{ ...outline, width: 19, height: 19, borderRadius: 5 }}
            />
          ))}
        </div>
      );
    case "source-receipt":
      return (
        <div
          style={{
            ...outline,
            width: 48,
            height: 55,
            borderRadius: 6,
            padding: "11px 8px",
            display: "flex",
            flexDirection: "column",
            gap: 7,
          }}
        >
          {[1, 0.76, 0.9].map((width, index) => (
            <div
              key={index}
              style={{ ...line, height: 4, width: `${width * 100}%` }}
            />
          ))}
        </div>
      );
    case "parameter-change":
      return (
        <div style={{ position: "relative", width: 58, height: 34 }}>
          <div
            style={{
              ...line,
              position: "absolute",
              left: 0,
              right: 0,
              top: 15,
              height: 5,
            }}
          />
          <div
            style={{
              ...outline,
              position: "absolute",
              left: 31,
              top: 4,
              width: 24,
              height: 24,
              borderRadius: "50%",
              background: "transparent",
            }}
          />
        </div>
      );
    case "comparison-switch":
      return (
        <div style={{ display: "flex", gap: 7 }}>
          <div style={{ ...outline, width: 23, height: 47, borderRadius: 7 }} />
          <div
            style={{
              ...outline,
              width: 23,
              height: 47,
              borderRadius: 7,
              transform: "translateY(8px)",
            }}
          />
        </div>
      );
    case "misconception-correction":
      return (
        <div style={{ position: "relative", width: 58, height: 58 }}>
          <div
            style={{
              ...outline,
              position: "absolute",
              inset: 10,
              transform: "rotate(45deg)",
              borderRadius: 8,
            }}
          />
          <div
            style={{
              ...line,
              position: "absolute",
              width: 10,
              height: 10,
              left: 24,
              top: 24,
            }}
          />
        </div>
      );
    case "callback":
      return (
        <div style={{ position: "relative", width: 58, height: 58 }}>
          <div
            style={{
              ...outline,
              position: "absolute",
              inset: 4,
              borderRadius: "50%",
            }}
          />
          <div
            style={{
              ...outline,
              position: "absolute",
              inset: 18,
              borderRadius: "50%",
            }}
          />
        </div>
      );
  }
};

const eventColor = (
  event: RetentionEventData,
  tokens: ReturnType<typeof getTheme>,
): string => {
  switch (event.eventKind) {
    case "evidence-payoff":
      return tokens.citation;
    case "limitation-reframe":
      return tokens.warning;
    case "final-payoff":
      return tokens.accent;
    case "re-hook":
      return tokens.warning;
    case "pattern-interrupt":
      return tokens.accent;
  }
};

export const RetentionOverlay: React.FC<{
  retention: ProjectData["retention"];
  themeName: ProjectData["theme"];
}> = ({ retention, themeName }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const safeZone = useSafeZone();
  const event = retention
    ? activeRetentionEvent(retention.events, frame, fps)
    : null;
  if (!event) return null;

  const tokens = getTheme(themeName);
  const color = eventColor(event, tokens);
  const progress = retentionPulseProgress(event, frame, fps);
  return (
    <div
      aria-hidden="true"
      data-retention-device={event.device}
      data-retention-event-id={event.eventId}
      style={{
        position: "absolute",
        top: safeZone.top,
        right: safeZone.right,
        bottom: safeZone.bottom,
        left: safeZone.left,
        border: `3px solid ${color}`,
        borderRadius: 30,
        boxShadow: `inset 0 0 42px ${color}22, 0 0 28px ${color}18`,
        opacity: progress * 0.48,
        transform: `scale(${0.994 + progress * 0.006})`,
        transformOrigin: "center",
        pointerEvents: "none",
        zIndex: 18,
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 18,
          right: 18,
          width: 66,
          height: 66,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 18,
          background: `${tokens.background}d9`,
          boxShadow: `0 8px 24px ${tokens.background}99`,
        }}
      >
        <DeviceGlyph device={event.device} color={color} />
      </div>
    </div>
  );
};
