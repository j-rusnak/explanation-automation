import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

import {
  KOKORO_VOICES,
  inspectModelCache,
  loadKokoro,
  synthesizeSegments,
  validateSynthesisInput,
} from "./kokoro-runtime.mjs";

const action = process.argv[2];
const valueAfter = (flag) => {
  const index = process.argv.indexOf(flag);
  return index >= 0 ? process.argv[index + 1] : undefined;
};
const fail = (message) => {
  process.stderr.write(`${message}\n`);
  process.exit(1);
};

try {
  if (action === "voices") {
    process.stdout.write(`${JSON.stringify(KOKORO_VOICES)}\n`);
    process.exit(0);
  }

  const cacheArgument = valueAfter("--cache-dir");
  if (!cacheArgument) fail("--cache-dir is required");
  const cacheDirectory = resolve(cacheArgument);

  if (action === "setup") {
    await mkdir(cacheDirectory, { recursive: true });
    await loadKokoro({ cacheDirectory, allowRemoteModels: true });
    const inspection = await inspectModelCache(cacheDirectory);
    process.stdout.write(`${JSON.stringify(inspection)}\n`);
    process.exit(0);
  }

  if (action !== "synthesize") {
    fail("usage: kokoro-local.mjs voices|setup|synthesize");
  }
  const inputArgument = valueAfter("--input");
  const outputArgument = valueAfter("--output-dir");
  if (!inputArgument || !outputArgument) {
    fail("synthesize requires --input and --output-dir");
  }
  const inputPath = resolve(inputArgument);
  const outputDirectory = resolve(outputArgument);
  const source = await readFile(inputPath);
  if (source.length > 128 * 1024) fail("Kokoro input exceeds 128 KiB");
  const input = validateSynthesisInput(JSON.parse(source.toString("utf8")));
  const inspection = await inspectModelCache(cacheDirectory);
  const tts = await loadKokoro({ cacheDirectory, allowRemoteModels: false });
  const result = await synthesizeSegments(tts, input, outputDirectory);
  process.stdout.write(
    `${JSON.stringify({ ...result, modelCacheSha256: inspection.aggregateSha256 })}\n`,
  );
} catch (error) {
  fail(error instanceof Error ? error.message : "Kokoro narration failed");
}
