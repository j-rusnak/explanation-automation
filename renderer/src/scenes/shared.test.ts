import { describe, expect, it } from "vitest";

import type { SceneData } from "../schemas/project";
import { isKineticPopTheme, kineticChapterFor } from "./shared";

const chapterInput = (
  order: number,
  layout: SceneData["layout"],
  primitive: SceneData["primitive"],
) => ({ order, layout, primitive });

describe("Kinetic Pop composition grammar", () => {
  it("assigns semantic color chapters rather than arbitrary scene colors", () => {
    expect(kineticChapterFor(chapterInput(0, "hero", "KineticText"))).toEqual({
      primary: "warning",
      secondary: "accent",
      anchor: "right",
    });
    expect(
      kineticChapterFor(chapterInput(3, "evidence", "SourceReceipt")),
    ).toEqual({
      primary: "citation",
      secondary: "warning",
      anchor: "right",
    });
    expect(
      kineticChapterFor(chapterInput(6, "limitation", "LimitationCard")),
    ).toEqual({
      primary: "danger",
      secondary: "warning",
      anchor: "left",
    });
  });

  it("keeps the new grammar strictly theme-gated", () => {
    expect(isKineticPopTheme("blueprint")).toBe(false);
    expect(isKineticPopTheme("signal-lab")).toBe(false);
    expect(isKineticPopTheme("technical-editorial")).toBe(false);
    expect(isKineticPopTheme("kinetic-pop")).toBe(true);
  });
});
