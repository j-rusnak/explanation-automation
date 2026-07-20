import { describe, expect, it } from "vitest";
import type { RetentionEventData } from "../schemas/project";
import {
  RETENTION_PULSE_SECONDS,
  RETENTION_RAMP_SECONDS,
  activeRetentionEvent,
  retentionEventStartFrame,
  retentionPulseProgress,
} from "./RetentionOverlay";

const event = (
  eventId: string,
  scheduledAtSeconds: number,
): RetentionEventData => ({
  eventId,
  scheduledAtSeconds,
  eventKind: "pattern-interrupt",
  device: "visual-mode-change",
});

describe("declared retention events", () => {
  it("activates on the first frame at or after the exact scheduled time", () => {
    const scheduled = event("retention-event-01", 2.25);
    const start = retentionEventStartFrame(scheduled, 30);

    expect(start).toBe(68);
    expect(activeRetentionEvent([scheduled], start - 1, 30)).toBeNull();
    expect(activeRetentionEvent([scheduled], start, 30)).toBe(scheduled);
  });

  it("does not invent events at scene positions or pacing microbeats", () => {
    expect(activeRetentionEvent([], 0, 30)).toBeNull();
    expect(activeRetentionEvent([], 90, 30)).toBeNull();
    expect(activeRetentionEvent([], 450, 30)).toBeNull();

    const onlyDeclared = event("retention-event-01", 8);
    expect(activeRetentionEvent([onlyDeclared], 6 * 30, 30)).toBeNull();
  });

  it("selects only the newest declared event when pulse windows overlap", () => {
    const first = event("retention-event-01", 2);
    const second = event("retention-event-02", 2.2);

    expect(activeRetentionEvent([first, second], 66, 30)).toBe(second);
  });

  it("uses one gradual non-strobing pulse with a 300 ms ramp", () => {
    const scheduled = event("retention-event-01", 1);
    const start = retentionEventStartFrame(scheduled, 30);

    expect(RETENTION_PULSE_SECONDS).toBeGreaterThanOrEqual(0.25);
    expect(RETENTION_RAMP_SECONDS).toBeGreaterThanOrEqual(0.25);
    expect(retentionPulseProgress(scheduled, start, 30)).toBe(0);
    expect(retentionPulseProgress(scheduled, start + 4, 30)).toBeGreaterThan(0);
    expect(retentionPulseProgress(scheduled, start + 9, 30)).toBe(1);
    expect(retentionPulseProgress(scheduled, start + 20, 30)).toBeLessThan(1);
    expect(retentionPulseProgress(scheduled, start + 22, 30)).toBe(0);
  });
});
