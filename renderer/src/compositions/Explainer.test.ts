import { describe, expect, it } from "vitest";

import type { CaptionTokenData } from "../schemas/project";
import { activeKeywordTokenIndexFor } from "./Explainer";

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
