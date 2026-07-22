import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

import { buildRemotionArgs } from "./render-command.mjs";

const mode = process.argv[2];
const outputIndex = process.argv.indexOf("--output");
const propsIndex = process.argv.indexOf("--props");
const scaleIndex = process.argv.indexOf("--scale");
if (
  !new Set(["preview", "final", "cover"]).has(mode) ||
  outputIndex < 0 ||
  !process.argv[outputIndex + 1]
) {
  console.error("usage: render.mjs preview|final|cover --output <path>");
  process.exit(2);
}
const output = resolve(process.argv[outputIndex + 1]);
const props = resolve(
  propsIndex >= 0 && process.argv[propsIndex + 1]
    ? process.argv[propsIndex + 1]
    : "renderer/public/project-data.json",
);
const scale = Number(
  scaleIndex >= 0 && process.argv[scaleIndex + 1]
    ? process.argv[scaleIndex + 1]
    : mode === "preview"
      ? 1 / 3
      : 1,
);
if (!Number.isFinite(scale) || scale <= 0) {
  console.error("--scale must be a positive number");
  process.exit(2);
}
const remotion = resolve("node_modules/@remotion/cli/remotion-cli.js");
const args = buildRemotionArgs({ mode, output, props, scale });
const result = spawnSync(process.execPath, [remotion, ...args], {
  stdio: "inherit",
  shell: false,
  timeout: 900_000,
});
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
