import { z } from "zod";

const activeContent =
  /<\s*\/?\s*[a-z!][^>]*>|\b(?:java|vb)script\s*:|\bdata\s*:\s*(?:text\/html|image\/svg\+xml)|\bon[a-z]{3,}\s*=|\b(?:eval|exec|__import__)\s*\(|\bnew\s+function\s*\(/i;
const inertText = z
  .string()
  .refine((value) => !value.includes("\0") && !activeContent.test(value), {
    message: "active content is forbidden",
  });
const stableId = inertText.regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/);
const color = z.string().regex(/^#[0-9A-Fa-f]{6}$/);
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
const node = z
  .object({
    id: stableId,
    label: inertText,
    x: z.number().min(0).max(1),
    y: z.number().min(0).max(1),
    state: z.enum(["normal", "active", "muted"]).default("normal"),
  })
  .strict();
const edge = z
  .object({
    source: stableId,
    target: stableId,
    label: inertText.nullable().optional(),
  })
  .strict();
const visual = z
  .object({
    title: inertText,
    body: inertText.nullable().optional(),
    nodes: z.array(node).default([]),
    edges: z.array(edge).default([]),
    series: z.array(z.number()).max(30).default([]),
    labels: z.array(inertText).max(30).default([]),
    parameter: z.number().min(0).max(1).nullable().optional(),
    left: inertText.nullable().optional(),
    right: inertText.nullable().optional(),
    citation: stableId.nullable().optional(),
    evidence_id: stableId.nullable().optional(),
    evidence_excerpt: inertText.nullable().optional(),
    source_locator: inertText.nullable().optional(),
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
    for (const item of value.edges) {
      if (!ids.has(item.source) || !ids.has(item.target)) {
        context.addIssue({
          code: "custom",
          message: "visual edges must reference declared nodes",
        });
      }
    }
  });
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
export const sceneSchema = z
  .object({
    schema_version: z.literal("1.0.0"),
    scene_id: stableId,
    order: z.number().int().nonnegative(),
    start_time: z.number().nonnegative(),
    duration: z.number().positive(),
    transition: z.enum(["cut", "fade", "slide"]),
    primitive: z.enum([
      "KineticText",
      "SourceReceipt",
      "MechanismDiagram",
      "ChartReveal",
      "ParameterSimulation",
      "Comparison",
      "LimitationCard",
    ]),
    script_segment_ids: z.array(stableId).min(1),
    claim_ids: z.array(stableId).min(1),
    on_screen_text: inertText,
    visual,
    asset_ids: z.array(stableId),
    accessibility_description: inertText,
    evidence_label: z
      .enum(["DOCUMENTED", "MEASURED", "SIMULATED", "INFERRED"])
      .nullable()
      .optional(),
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
  .strict();
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
export const projectSchema = z
  .object({
    schemaVersion: z.literal("1.0.0"),
    title: inertText,
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    fps: z.number().int().positive(),
    watermarked: z.boolean(),
    segments: z.array(segmentSchema),
    scenes: z.array(sceneSchema).min(1),
    captions: z.array(captionSchema),
    audioPath: z
      .string()
      .regex(/^[A-Za-z0-9][A-Za-z0-9._/-]*$/)
      .refine((value) => !value.split("/").includes(".."), {
        message: "audio path must be public-relative and traversal-free",
      })
      .optional(),
  })
  .strict();
export type ProjectData = z.infer<typeof projectSchema>;
export type SceneData = z.infer<typeof sceneSchema>;
