import { describe, expect, it } from "vitest";
import { DEFAULT_SAFE_ZONE } from "../schemas/project";
import { kineticChapterFor } from "../scenes/shared";
import { KINETIC_COVER_CHAPTER, coverPaddingFor } from "./Cover";

describe("short-form cover layout", () => {
  it("keeps every cover footer and badge inside the shared platform safe zone", () => {
    const data = {
      width: 1080,
      height: 1920,
      safeZone: DEFAULT_SAFE_ZONE,
    };

    expect(coverPaddingFor(data, "editorial")).toEqual({
      top: 165,
      right: 152,
      bottom: 327,
      left: 73,
    });
    expect(coverPaddingFor(data, "split-hero")).toEqual({
      top: 125,
      right: 152,
      bottom: 327,
      left: 73,
    });
  });

  it("shares the first scene's semantic backdrop for visual continuity", () => {
    expect(KINETIC_COVER_CHAPTER).toEqual(
      kineticChapterFor({
        layout: "hero",
        order: 0,
        primitive: "KineticText",
      }),
    );
  });
});
