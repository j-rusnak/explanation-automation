export type KokoroVoice = {
  name: string;
  culture: string;
  gender: "Female" | "Male";
};

export type KokoroSynthesisInput = {
  schemaVersion: "1.0.0";
  voice: string;
  speed: number;
  segments: Array<{ segmentId: string; text: string }>;
};

export const KOKORO_MODEL_ID: string;
export const KOKORO_MODEL_REVISION: string;
export const KOKORO_DTYPE: "q8";
export const KOKORO_DEVICE: "cpu";
export const KOKORO_RUNTIME_VERSION: string;
export const KOKORO_VOICES: Readonly<Record<string, KokoroVoice>>;
export const validateSynthesisInput: (value: unknown) => KokoroSynthesisInput;
export const segmentFileName: (index: number) => string;
export const configureKokoroEnvironment: (
  cacheDirectory: string,
  allowRemoteModels: boolean,
) => string;
export const loadKokoro: (options: {
  cacheDirectory: string;
  allowRemoteModels: boolean;
}) => Promise<unknown>;
export const inspectModelCache: (cacheDirectory: string) => Promise<{
  modelId: string;
  revision: string;
  dtype: string;
  device: string;
  runtimeVersion: string;
  aggregateSha256: string;
  fileCount: number;
  totalBytes: number;
  files: Array<{ path: string; size: number; sha256: string }>;
}>;
export const synthesizeSegments: (
  tts: unknown,
  input: unknown,
  outputDirectory: string,
) => Promise<unknown>;
