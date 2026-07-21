import { describe, expect, it } from "vitest";
import { getTheme, themes } from "./tokens";

describe("renderer themes", () => {
  it("provides four materially distinct deterministic identities", () => {
    expect(Object.keys(themes)).toEqual([
      "kinetic-pop",
      "blueprint",
      "signal-lab",
      "technical-editorial",
    ]);
    expect(
      new Set(Object.values(themes).map((theme) => theme.background)).size,
    ).toBe(4);
    expect(
      new Set(Object.values(themes).map((theme) => theme.motif)).size,
    ).toBe(4);
  });

  it("uses the accessible kinetic-pop palette", () => {
    expect(getTheme("kinetic-pop")).toMatchObject({
      background: "#0B0D17",
      text: "#FFF8E7",
      accent: "#24E5FF",
      warning: "#FFD84A",
      danger: "#FF4F6D",
      panelBorder: "#7657FF",
    });
  });

  it("uses an editorial heading face only for the editorial identity", () => {
    expect(getTheme("technical-editorial").headingFont).toContain("Georgia");
    expect(getTheme("blueprint").headingFont).toContain("Atkinson");
  });
});
