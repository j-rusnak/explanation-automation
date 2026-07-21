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
  const retentionScene = { ...scene, duration: 75 };
  const retentionEvents = Array.from({ length: 15 }, (_, index) => ({
    eventId: `retention-event-${String(index + 1).padStart(2, "0")}`,
    scheduledAtSeconds: index === 14 ? 74.25 : 0.75 + index * 5,
    eventKind: "pattern-interrupt",
    device: "visual-mode-change",
  }));
  const retention = {
    schemaVersion: "1.0.0",
    planVersionId: "retention-aaaaaaaaaaaaaaaa",
    timingScale: 1,
    totalDurationSeconds: 75,
    events: retentionEvents,
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

  it("accepts allowlisted visual quality presets and typed raster scans", () => {
    const parsed = sceneSchema.parse({
      ...scene,
      primitive: "RasterScan",
      layout: "split",
      motion: "calm",
      citation_label: "Section 2",
      visual: {
        kind: "raster-scan",
        direction: "top-to-bottom",
        rows: 18,
        subject: "blade",
        distortion: 0.62,
        scan_label: "Rows expose in sequence",
        before_label: "Geometry",
        after_label: "Captured frame",
      },
    });
    expect(parsed.visual).toMatchObject({ kind: "raster-scan", rows: 18 });
    expect(parsed.layout).toBe("split");
  });

  it("defaults to brisk pacing and rejects unbounded pacing modes", () => {
    const parsed = projectSchema.parse({ ...base, scenes: [scene] });
    expect(parsed.pacing).toBe("brisk");
    expect(parsed.safeZone).toEqual({
      top: 0.06,
      right: 0.14,
      bottom: 0.17,
      left: 0.067,
    });
    expect(() =>
      projectSchema.parse({
        ...base,
        scenes: [scene],
        pacing: "viral-chaos",
      }),
    ).toThrow();
    expect(
      projectSchema.parse({ ...base, scenes: [scene], pacing: "measured" })
        .pacing,
    ).toBe("measured");
  });

  it("accepts an allowlisted frame-ready retention schedule", () => {
    const parsed = projectSchema.parse({
      ...base,
      scenes: [retentionScene],
      retention,
    });
    expect(parsed.retention?.events).toHaveLength(15);
    expect(parsed.retention?.events[14]?.scheduledAtSeconds).toBe(74.25);
    expect(parsed.retention?.events[0]?.device).toBe("visual-mode-change");
  });

  it("accepts the 45-second lower retention boundary", () => {
    const parsed = projectSchema.parse({
      ...base,
      scenes: [{ ...retentionScene, duration: 45 }],
      retention: {
        ...retention,
        timingScale: 0.6,
        totalDurationSeconds: 45,
        events: retention.events.map((item) => ({
          ...item,
          scheduledAtSeconds: item.scheduledAtSeconds * 0.6,
        })),
      },
    });
    expect(parsed.retention?.totalDurationSeconds).toBe(45);
  });

  it("rejects more than fifteen retention events", () =>
    expect(() =>
      projectSchema.parse({
        ...base,
        scenes: [retentionScene],
        retention: {
          ...retention,
          events: [
            ...retention.events,
            {
              ...retention.events[14],
              eventId: "retention-event-16",
              scheduledAtSeconds: 74.5,
            },
          ],
        },
      }),
    ).toThrow());

  it("rejects unknown, executable, and sound-rendering retention data", () => {
    const declaredEvent = retention.events[0]!;
    expect(() =>
      projectSchema.parse({
        ...base,
        scenes: [retentionScene],
        retention: {
          ...retention,
          events: retention.events.map((item, index) =>
            index === 0
              ? { ...declaredEvent, execute: "javascript:steal()" }
              : item,
          ),
        },
      }),
    ).toThrow();
    expect(() =>
      projectSchema.parse({
        ...base,
        scenes: [retentionScene],
        retention: {
          ...retention,
          events: retention.events.map((item, index) =>
            index === 0 ? { ...declaredEvent, soundPath: "secret.wav" } : item,
          ),
        },
      }),
    ).toThrow();
    expect(() =>
      projectSchema.parse({
        ...base,
        scenes: [retentionScene],
        retention: {
          ...retention,
          events: retention.events.map((item, index) =>
            index === 0 ? { ...declaredEvent, device: "eval(source)" } : item,
          ),
        },
      }),
    ).toThrow();
  });

  it("rejects a retention schedule that does not match rendered runtime", () =>
    expect(() =>
      projectSchema.parse({
        ...base,
        scenes: [retentionScene],
        retention: { ...retention, totalDurationSeconds: 74.5 },
      }),
    ).toThrow(/retention runtime/));

  it("rejects an event scheduled beyond the last renderable frame", () =>
    expect(() =>
      projectSchema.parse({
        ...base,
        scenes: [retentionScene],
        retention: {
          ...retention,
          events: retention.events.map((item, index) =>
            index === 14 ? { ...item, scheduledAtSeconds: 75 } : item,
          ),
        },
      }),
    ).toThrow(/final rendered frame/));

  it("rejects mismatched primitive and typed visual kinds", () =>
    expect(() =>
      sceneSchema.parse({
        ...scene,
        primitive: "Timeline",
        visual: {
          kind: "raster-scan",
          direction: "top-to-bottom",
          rows: 18,
          subject: "blade",
          distortion: 0.5,
          scan_label: "Readout",
          before_label: "Before",
          after_label: "After",
        },
      }),
    ).toThrow(/requires visual kind timeline/));

  it("rejects out-of-bounds evidence highlights", () =>
    expect(() =>
      sceneSchema.parse({
        ...scene,
        primitive: "EvidenceHighlight",
        visual: {
          kind: "evidence-highlight",
          source_title: "Original note",
          excerpt: "Rows expose at different times.",
          locator: "Mechanism section",
          evidence_id: "evidence-1",
          highlights: [{ start: 4, end: 100 }],
        },
      }),
    ).toThrow(/highlight range/));

  it("accepts a selected, evidence-linked cover candidate", () => {
    const parsed = projectSchema.parse({
      ...base,
      scenes: [scene],
      theme: "technical-editorial",
      cover: {
        schema_version: "1.0.0",
        selected_candidate_id: "cover-1",
        candidates: [
          {
            candidate_id: "cover-1",
            headline: "Why Straight Blades Look Bent",
            subheadline: "A sensor reads the frame one row at a time.",
            layout: "split-hero",
            palette: "signal-lab",
            hero: {
              kind: "comparison",
              feature: "straight-edge",
              before_label: "Object",
              after_label: "Image",
            },
            claim_ids: ["claim-1"],
            evidence_ids: ["evidence-1"],
            accessibility_description:
              "A straight blade beside a skewed blade.",
          },
        ],
      },
    });
    expect(parsed.cover?.selected_candidate_id).toBe("cover-1");
    expect(parsed.theme).toBe("technical-editorial");
  });

  it("accepts explicit comparison-side appearance semantics", () => {
    const comparison = {
      ...scene,
      primitive: "Comparison",
      visual: {
        kind: "comparison",
        feature: "straight-edge",
        left: {
          label: "Rolling",
          value: "successive row times",
          distorted: true,
        },
        right: {
          label: "Global",
          value: "shared exposure time",
          distorted: false,
        },
      },
    };

    const parsed = projectSchema.parse({ ...base, scenes: [comparison] });

    expect(parsed.scenes[0]!.visual).toMatchObject({
      left: { distorted: true },
      right: { distorted: false },
    });

    const invalid = structuredClone(comparison);
    invalid.visual.left.distorted = "yes" as never;
    expect(() => projectSchema.parse({ ...base, scenes: [invalid] })).toThrow();
  });

  it("rejects a cover selection that does not identify a candidate", () =>
    expect(() =>
      projectSchema.parse({
        ...base,
        scenes: [scene],
        cover: {
          schema_version: "1.0.0",
          selected_candidate_id: "cover-missing",
          candidates: [
            {
              candidate_id: "cover-1",
              headline: "A reviewed cover",
              layout: "editorial",
              palette: "blueprint",
              hero: { kind: "scanline", subject: "blade", distortion: 0.5 },
              claim_ids: ["claim-1"],
              evidence_ids: ["evidence-1"],
              accessibility_description: "A scanning line crosses a blade.",
            },
          ],
        },
      }),
    ).toThrow(/selected cover candidate/));

  it("rejects executable content nested in typed visuals", () =>
    expect(() =>
      sceneSchema.parse({
        ...scene,
        primitive: "Timeline",
        visual: {
          kind: "timeline",
          unit: "ms",
          events: [
            { time: 0, label: "First row" },
            { time: 2, label: "<svg onload=steal>" },
          ],
        },
      }),
    ).toThrow(/active content/));

  it("requires source-receipt highlights to be exact excerpt text", () =>
    expect(() =>
      sceneSchema.parse({
        ...scene,
        primitive: "SourceReceipt",
        visual: {
          kind: "source-receipt",
          source_title: "Original note",
          excerpt: "Rows expose at different moments.",
          locator: "Mechanism section",
          evidence_id: "evidence-1",
          highlight: "all at once",
        },
      }),
    ).toThrow(/highlight must occur/));

  it("requires time-based visual events to be strictly increasing", () => {
    expect(() =>
      sceneSchema.parse({
        ...scene,
        primitive: "Timeline",
        visual: {
          kind: "timeline",
          unit: "ms",
          events: [
            { time: 20, label: "Bottom row" },
            { time: 0, label: "Top row" },
          ],
        },
      }),
    ).toThrow(/strictly increasing/);
    expect(() =>
      sceneSchema.parse({
        ...scene,
        primitive: "TimeSlice",
        visual: {
          kind: "time-slice",
          unit: "ms",
          slices: [
            { time: 0, label: "First", offset: 0 },
            { time: 0, label: "Duplicate", offset: 0.2 },
          ],
        },
      }),
    ).toThrow(/strictly increasing/);
  });

  it("requires chart annotations to fall inside the plotted range", () =>
    expect(() =>
      sceneSchema.parse({
        ...scene,
        primitive: "AnnotatedChart",
        visual: {
          kind: "annotated-chart",
          chart_type: "line",
          x_axis: { label: "time", unit: "ms" },
          y_axis: { label: "offset", unit: "%" },
          series: [
            {
              label: "example",
              color: "accent",
              points: [
                { x: 0, y: 0 },
                { x: 20, y: 2 },
              ],
            },
          ],
          annotations: [{ x: 50, y: 2, label: "outside" }],
        },
      }),
    ).toThrow(/inside the data range/));
});
