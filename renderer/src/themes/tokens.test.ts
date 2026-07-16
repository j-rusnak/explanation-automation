import { describe, expect, it } from "vitest";
import { getTheme, themes } from "./tokens";

describe("renderer themes", () => {
  it("provides three materially distinct deterministic identities", () => {
    expect(Object.keys(themes)).toEqual([
      "blueprint",
      "signal-lab",
      "technical-editorial",
    ]);
    expect(
      new Set(Object.values(themes).map((theme) => theme.background)).size,
    ).toBe(3);
    expect(
      new Set(Object.values(themes).map((theme) => theme.motif)).size,
    ).toBe(3);
  });

  it("uses an editorial heading face only for the editorial identity", () => {
    expect(getTheme("technical-editorial").headingFont).toContain("Georgia");
    expect(getTheme("blueprint").headingFont).toContain("Atkinson");
  });
});
