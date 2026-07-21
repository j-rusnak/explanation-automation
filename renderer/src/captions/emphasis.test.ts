import { describe, expect, it } from "vitest";

import type { CaptionTokenData } from "../schemas/project";
import {
  MAX_EMPHASIS_CHANGES_PER_SECOND,
  MIN_EMPHASIS_HOLD_SECONDS,
  activeEmphasisTokenIndexes,
  captionTokenPresentation,
  emphasisPhrasesFor,
} from "./emphasis";

const tokens: CaptionTokenData[] = [
  { text: "Rows", start: 0, end: 0.18, group: 0 },
  { text: "expose", start: 0.18, end: 0.38, group: 0 },
  { text: "at", start: 0.38, end: 0.54, group: 1 },
  { text: "different", start: 0.54, end: 0.75, group: 2 },
  { text: "moments.", start: 0.75, end: 1.2, group: 2 },
];

describe("caption emphasis", () => {
  it("prefers declared phrase groups and merges changes that are too fast", () => {
    const phrases = emphasisPhrasesFor(tokens, 1.2);

    expect(phrases).toEqual([
      { start: 0, end: 0.54, tokenIndexes: [0, 1, 2] },
      { start: 0.54, end: 1.2, tokenIndexes: [3, 4] },
    ]);
    expect(1 / MIN_EMPHASIS_HOLD_SECONDS).toBe(MAX_EMPHASIS_CHANGES_PER_SECOND);
    expect(
      phrases.every(
        (phrase) =>
          phrase.end - phrase.start + Number.EPSILON >=
          MIN_EMPHASIS_HOLD_SECONDS,
      ),
    ).toBe(true);
  });

  it("selects one deterministic phrase at exact half-open boundaries", () => {
    expect(activeEmphasisTokenIndexes(tokens, 0, 1.2)).toEqual([0, 1, 2]);
    expect(activeEmphasisTokenIndexes(tokens, 0.539, 1.2)).toEqual([0, 1, 2]);
    expect(activeEmphasisTokenIndexes(tokens, 0.54, 1.2)).toEqual([3, 4]);
    expect(activeEmphasisTokenIndexes(tokens, 1.2, 1.2)).toEqual([]);
  });

  it("keeps active and inactive text equally visible without layout changes", () => {
    const inactive = captionTokenPresentation(false, "#5eead4");
    const active = captionTokenPresentation(true, "#5eead4");

    expect(active.color).toBe(inactive.color);
    expect(active.opacity).toBe(1);
    expect(inactive.opacity).toBe(1);
    expect(active.fontSize).toBeUndefined();
    expect(active.fontWeight).toBeUndefined();
    expect(active.transform).toBeUndefined();
    expect(active.textDecorationLine).toBe("underline");
    expect(inactive.textDecorationLine).toBe("none");
    expect(active.textDecorationColor).toBe("#5eead4");
  });

  it("falls back safely when no token timing is available", () => {
    expect(emphasisPhrasesFor([], 2)).toEqual([]);
    expect(activeEmphasisTokenIndexes([], 1, 2)).toEqual([]);
  });
});
