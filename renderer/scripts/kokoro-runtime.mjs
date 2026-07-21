import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import { relative, resolve, sep } from "node:path";

import { env as transformersEnv } from "@huggingface/transformers";
import { KokoroTTS } from "kokoro-js";

export const KOKORO_MODEL_ID = "onnx-community/Kokoro-82M-v1.0-ONNX";
export const KOKORO_MODEL_REVISION = "1939ad2a8e416c0acfeecc08a694d14ef25f2231";
export const KOKORO_DTYPE = "q8";
export const KOKORO_DEVICE = "cpu";
export const KOKORO_RUNTIME_VERSION = "techshort-kokoro-v1";

const stableId = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const manifestName = "techshort-kokoro-manifest.json";
const maxInputBytes = 128 * 1024;

export const KOKORO_VOICES = Object.freeze({
  af_heart: { name: "Heart", culture: "en-US", gender: "Female" },
  af_bella: { name: "Bella", culture: "en-US", gender: "Female" },
  af_nicole: { name: "Nicole", culture: "en-US", gender: "Female" },
  af_aoede: { name: "Aoede", culture: "en-US", gender: "Female" },
  af_kore: { name: "Kore", culture: "en-US", gender: "Female" },
  af_nova: { name: "Nova", culture: "en-US", gender: "Female" },
  af_sarah: { name: "Sarah", culture: "en-US", gender: "Female" },
  am_fenrir: { name: "Fenrir", culture: "en-US", gender: "Male" },
  am_michael: { name: "Michael", culture: "en-US", gender: "Male" },
  am_puck: { name: "Puck", culture: "en-US", gender: "Male" },
  bf_emma: { name: "Emma", culture: "en-GB", gender: "Female" },
  bf_isabella: { name: "Isabella", culture: "en-GB", gender: "Female" },
  bm_fable: { name: "Fable", culture: "en-GB", gender: "Male" },
  bm_george: { name: "George", culture: "en-GB", gender: "Male" },
});

const exactKeys = (value, expected, label) => {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (
    actual.length !== wanted.length ||
    actual.some((key, i) => key !== wanted[i])
  ) {
    throw new Error(`${label} contains unsupported fields`);
  }
};

export const validateSynthesisInput = (value) => {
  exactKeys(value, ["schemaVersion", "voice", "speed", "segments"], "input");
  if (value.schemaVersion !== "1.0.0") {
    throw new Error("unsupported Kokoro input schema version");
  }
  if (!Object.hasOwn(KOKORO_VOICES, value.voice)) {
    throw new Error("voice is not in the reviewed English Kokoro allowlist");
  }
  if (
    typeof value.speed !== "number" ||
    !Number.isFinite(value.speed) ||
    value.speed < 0.75 ||
    value.speed > 1.5
  ) {
    throw new Error("Kokoro speed must be a finite number from 0.75 to 1.5");
  }
  if (
    !Array.isArray(value.segments) ||
    value.segments.length < 1 ||
    value.segments.length > 100
  ) {
    throw new Error("Kokoro input requires between 1 and 100 segments");
  }
  const seen = new Set();
  let totalBytes = 0;
  const segments = value.segments.map((segment, index) => {
    exactKeys(segment, ["segmentId", "text"], `segment ${index + 1}`);
    if (
      typeof segment.segmentId !== "string" ||
      !stableId.test(segment.segmentId)
    ) {
      throw new Error(`segment ${index + 1} has an invalid ID`);
    }
    if (seen.has(segment.segmentId)) {
      throw new Error("Kokoro segment IDs must be unique");
    }
    seen.add(segment.segmentId);
    if (
      typeof segment.text !== "string" ||
      !segment.text.trim() ||
      segment.text.includes("\0") ||
      segment.text.includes("\r") ||
      segment.text.includes("\n") ||
      segment.text.length > 4000
    ) {
      throw new Error(`segment ${index + 1} has invalid narration text`);
    }
    totalBytes += Buffer.byteLength(segment.text, "utf8");
    return { segmentId: segment.segmentId, text: segment.text };
  });
  if (totalBytes > maxInputBytes) {
    throw new Error("Kokoro narration exceeds the 128 KiB safety limit");
  }
  return {
    schemaVersion: "1.0.0",
    voice: value.voice,
    speed: value.speed,
    segments,
  };
};

export const segmentFileName = (index) => {
  if (!Number.isSafeInteger(index) || index < 0 || index >= 100) {
    throw new Error("segment index is outside the supported range");
  }
  return `segment-${String(index + 1).padStart(3, "0")}.wav`;
};

export const configureKokoroEnvironment = (
  cacheDirectory,
  allowRemoteModels,
) => {
  const cache = resolve(cacheDirectory);
  transformersEnv.cacheDir = cache;
  transformersEnv.allowLocalModels = true;
  transformersEnv.allowRemoteModels = Boolean(allowRemoteModels);
  transformersEnv.remotePathTemplate = `{model}/resolve/${KOKORO_MODEL_REVISION}/`;
  return cache;
};

export const loadKokoro = async ({ cacheDirectory, allowRemoteModels }) => {
  configureKokoroEnvironment(cacheDirectory, allowRemoteModels);
  return KokoroTTS.from_pretrained(KOKORO_MODEL_ID, {
    dtype: KOKORO_DTYPE,
    device: KOKORO_DEVICE,
  });
};

const walkFiles = async (directory, root, output) => {
  const entries = await readdir(directory, { withFileTypes: true });
  entries.sort((left, right) => left.name.localeCompare(right.name));
  for (const entry of entries) {
    const absolute = resolve(directory, entry.name);
    if (entry.isSymbolicLink()) {
      throw new Error("Kokoro cache may not contain symbolic links");
    }
    if (entry.isDirectory()) {
      await walkFiles(absolute, root, output);
      continue;
    }
    if (!entry.isFile() || entry.name === manifestName) continue;
    const relativePath = relative(root, absolute).split(sep).join("/");
    const metadata = await stat(absolute);
    const digest = createHash("sha256")
      .update(await readFile(absolute))
      .digest("hex");
    output.push({ path: relativePath, size: metadata.size, sha256: digest });
  }
};

export const inspectModelCache = async (cacheDirectory) => {
  const root = resolve(cacheDirectory);
  const files = [];
  await walkFiles(root, root, files);
  if (!files.some((item) => item.path.endsWith(".onnx"))) {
    throw new Error("Kokoro cache does not contain the pinned ONNX model");
  }
  const identity = createHash("sha256");
  let totalBytes = 0;
  for (const file of files) {
    identity.update(file.path);
    identity.update("\0");
    identity.update(String(file.size));
    identity.update("\0");
    identity.update(file.sha256);
    identity.update("\n");
    totalBytes += file.size;
  }
  return {
    modelId: KOKORO_MODEL_ID,
    revision: KOKORO_MODEL_REVISION,
    dtype: KOKORO_DTYPE,
    device: KOKORO_DEVICE,
    runtimeVersion: KOKORO_RUNTIME_VERSION,
    aggregateSha256: identity.digest("hex"),
    fileCount: files.length,
    totalBytes,
    files,
  };
};

export const synthesizeSegments = async (tts, input, outputDirectory) => {
  const validated = validateSynthesisInput(input);
  const destination = resolve(outputDirectory);
  const outputs = [];
  for (const [index, segment] of validated.segments.entries()) {
    const fileName = segmentFileName(index);
    const outputPath = resolve(destination, fileName);
    const audio = await tts.generate(segment.text, {
      voice: validated.voice,
      speed: validated.speed,
    });
    if (audio.sampling_rate !== 24000 || audio.audio.length < 1) {
      throw new Error("Kokoro returned invalid 24 kHz audio");
    }
    await audio.save(outputPath);
    outputs.push({
      segmentId: segment.segmentId,
      fileName,
      sampleRate: audio.sampling_rate,
      sampleCount: audio.audio.length,
      durationSeconds: audio.audio.length / audio.sampling_rate,
    });
  }
  return {
    schemaVersion: "1.0.0",
    provider: "kokoro-local",
    modelId: KOKORO_MODEL_ID,
    revision: KOKORO_MODEL_REVISION,
    dtype: KOKORO_DTYPE,
    device: KOKORO_DEVICE,
    runtimeVersion: KOKORO_RUNTIME_VERSION,
    voice: validated.voice,
    speed: validated.speed,
    segments: outputs,
  };
};
