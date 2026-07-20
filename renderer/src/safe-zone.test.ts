import { describe, expect, it } from "vitest";
import { safeZonePixels } from "./safe-zone";
import { DEFAULT_SAFE_ZONE, safeZoneSchema } from "./schemas/project";

describe("universal short-form safe zone", () => {
  it("resolves conservative 1080 by 1920 insets", () => {
    expect(safeZonePixels(DEFAULT_SAFE_ZONE, 1080, 1920)).toEqual({
      top: 116,
      right: 152,
      bottom: 327,
      left: 73,
    });
  });

  it("accepts bounded custom insets and rejects content-crushing zones", () => {
    expect(
      safeZoneSchema.parse({
        top: 0.05,
        right: 0.12,
        bottom: 0.18,
        left: 0.06,
      }),
    ).toEqual({ top: 0.05, right: 0.12, bottom: 0.18, left: 0.06 });
    expect(() =>
      safeZoneSchema.parse({
        top: 0.2,
        right: 0.22,
        bottom: 0.22,
        left: 0.22,
      }),
    ).toThrow(/40%/);
  });
});
