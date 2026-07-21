import { describe, expect, it } from "vitest";

import {
  KOKORO_MODEL_REVISION,
  KOKORO_VOICES,
  segmentFileName,
  validateSynthesisInput,
} from "../scripts/kokoro-runtime.mjs";

const validInput = () => ({
  schemaVersion: "1.0.0",
  voice: "af_heart",
  speed: 1,
  segments: [
    { segmentId: "segment-01", text: "A camera reads one row at a time." },
  ],
});

describe("Kokoro local runtime contract", () => {
  it("pins a full model revision and exposes a bounded English voice allowlist", () => {
    expect(KOKORO_MODEL_REVISION).toMatch(/^[0-9a-f]{40}$/);
    expect(Object.keys(KOKORO_VOICES).length).toBeGreaterThanOrEqual(10);
    expect(KOKORO_VOICES.af_heart).toEqual({
      name: "Heart",
      culture: "en-US",
      gender: "Female",
    });
  });

  it("validates inert ordered segments and deterministic filenames", () => {
    expect(validateSynthesisInput(validInput())).toEqual(validInput());
    expect(segmentFileName(0)).toBe("segment-001.wav");
    expect(segmentFileName(99)).toBe("segment-100.wav");
  });

  it.each([
    [{ ...validInput(), voice: "../../voice" }, /voice/],
    [{ ...validInput(), speed: Number.NaN }, /speed/],
    [{ ...validInput(), speed: 2 }, /speed/],
    [{ ...validInput(), extra: "field" }, /unsupported fields/],
    [
      {
        ...validInput(),
        segments: [
          { segmentId: "segment-01", text: "First." },
          { segmentId: "segment-01", text: "Second." },
        ],
      },
      /unique/,
    ],
    [
      {
        ...validInput(),
        segments: [{ segmentId: "../../escape", text: "No." }],
      },
      /invalid ID/,
    ],
    [
      {
        ...validInput(),
        segments: [{ segmentId: "segment-01", text: "line one\nline two" }],
      },
      /invalid narration text/,
    ],
  ])("rejects unsafe or unbounded input %#", (input, message) => {
    expect(() => validateSynthesisInput(input)).toThrow(message);
  });
});
