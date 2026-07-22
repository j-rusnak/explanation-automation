import { resolve } from "node:path";

const publicDirectory = resolve("renderer/public");

/**
 * Build the Remotion CLI arguments used by the renderer entrypoint.
 *
 * The public directory is explicit because render payload assets are staged under
 * renderer/public, while Remotion otherwise resolves public/ from the repository
 * root.
 *
 * @param {{
 *   mode: "preview" | "final" | "cover";
 *   output: string;
 *   props: string;
 *   scale: number;
 * }} options
 * @returns {string[]}
 */
export const buildRemotionArgs = ({ mode, output, props, scale }) => {
  const shared = [
    `--props=${props}`,
    `--scale=${scale}`,
    `--public-dir=${publicDirectory}`,
  ];

  if (mode === "cover") {
    return [
      "still",
      "renderer/src/index.ts",
      "TechShortCover",
      output,
      ...shared,
      "--image-format=png",
    ];
  }

  return [
    "render",
    "renderer/src/index.ts",
    "TechShort",
    output,
    ...shared,
    "--codec=h264",
    "--pixel-format=yuv420p",
    mode === "preview" ? "--crf=28" : "--crf=18",
  ];
};
