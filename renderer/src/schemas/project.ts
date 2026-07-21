import { z } from "zod";

const activeContent =
  /<\s*\/?\s*[a-z!][^>]*>|\b(?:java|vb)script\s*:|\bdata\s*:\s*(?:text\/html|image\/svg\+xml)|\bon[a-z]{3,}\s*=|\b(?:eval|exec|__import__)\s*\(|\bnew\s+function\s*\(/i;
export const inertText = z
  .string()
  .max(2_000)
  .refine((value) => !value.includes("\0") && !activeContent.test(value), {
    message: "active content is forbidden",
  });
const shortText = inertText.max(180);
const stableId = inertText.regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/);
const color = z.string().regex(/^#[0-9A-Fa-f]{6}$/);
const paletteRole = z.enum([
  "accent",
  "warning",
  "citation",
  "danger",
  "muted",
]);
export const themeNameSchema = z.enum([
  "blueprint",
  "signal-lab",
  "technical-editorial",
]);
export const layoutSchema = z.enum([
  "hero",
  "full-diagram",
  "split",
  "evidence",
  "numeric",
  "limitation",
]);
export const motionSchema = z.enum(["calm", "precise", "energetic"]);
export const pacingSchema = z.enum(["measured", "brisk", "high-retention"]);
export const DEFAULT_SAFE_ZONE = {
  top: 0.06,
  right: 0.14,
  bottom: 0.17,
  left: 0.067,
} as const;
export const safeZoneSchema = z
  .object({
    top: z.number().min(0).max(0.25).default(DEFAULT_SAFE_ZONE.top),
    right: z.number().min(0).max(0.25).default(DEFAULT_SAFE_ZONE.right),
    bottom: z.number().min(0).max(0.25).default(DEFAULT_SAFE_ZONE.bottom),
    left: z.number().min(0).max(0.25).default(DEFAULT_SAFE_ZONE.left),
  })
  .strict()
  .refine((zone) => zone.left + zone.right <= 0.4, {
    message:
      "horizontal safe-zone insets may not consume over 40% of the frame",
  })
  .refine((zone) => zone.top + zone.bottom <= 0.4, {
    message: "vertical safe-zone insets may not consume over 40% of the frame",
  });

const themeKeys = new Set([
  "background",
  "panel",
  "text",
  "muted",
  "accent",
  "warning",
  "danger",
  "citation",
]);

export const nodeSchema = z
  .object({
    id: stableId,
    label: shortText,
    x: z.number().min(0).max(1),
    y: z.number().min(0).max(1),
    state: z.enum(["normal", "active", "muted"]).default("normal"),
  })
  .strict();
export const edgeSchema = z
  .object({
    source: stableId,
    target: stableId,
    label: shortText.nullable().optional(),
  })
  .strict();
const graphShape = {
  nodes: z.array(nodeSchema).min(2).max(12),
  edges: z.array(edgeSchema).max(18),
};
type GraphValue = {
  nodes: Array<z.infer<typeof nodeSchema>>;
  edges: Array<z.infer<typeof edgeSchema>>;
};
const validateGraph = (value: GraphValue, context: z.RefinementCtx): void => {
  const ids = new Set(value.nodes.map((item) => item.id));
  if (ids.size !== value.nodes.length) {
    context.addIssue({
      code: "custom",
      message: "visual node IDs must be unique",
    });
  }
  for (const edge of value.edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) {
      context.addIssue({
        code: "custom",
        message: "visual edges must reference declared nodes",
      });
    }
  }
};

// Kept only so archived v1 storyboards remain renderable. New storyboards use a
// discriminated visual below and cannot smuggle fields from another primitive.
const legacyVisualSchema = z
  .object({
    title: shortText,
    body: inertText.nullable().optional(),
    nodes: z.array(nodeSchema).default([]),
    edges: z.array(edgeSchema).default([]),
    series: z.array(z.number().finite()).max(30).default([]),
    labels: z.array(shortText).max(30).default([]),
    parameter: z.number().min(0).max(1).nullable().optional(),
    left: shortText.nullable().optional(),
    right: shortText.nullable().optional(),
    citation: stableId.nullable().optional(),
    evidence_id: stableId.nullable().optional(),
    evidence_excerpt: inertText.nullable().optional(),
    source_locator: shortText.nullable().optional(),
  })
  .strict()
  .superRefine((value, context) => {
    const ids = new Set(value.nodes.map((item) => item.id));
    if (ids.size !== value.nodes.length) {
      context.addIssue({
        code: "custom",
        message: "visual node IDs must be unique",
      });
    }
    for (const edge of value.edges) {
      if (!ids.has(edge.source) || !ids.has(edge.target)) {
        context.addIssue({
          code: "custom",
          message: "visual edges must reference declared nodes",
        });
      }
    }
  });

const kineticVisual = z
  .object({
    kind: z.literal("kinetic-text"),
    emphasis: z.array(shortText).max(4).default([]),
    supporting_text: shortText.nullable().optional(),
  })
  .strict();
const sourceReceiptVisual = z
  .object({
    kind: z.literal("source-receipt"),
    source_title: shortText,
    excerpt: inertText.min(1).max(500),
    locator: shortText,
    evidence_id: stableId,
    highlight: shortText.nullable().optional(),
  })
  .strict()
  .refine(
    (receipt) =>
      receipt.highlight == null || receipt.excerpt.includes(receipt.highlight),
    "source receipt highlight must occur in its excerpt",
  );
const mechanismVisual = z
  .object({
    ...graphShape,
    kind: z.literal("mechanism-diagram"),
    active_step_id: stableId.nullable().optional(),
  })
  .strict()
  .superRefine((value, context) => {
    validateGraph(value, context);
    if (
      value.active_step_id != null &&
      !value.nodes.some((node) => node.id === value.active_step_id)
    ) {
      context.addIssue({
        code: "custom",
        message: "active mechanism step must reference a declared node",
      });
    }
  });
const chartPoint = z
  .object({ x: z.number().finite(), y: z.number().finite() })
  .strict();
const chartSeries = z
  .object({
    label: shortText,
    color: paletteRole.default("accent"),
    points: z.array(chartPoint).min(1).max(30),
  })
  .strict();
const chartAnnotation = z
  .object({
    x: z.number().finite(),
    y: z.number().finite(),
    label: shortText,
  })
  .strict();
const annotatedChartVisual = z
  .object({
    kind: z.literal("annotated-chart"),
    chart_type: z.enum(["bar", "line", "dot"]),
    x_axis: z
      .object({ label: shortText, unit: shortText.nullable().optional() })
      .strict(),
    y_axis: z
      .object({ label: shortText, unit: shortText.nullable().optional() })
      .strict(),
    series: z.array(chartSeries).min(1).max(4),
    annotations: z.array(chartAnnotation).max(6).default([]),
  })
  .strict()
  .superRefine((chart, context) => {
    const points = chart.series.flatMap((series) => series.points);
    const minX = Math.min(...points.map((point) => point.x));
    const maxX = Math.max(...points.map((point) => point.x));
    const minY = Math.min(...points.map((point) => point.y));
    const maxY = Math.max(...points.map((point) => point.y));
    for (const annotation of chart.annotations) {
      if (
        annotation.x < minX ||
        annotation.x > maxX ||
        annotation.y < minY ||
        annotation.y > maxY
      ) {
        context.addIssue({
          code: "custom",
          message:
            "chart annotations must identify a point inside the data range",
        });
      }
    }
  });
const parameterVisual = z
  .object({
    kind: z.literal("parameter-simulation"),
    parameter_label: shortText,
    unit: shortText.nullable().optional(),
    minimum: z.number().finite(),
    maximum: z.number().finite(),
    value: z.number().finite(),
    left_label: shortText,
    right_label: shortText,
  })
  .strict()
  .refine(
    (value) => value.maximum > value.minimum,
    "maximum must exceed minimum",
  )
  .refine(
    (value) => value.value >= value.minimum && value.value <= value.maximum,
    "value must fall inside the parameter bounds",
  );
const comparisonSide = z
  .object({
    label: shortText,
    value: shortText,
    detail: shortText.nullable().optional(),
    distorted: z.boolean().nullable().optional(),
  })
  .strict();
const comparisonVisual = z
  .object({
    kind: z.literal("comparison"),
    feature: z.enum(["straight-edge", "grid", "rotor", "signal", "generic"]),
    left: comparisonSide,
    right: comparisonSide,
  })
  .strict();
const limitationVisual = z
  .object({
    kind: z.literal("limitation"),
    limitation: inertText.min(1).max(360),
    applies_when: shortText.nullable().optional(),
  })
  .strict();
const rasterScanVisual = z
  .object({
    kind: z.literal("raster-scan"),
    direction: z.enum(["top-to-bottom", "bottom-to-top", "left-to-right"]),
    rows: z.number().int().min(6).max(32),
    subject: z.enum(["blade", "pole", "grid", "rotor"]),
    distortion: z.number().min(-1).max(1),
    scan_label: shortText,
    before_label: shortText,
    after_label: shortText,
  })
  .strict();
const timeSlice = z
  .object({
    time: z.number().nonnegative(),
    label: shortText,
    offset: z.number().min(-1).max(1),
  })
  .strict();
const timeSliceVisual = z
  .object({
    kind: z.literal("time-slice"),
    unit: shortText,
    slices: z.array(timeSlice).min(2).max(12),
  })
  .strict()
  .refine(
    (visual) =>
      visual.slices.every(
        (slice, index) =>
          index === 0 || slice.time > visual.slices[index - 1]!.time,
      ),
    "time slices must be strictly increasing",
  );
const gridWarpVisual = z
  .object({
    kind: z.literal("grid-warp"),
    rows: z.number().int().min(3).max(20),
    columns: z.number().int().min(3).max(20),
    skew: z.number().min(-1).max(1),
    curvature: z.number().min(-1).max(1),
    before_label: shortText,
    after_label: shortText,
  })
  .strict();
const beforeAfterVisual = z
  .object({
    kind: z.literal("before-after-overlay"),
    feature: z.enum(["straight-edge", "grid", "rotor", "signal"]),
    before_label: shortText,
    after_label: shortText,
    divider: z.number().min(0.2).max(0.8).default(0.5),
  })
  .strict();
const evidenceHighlightVisual = z
  .object({
    kind: z.literal("evidence-highlight"),
    source_title: shortText,
    excerpt: inertText.min(1).max(500),
    locator: shortText,
    evidence_id: stableId,
    highlights: z
      .array(
        z
          .object({
            start: z.number().int().nonnegative(),
            end: z.number().int().positive(),
          })
          .strict(),
      )
      .min(1)
      .max(6),
  })
  .strict()
  .superRefine((value, context) => {
    const sorted = [...value.highlights].sort(
      (left, right) => left.start - right.start,
    );
    for (const [index, range] of sorted.entries()) {
      if (range.end <= range.start || range.end > value.excerpt.length) {
        context.addIssue({
          code: "custom",
          message: "highlight range must be inside excerpt",
        });
      }
      if (index > 0 && range.start < sorted[index - 1]!.end) {
        context.addIssue({
          code: "custom",
          message: "highlight ranges cannot overlap",
        });
      }
    }
  });
const processFlowVisual = z
  .object({
    ...graphShape,
    kind: z.literal("process-flow"),
    active_step_id: stableId.nullable().optional(),
  })
  .strict()
  .superRefine((value, context) => {
    validateGraph(value, context);
    if (
      value.active_step_id != null &&
      !value.nodes.some((node) => node.id === value.active_step_id)
    ) {
      context.addIssue({
        code: "custom",
        message: "active process step must reference a declared node",
      });
    }
  });
const timelineEvent = z
  .object({
    time: z.number().finite(),
    label: shortText,
    detail: shortText.nullable().optional(),
  })
  .strict();
const timelineVisual = z
  .object({
    kind: z.literal("timeline"),
    unit: shortText,
    events: z.array(timelineEvent).min(2).max(10),
  })
  .strict()
  .refine(
    (visual) =>
      visual.events.every(
        (event, index) =>
          index === 0 || event.time > visual.events[index - 1]!.time,
      ),
    "timeline events must be strictly increasing",
  );

export const typedVisualSchema = z.discriminatedUnion("kind", [
  kineticVisual,
  sourceReceiptVisual,
  mechanismVisual,
  annotatedChartVisual,
  parameterVisual,
  comparisonVisual,
  limitationVisual,
  rasterScanVisual,
  timeSliceVisual,
  gridWarpVisual,
  beforeAfterVisual,
  evidenceHighlightVisual,
  processFlowVisual,
  timelineVisual,
]);
export const visualSchema = z.union([legacyVisualSchema, typedVisualSchema]);

export const captionSchema = z
  .object({
    index: z.number().int().positive(),
    start: z.number().nonnegative(),
    end: z.number().positive(),
    text: inertText.min(1).max(42),
  })
  .strict()
  .refine((cue) => cue.end > cue.start, {
    message: "caption end must be after its start",
  });

export const retentionEventKindSchema = z.enum([
  "re-hook",
  "pattern-interrupt",
  "evidence-payoff",
  "limitation-reframe",
  "final-payoff",
]);
export const engagementDeviceSchema = z.enum([
  "question-pivot",
  "visual-mode-change",
  "source-receipt",
  "parameter-change",
  "comparison-switch",
  "misconception-correction",
  "callback",
]);
export const retentionEventSchema = z
  .object({
    eventId: stableId,
    scheduledAtSeconds: z.number().nonnegative().max(75),
    eventKind: retentionEventKindSchema,
    device: engagementDeviceSchema,
  })
  .strict();
export const retentionSchema = z
  .object({
    schemaVersion: z.literal("1.0.0"),
    planVersionId: z.string().regex(/^retention-[0-9a-f]{16}$/),
    timingScale: z.number().min(0.5).max(2),
    totalDurationSeconds: z.number().min(45).max(75),
    events: z.array(retentionEventSchema).min(5).max(15),
  })
  .strict()
  .superRefine((retention, context) => {
    const ids = retention.events.map((event) => event.eventId);
    if (new Set(ids).size !== ids.length) {
      context.addIssue({
        code: "custom",
        message: "retention event IDs must be unique",
      });
    }
    for (const [index, event] of retention.events.entries()) {
      if (event.scheduledAtSeconds > retention.totalDurationSeconds) {
        context.addIssue({
          code: "custom",
          path: ["events", index, "scheduledAtSeconds"],
          message: "retention events must fit inside the rendered runtime",
        });
      }
      if (
        index > 0 &&
        event.scheduledAtSeconds <
          retention.events[index - 1]!.scheduledAtSeconds
      ) {
        context.addIssue({
          code: "custom",
          path: ["events", index, "scheduledAtSeconds"],
          message: "retention events must be ordered",
        });
      }
    }
  });

const primitiveSchema = z.enum([
  "KineticText",
  "SourceReceipt",
  "MechanismDiagram",
  "ChartReveal",
  "ParameterSimulation",
  "Comparison",
  "LimitationCard",
  "RasterScan",
  "TimeSlice",
  "GridWarp",
  "BeforeAfterOverlay",
  "AnnotatedChart",
  "EvidenceHighlight",
  "ProcessFlow",
  "Timeline",
]);
const expectedKind: Partial<
  Record<
    z.infer<typeof primitiveSchema>,
    z.infer<typeof typedVisualSchema>["kind"]
  >
> = {
  KineticText: "kinetic-text",
  SourceReceipt: "source-receipt",
  MechanismDiagram: "mechanism-diagram",
  ChartReveal: "annotated-chart",
  ParameterSimulation: "parameter-simulation",
  Comparison: "comparison",
  LimitationCard: "limitation",
  RasterScan: "raster-scan",
  TimeSlice: "time-slice",
  GridWarp: "grid-warp",
  BeforeAfterOverlay: "before-after-overlay",
  AnnotatedChart: "annotated-chart",
  EvidenceHighlight: "evidence-highlight",
  ProcessFlow: "process-flow",
  Timeline: "timeline",
};

export const sceneSchema = z
  .object({
    schema_version: z.literal("1.0.0"),
    scene_id: stableId,
    order: z.number().int().nonnegative(),
    start_time: z.number().nonnegative(),
    duration: z.number().positive(),
    transition: z.enum(["cut", "fade", "slide"]),
    primitive: primitiveSchema,
    layout: layoutSchema.default("hero"),
    motion: motionSchema.default("precise"),
    script_segment_ids: z.array(stableId).min(1),
    claim_ids: z.array(stableId).min(1),
    on_screen_text: shortText.min(1),
    visual: visualSchema,
    asset_ids: z.array(stableId),
    accessibility_description: inertText,
    evidence_label: z
      .enum(["DOCUMENTED", "MEASURED", "SIMULATED", "INFERRED"])
      .nullable()
      .optional(),
    citation_label: shortText.nullable().optional(),
    theme_overrides: z
      .record(z.string(), color)
      .refine(
        (value) => Object.keys(value).every((key) => themeKeys.has(key)),
        {
          message: "theme override key is not allowlisted",
        },
      ),
    review_status: z.enum(["pending", "approved", "rejected", "stale"]),
    dependency_hash: z.string().regex(/^[0-9a-f]{64}$/),
  })
  .strict()
  .superRefine((scene, context) => {
    if (!("kind" in scene.visual)) return;
    const expected = expectedKind[scene.primitive];
    if (expected && scene.visual.kind !== expected) {
      context.addIssue({
        code: "custom",
        path: ["visual", "kind"],
        message: `${scene.primitive} requires visual kind ${expected}`,
      });
    }
  });

export const segmentSchema = z
  .object({
    schema_version: z.literal("1.0.0"),
    segment_id: stableId,
    text: inertText,
    segment_type: z.enum([
      "factual",
      "hook",
      "transition",
      "analogy",
      "caveat",
      "limitation",
      "cta",
    ]),
    claim_ids: z.array(stableId).min(1),
    approximate_duration: z.number().positive(),
    pronunciation_notes: inertText.nullable().optional(),
    review_status: z.enum(["pending", "approved", "rejected", "stale"]),
    approval_hash: z.string().nullable().optional(),
  })
  .strict();

const comparisonHero = z
  .object({
    kind: z.literal("comparison"),
    feature: z.enum(["straight-edge", "grid", "rotor", "signal"]),
    before_label: shortText,
    after_label: shortText,
  })
  .strict();
const scanlineHero = z
  .object({
    kind: z.literal("scanline"),
    subject: z.enum(["blade", "pole", "grid", "rotor"]),
    distortion: z.number().min(-1).max(1),
  })
  .strict();
const diagramHero = z
  .object({ ...graphShape, kind: z.literal("diagram") })
  .strict()
  .superRefine(validateGraph);
export const coverHeroSchema = z.discriminatedUnion("kind", [
  comparisonHero,
  scanlineHero,
  diagramHero,
]);
export const coverCandidateSchema = z
  .object({
    candidate_id: stableId,
    headline: inertText.min(1).max(72),
    subheadline: inertText.max(110).nullable().optional(),
    layout: z.enum(["split-hero", "diagram-hero", "editorial"]),
    palette: themeNameSchema,
    hero: coverHeroSchema,
    claim_ids: z.array(stableId).min(1).max(6),
    evidence_ids: z.array(stableId).min(1).max(6),
    accessibility_description: inertText.min(1).max(500),
  })
  .strict();
export const coverSpecSchema = z
  .object({
    schema_version: z.literal("1.0.0"),
    selected_candidate_id: stableId,
    candidates: z.array(coverCandidateSchema).min(1).max(3),
  })
  .strict()
  .superRefine((cover, context) => {
    const ids = cover.candidates.map((candidate) => candidate.candidate_id);
    if (new Set(ids).size !== ids.length) {
      context.addIssue({
        code: "custom",
        message: "cover candidate IDs must be unique",
      });
    }
    if (!ids.includes(cover.selected_candidate_id)) {
      context.addIssue({
        code: "custom",
        message: "selected cover candidate must exist",
      });
    }
  });

export const projectSchema = z
  .object({
    schemaVersion: z.literal("1.0.0"),
    title: inertText,
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    fps: z.number().int().positive(),
    watermarked: z.boolean(),
    theme: themeNameSchema.default("blueprint"),
    pacing: pacingSchema.default("brisk"),
    safeZone: safeZoneSchema.default(DEFAULT_SAFE_ZONE),
    segments: z.array(segmentSchema),
    scenes: z.array(sceneSchema).min(1),
    captions: z.array(captionSchema),
    retention: retentionSchema.optional(),
    cover: coverSpecSchema.optional(),
    audioPath: z
      .string()
      .regex(/^[A-Za-z0-9][A-Za-z0-9._/-]*$/)
      .refine((value) => !value.split("/").includes(".."), {
        message: "audio path must be public-relative and traversal-free",
      })
      .optional(),
  })
  .strict()
  .superRefine((project, context) => {
    if (!project.retention) return;
    const runtime = project.scenes.reduce(
      (maximum, scene) => Math.max(maximum, scene.start_time + scene.duration),
      0,
    );
    if (Math.abs(project.retention.totalDurationSeconds - runtime) > 0.000001) {
      context.addIssue({
        code: "custom",
        path: ["retention", "totalDurationSeconds"],
        message: "retention runtime must match the rendered scene runtime",
      });
    }
    const renderedFrames = Math.ceil(runtime * project.fps);
    for (const [index, event] of project.retention.events.entries()) {
      if (Math.ceil(event.scheduledAtSeconds * project.fps) >= renderedFrames) {
        context.addIssue({
          code: "custom",
          path: ["retention", "events", index, "scheduledAtSeconds"],
          message:
            "retention events must activate before the final rendered frame",
        });
      }
    }
  });

export type ProjectData = z.infer<typeof projectSchema>;
export type SceneData = z.infer<typeof sceneSchema>;
export type TypedVisual = z.infer<typeof typedVisualSchema>;
export type CoverCandidate = z.infer<typeof coverCandidateSchema>;
export type PacingPreset = z.infer<typeof pacingSchema>;
export type SafeZoneInsets = z.infer<typeof safeZoneSchema>;
export type RetentionEventData = z.infer<typeof retentionEventSchema>;
