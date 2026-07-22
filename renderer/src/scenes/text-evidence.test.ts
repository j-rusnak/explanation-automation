import { describe, expect, it } from "vitest";
import {
  kineticTextRevealFor,
  receiptPayoffFromText,
  receiptPayoffRevealFor,
} from "./text-evidence";

describe("kinetic text reveal", () => {
  it("uses a monotonic bounded reveal with no spring overshoot", () => {
    const samples = Array.from({ length: 16 }, (_, frame) =>
      kineticTextRevealFor(frame, 30),
    );
    expect(samples[0]).toBe(0);
    expect(samples.at(-1)).toBe(1);
    expect(samples.every((value) => value >= 0 && value <= 1)).toBe(true);
    expect(
      samples.every(
        (value, index) => index === 0 || value >= samples[index - 1]!,
      ),
    ).toBe(true);
  });
});

describe("receipt payoff transition", () => {
  it("uses one stable information-boundary reveal", () => {
    expect(receiptPayoffRevealFor(0.53)).toBe(0);
    expect(receiptPayoffRevealFor(0.6)).toBeGreaterThan(0);
    expect(receiptPayoffRevealFor(0.67)).toBe(1);
    expect(receiptPayoffRevealFor(2)).toBe(1);
  });
});

describe("source receipt payoff", () => {
  it("derives the approximate payoff from an explicit supplied relationship", () => {
    expect(receiptPayoffFromText("20 ms → about 2%", "")).toEqual({
      duration: "20 ms",
      offset: "~2%",
    });
  });

  it("preserves exact percentages without adding approximation", () => {
    expect(receiptPayoffFromText("20 milliseconds -> 2%", "")).toEqual({
      duration: "20 ms",
      offset: "2%",
    });
  });

  it("does not combine unrelated numbers into a claim", () => {
    expect(
      receiptPayoffFromText("20 ms readout", "A separate value is 2%."),
    ).toBeNull();
  });
});
