import { describe, expect, it } from "vitest";
import { projectSchema } from "./project";

const base = {
  schemaVersion: "1.0.0",
  title: "x",
  width: 360,
  height: 640,
  fps: 30,
  watermarked: true,
  segments: [],
  scenes: [],
  captions: [],
};
describe("renderer schema", () => {
  it("rejects empty scenes", () =>
    expect(() => projectSchema.parse(base)).toThrow());
  it("rejects executable primitive names", () =>
    expect(() =>
      projectSchema.parse({
        ...base,
        scenes: [{ primitive: "eval(alert(1))" }],
      }),
    ).toThrow());
  it("rejects unknown fields", () =>
    expect(() =>
      projectSchema.parse({ ...base, execute: "rm -rf" }),
    ).toThrow());
  it("rejects caption text longer than the sidecar limit", () =>
    expect(() =>
      projectSchema.parse({
        ...base,
        captions: [{ index: 1, start: 0, end: 1, text: "x".repeat(43) }],
      }),
    ).toThrow());
  it("rejects traversal in staged audio paths", () =>
    expect(() =>
      projectSchema.parse({ ...base, audioPath: "stage/../secret.wav" }),
    ).toThrow());
});
