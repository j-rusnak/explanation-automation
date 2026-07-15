# Architecture decision record

## ADR-001: local manifests and deterministic rendering

techshort is a local compiler with a trust boundary between untrusted source/provider text and allowlisted application behavior. Python owns strict Pydantic schemas, extraction, evidence verification, append-only review state, invalidation, captions, QA, and export. The renderer consumes only validated structured scene data and never evaluates project-supplied code. Projects are versioned JSON manifests with atomic replacement after validation.

The dependency graph is source → evidence → claims → script → storyboard/assets/audio → render → QA → final approval → export. Changes mark all downstream gates stale. Exact excerpts are re-resolved by character offsets before claim approval and QA. Human approval hashes bind the reviewed object to its evidence/dependency state.

The renderer accepts seven primitives: KineticText, SourceReceipt, MechanismDiagram, ChartReveal, ParameterSimulation, Comparison, and LimitationCard. Visual values are bounded schemas, not HTML or scripts. Preview is low resolution and visibly watermarked. Final is 1080×1920 at 30 fps and requires all gates.

Persistence is deliberately filesystem-only. There is no server, database, authentication, cloud service, analytics, publishing, or arbitrary custom-scene runtime.

## Dependency decisions

- pypdf: BSD-3-Clause, selected instead of copyleft/commercial PDF alternatives. V1 supports text extraction, not OCR.
- Pydantic: MIT; strict schema validation and JSON Schema generation.
- Typer: MIT; discoverable local CLI.
- Streamlit: Apache-2.0; minimal restart-safe local reviewer.
- Remotion: primary renderer only if the operator qualifies under or obtains its commercial terms. A license decision is recorded before installation.

