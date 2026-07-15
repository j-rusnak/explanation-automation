import { z } from "zod";

const node = z
  .object({
    id: z.string(),
    label: z.string(),
    x: z.number().min(0).max(1),
    y: z.number().min(0).max(1),
    state: z.enum(["normal", "active", "muted"]).default("normal"),
  })
  .strict();
const edge = z
  .object({
    source: z.string(),
    target: z.string(),
    label: z.string().nullable().optional(),
  })
  .strict();
const visual = z
  .object({
    title: z.string(),
    body: z.string().nullable().optional(),
    nodes: z.array(node).default([]),
    edges: z.array(edge).default([]),
    series: z.array(z.number()).max(30).default([]),
    labels: z.array(z.string()).max(30).default([]),
    parameter: z.number().min(0).max(1).nullable().optional(),
    left: z.string().nullable().optional(),
    right: z.string().nullable().optional(),
    citation: z.string().nullable().optional(),
  })
  .strict();
export const captionSchema = z
  .object({
    index: z.number().int().positive(),
    start: z.number().nonnegative(),
    end: z.number().positive(),
    text: z.string().min(1).max(42),
  })
  .strict()
  .refine((cue) => cue.end > cue.start, {
    message: "caption end must be after its start",
  });
export const sceneSchema = z
  .object({
    schema_version: z.literal("1.0.0"),
    scene_id: z.string(),
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
    script_segment_ids: z.array(z.string()).min(1),
    claim_ids: z.array(z.string()),
    on_screen_text: z.string(),
    visual,
    asset_ids: z.array(z.string()),
    accessibility_description: z.string(),
    evidence_label: z.string().nullable().optional(),
    theme_overrides: z.record(z.string(), z.string()),
    review_status: z.string(),
    dependency_hash: z.string(),
  })
  .strict();
export const segmentSchema = z
  .object({
    schema_version: z.literal("1.0.0"),
    segment_id: z.string(),
    text: z.string(),
    segment_type: z.enum([
      "factual",
      "hook",
      "transition",
      "analogy",
      "caveat",
      "limitation",
      "cta",
    ]),
    claim_ids: z.array(z.string()),
    approximate_duration: z.number().positive(),
    pronunciation_notes: z.string().nullable().optional(),
    review_status: z.string(),
    approval_hash: z.string().nullable().optional(),
  })
  .strict();
export const projectSchema = z
  .object({
    schemaVersion: z.literal("1.0.0"),
    title: z.string(),
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
