import { describe, expect, it } from "vitest";

import { kineticEntrancePresentationFor } from "../pacing/rhythm";
import type { CaptionTokenData } from "../schemas/project";
import {
  activeKeywordTokenIndexFor,
  kineticSceneBoundaryStyleFor,
} from "./Explainer";

const tokens: CaptionTokenData[] = [
  { text: "Rows", start: 0, end: 0.2, group: 0 },
  { text: "capture", start: 0.2, end: 0.5, group: 0 },
  { text: "different", start: 0.5, end: 0.8, group: 0 },
  { text: "moments.", start: 0.8, end: 1.1, group: 0 },
];

describe("Kinetic Pop captions", () => {
  it("accents exactly one deterministic keyword in the active phrase", () => {
    expect(activeKeywordTokenIndexFor(tokens, [0, 1, 2, 3])).toBe(2);
    expect(activeKeywordTokenIndexFor(tokens, [3, 1])).toBe(3);
    expect(activeKeywordTokenIndexFor(tokens, [])).toBeNull();
  });

  it("ignores invalid token indexes rather than reading arbitrary data", () => {
    expect(activeKeywordTokenIndexFor(tokens, [-1, 99, 1])).toBe(1);
  });
});

describe("Kinetic Pop scene composition", () => {
  it("has no continuous camera scale, vertical drift, or bounce", () => {
    const styles = [6, 30, 90, 180].map((frame) =>
      kineticSceneBoundaryStyleFor(
        kineticEntrancePresentationFor(frame, 6, 1, "fade"),
      ),
    );
    expect(new Set(styles.map((style) => style.transform))).toEqual(
      new Set(["translate3d(0px, 0, 0)"]),
    );
    expect(new Set(styles.map((style) => style.clipPath))).toEqual(
      new Set(["inset(0 0% 0 0%)"]),
    );
    for (const style of styles) {
      expect(style.transform).not.toContain("scale");
    }
  });

  it("maps a bounded slide and mask to stable CSS without opacity flashes", () => {
    const slide = kineticSceneBoundaryStyleFor(
      kineticEntrancePresentationFor(0, 6, 1, "slide"),
    );
    expect(slide).toEqual({
      transform: "translate3d(-28px, 0, 0)",
      clipPath: "inset(0 0% 0 0%)",
    });

    const reveal = kineticSceneBoundaryStyleFor(
      kineticEntrancePresentationFor(0, 6, 0, "fade"),
    );
    expect(reveal).toEqual({
      transform: "translate3d(0px, 0, 0)",
      clipPath: "inset(0 100% 0 0%)",
    });
  });
});
