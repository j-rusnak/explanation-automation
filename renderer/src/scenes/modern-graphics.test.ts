import { describe, expect, it } from "vitest";
import { clampUnit, stagedReveal } from "./modern-graphics";

describe("modern graphic timing helpers", () => {
  it("clamps progress to a stable unit interval", () => {
    expect(clampUnit(-1)).toBe(0);
    expect(clampUnit(0.45)).toBe(0.45);
    expect(clampUnit(3)).toBe(1);
  });

  it("reveals ordered mechanism labels without oscillation", () => {
    const firstEarly = stagedReveal(0.2, 0, 3);
    const secondEarly = stagedReveal(0.2, 1, 3);
    const firstLate = stagedReveal(0.8, 0, 3);
    expect(firstEarly).toBeGreaterThan(secondEarly);
    expect(firstLate).toBeGreaterThanOrEqual(firstEarly);
  });
});
