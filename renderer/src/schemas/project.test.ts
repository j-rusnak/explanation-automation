import { describe, expect, it } from "vitest";
import { projectSchema, sceneSchema } from "./project";

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
  const scene = {
    schema_version: "1.0.0",
    scene_id: "scene-1",
    order: 0,
    start_time: 0,
    duration: 5,
    transition: "fade",
    primitive: "MechanismDiagram",
    script_segment_ids: ["segment-1"],
    claim_ids: ["claim-1"],
    on_screen_text: "Safe",
    visual: {
      title: "Safe diagram",
      nodes: [{ id: "a", label: "Sensor", x: 0.2, y: 0.5, state: "normal" }],
      edges: [],
      series: [],
      labels: [],
    },
    asset_ids: [],
    accessibility_description: "A safe diagram",
    evidence_label: "DOCUMENTED",
    theme_overrides: {},
    review_status: "pending",
    dependency_hash: "a".repeat(64),
  };
  it("rejects active content in scene text", () =>
    expect(() =>
      sceneSchema.parse({ ...scene, on_screen_text: "<svg onload=steal>" }),
    ).toThrow());
  it("rejects hostile or unknown theme overrides", () => {
    expect(() =>
      sceneSchema.parse({ ...scene, theme_overrides: { text: "#000000" } }),
    ).not.toThrow();
    expect(() =>
      sceneSchema.parse({ ...scene, theme_overrides: { font: "#000000" } }),
    ).toThrow();
    expect(() =>
      sceneSchema.parse({ ...scene, theme_overrides: { text: "url(evil)" } }),
    ).toThrow();
  });
  it("rejects edges that reference undeclared nodes", () =>
    expect(() =>
      sceneSchema.parse({
        ...scene,
        visual: {
          ...scene.visual,
          edges: [{ source: "a", target: "missing", label: "time" }],
        },
      }),
    ).toThrow());
});
