# Architecture decision record

## ADR-001: local manifests and deterministic rendering

techshort is a local compiler with a hard trust boundary between untrusted source/provider text and allowlisted application behavior. Python owns strict Pydantic schemas, extraction, exact evidence resolution, append-only review state, invalidation, captions, QA, and export. Remotion consumes only validated scene data; no project value is evaluated as code.

The dependency graph is:

`source → evidence → claims + independent critique → candidate angles + selection → script → storyboard + assets + narration → preview → QA → final approval → final render → export`

Every content edit receives a content-derived manifest version, archives the previous valid manifest, and invalidates dependent approvals. Angle generation always yields the three typed candidates, and script generation requires a separate hash-bound human selection whose central claims must appear in the script. Render bundles are also immutable by render ID. Approval hashes bind the exact reviewed object to its evidence; final approval additionally binds project configuration, captions, narration and any transcript, provenance receipts, the preview render manifest, QA report, and preview bytes.

The renderer accepts seven primitives: `KineticText`, `SourceReceipt`, `MechanismDiagram`, `ChartReveal`, `ParameterSimulation`, `Comparison`, and `LimitationCard`. `SourceReceipt` content is injected from a resolvable `EvidenceSpan`, not arbitrary scene prose. Preview is 360×640 with an `UNREVIEWED` watermark. Final output is 1080×1920 at 30 fps; the renderer itself refuses an unwatermarked render unless every current gate and final-review hash passes.

Persistence is deliberately filesystem-only. There is no database, authentication, cloud service, queue, analytics, social publishing, or custom-scene-code runtime.

## ADR-002: provider output is drafting data, never proof

Fixture generation is deterministic and offline. Manual generation exports a versioned prompt packet and imports strict JSON. Codex CLI generation is explicitly opt-in, uses the installed login, an excerpt-only temporary directory, read-only/ephemeral execution, sanitized environment variables, strict output schemas, timeouts, and one bounded schema-repair retry. Claims receive a distinct critique pass, but neither generation nor critique grants approval.

## Dependency decisions

- pypdf (BSD-3-Clause): text-PDF extraction and page labels; OCR remains out of scope.
- Pydantic and Typer (MIT): strict schemas and the local CLI.
- Streamlit (Apache-2.0): restart-safe local review surface.
- Remotion: the requested renderer, under its own commercial-use terms. Operators must confirm that their team/use qualifies or obtain the appropriate license.
- Atkinson Hyperlegible: bundled renderer font under the SIL Open Font License 1.1.
