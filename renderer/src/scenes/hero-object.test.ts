import { describe, expect, it } from "vitest";
import {
  rollingShutterProofProgress,
  rollingShutterRowOffset,
} from "./hero-object";

describe("rolling-shutter hero geometry", () => {
  it("shows distortion immediately when the opening proof requests it", () => {
    expect(rollingShutterProofProgress(0, true)).toBe(0.72);
    expect(rollingShutterProofProgress(0.2, false)).toBe(0.2);
  });

  it("clamps progress and keeps the first row anchored", () => {
    expect(rollingShutterProofProgress(2, false)).toBe(1);
    expect(rollingShutterProofProgress(-1, false)).toBe(0);
    expect(rollingShutterRowOffset(0, 0.8, 1, 600)).toBeCloseTo(0);
  });

  it("increases the deterministic offset down the sensor", () => {
    const upper = rollingShutterRowOffset(0.25, 0.8, 1, 600);
    const lower = rollingShutterRowOffset(0.9, 0.8, 1, 600);
    expect(lower).toBeGreaterThan(upper);
  });
});
