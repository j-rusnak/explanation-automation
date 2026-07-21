import { describe, expect, it } from "vitest";
import { receiptPayoffFromText } from "./text-evidence";

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
