# Architecture decision record

## ADR-001: local manifests and deterministic rendering

techshort is a local compiler with a hard trust boundary between untrusted source/provider text
and allowlisted application behavior. Python owns strict Pydantic schemas, extraction, exact
evidence resolution, append-only review state, invalidation, captions, QA, and export. Remotion
consumes only validated scene and retention data; no project value is evaluated as code.

The dependency graph is:

`source -> evidence -> claims + independent critique -> candidate angles + selection -> narrative brief + factual locks + beat plan -> script + editorial critique + retention plan + retention critique -> storyboard guidance + typed storyboard + visual critique -> cover candidates + selection + assets + narration mode -> preview + contact sheet + scene stills -> technical and creative QA -> final approval -> final render -> export`

Every content edit receives a content-derived manifest version, archives the previous valid
manifest, and invalidates dependent approvals. Angle generation always yields the three typed
candidates, and script generation requires a separate hash-bound human selection whose central
claims must appear in the script. Render bundles are also immutable by render ID. Approval hashes
bind the exact reviewed object to its evidence; final approval additionally binds project
configuration, captions, narration and any transcript, provenance receipts, the preview render
manifest, QA report, and preview bytes.

The renderer accepts fifteen allowlisted primitives: `KineticText`, `SourceReceipt`,
`MechanismDiagram`, `ChartReveal`, `ParameterSimulation`, `Comparison`, `LimitationCard`,
`RasterScan`, `TimeSlice`, `GridWarp`, `BeforeAfterOverlay`, `AnnotatedChart`,
`EvidenceHighlight`, `ProcessFlow`, and `Timeline`. Each primitive has a strict typed visual
contract; project data cannot carry executable markup or code. Evidence visuals are checked
against resolvable `EvidenceSpan` bytes rather than trusted as scene prose.

Three centralized themes, six layout presets, three motion presets, and three pacing profiles
parameterize those primitives without generating runtime code. Project configuration also carries
one bounded, resolution-independent safe zone shared by captions, scene content, covers, and
retention overlays. The selected evidence-linked cover is rendered by its own composition.
Preview video and cover are 360x640 with an `UNREVIEWED` watermark. Each render also produces a
contact sheet and one hash-tracked still per scene. Final output and cover are 1080x1920 at 30 fps;
an unwatermarked render remains impossible until every current gate and final-review hash passes.

Every script-generation path produces a strict retention plan and a separately recomputed
critique. The plan requires an honest opening of at most five seconds, a first event by two
seconds, no attention-event gap over five seconds, two distinct midpoint re-hooks, visible
evidence and limitation events, and explicit payoffs for every bounded curiosity thread. The
supported runtime is 45-75 seconds with 130-170 spoken words. Fixture generation supplies
topic-specific plans; manual and Codex imports receive deterministic provider-neutral planning
after schema validation. No provider artifact grants approval.

Generic-provider storyboard prompts receive a separately validated and hash-bound retention
context containing only timing, typed roles/devices, and provenance IDs. Event purpose prose and
sound cues are excluded; stale, mismatched, dependency-stale, or blocking state fails before
manual packet export or Codex invocation.

Only a complete, current retention chain is serialized to Remotion. Event times are scaled to the
narration-driven render duration. The render payload includes allowlisted IDs, times, event kinds,
and devices--not prose, paths, sound files, markup, or code--and binds each event to an exact
output frame. The renderer draws a single short geometric pulse inside the safe zone and uses
deterministic micro-beats between declared events. Stale or partially declared chains fail before
render instead of being guessed.

Creative QA is a deterministic advisory layer over the hard provenance, rights, staleness,
accessibility, and media gates. It evaluates a five-case golden corpus plus the active cover,
storyboard, script, captions, and current retention plan. Structural cover selection, evidence
links, human-readable citations, safe-zone geometry, unsafe caption timing or declared flashing,
and scene-still completeness are hard checks; the aggregate creative score and subjective polish
still require the final human watch-through. Motion QA is a declared/inferred-cue proxy, not full
rendered-pixel luminance analysis.

Persistence is deliberately filesystem-only. There is no database, authentication, cloud
service, queue, analytics, social publishing, or custom-scene-code runtime.

## ADR-002: provider output is drafting data, never proof

Fixture generation is deterministic and offline. Manual generation exports a versioned prompt
packet and imports strict JSON. Codex CLI generation is explicitly opt-in, uses the installed
login, an excerpt-only temporary directory, read-only/ephemeral execution, sanitized environment
variables, strict output schemas, timeouts, and one bounded schema-repair retry. Claims receive a
distinct critique pass; scripts receive deterministic editorial and retention plans and critiques
regardless of provider. Generation, critique, and engagement scoring never grant approval.

## Dependency decisions

- pypdf (BSD-3-Clause): text-PDF extraction and page labels; OCR remains out of scope.
- Pydantic and Typer (MIT): strict schemas and the local CLI.
- Streamlit (Apache-2.0): restart-safe local review surface.
- Remotion: the requested renderer, under its own commercial-use terms. Operators must confirm
  that their team/use qualifies or obtain the appropriate license.
- Atkinson Hyperlegible: bundled renderer font under the SIL Open Font License 1.1.
