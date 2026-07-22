import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  buildRemotionArgs,
  type RenderMode,
} from "../scripts/render-command.mjs";

describe("render command", () => {
  it.each([
    ["preview", "render", "TechShort"],
    ["final", "render", "TechShort"],
    ["cover", "still", "TechShortCover"],
  ] satisfies ReadonlyArray<[RenderMode, string, string]>)(
    "uses renderer/public for %s output",
    (mode, command, composition) => {
      const args = buildRemotionArgs({
        mode,
        output: resolve("output.file"),
        props: resolve("renderer/public/project-data.json"),
        scale: 1,
      });

      expect(args[0]).toBe(command);
      expect(args[2]).toBe(composition);
      expect(args).toContain(`--public-dir=${resolve("renderer/public")}`);
    },
  );
});
