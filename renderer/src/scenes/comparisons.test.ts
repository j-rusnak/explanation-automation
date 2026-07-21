import { describe, expect, it } from "vitest";
import { comparisonSideIsDistorted } from "./comparisons";

describe("comparison side appearance", () => {
  it("honors explicit visual semantics on either side", () => {
    expect(comparisonSideIsDistorted(true, 0)).toBe(true);
    expect(comparisonSideIsDistorted(false, 1)).toBe(false);
  });

  it("keeps the legacy left-reference/right-distorted default", () => {
    expect(comparisonSideIsDistorted(undefined, 0)).toBe(false);
    expect(comparisonSideIsDistorted(null, 1)).toBe(true);
  });
});
