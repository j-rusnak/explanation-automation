# Architecture decision record

## ADR-001: local manifests and deterministic rendering

techshort is a local compiler with a hard trust boundary between untrusted source/provider text
and allowlisted application behavior. Python owns strict Pydantic schemas, extraction, exact
evidence resolution, append-only review state, invalidation, captions, QA, and export. Remotion
consumes only validated scene and retention data; no project value is evaluated as code.

The production dependency graph is:

`source -> evidence -> claims + independent critique -> candidate angles + selection -> narrative brief + factual locks + beat plan -> script + editorial critique + retention plan + retention critique -> storyboard guidance + typed storyboard + visual critique -> cover candidates + selection + assets + narration or explicit silent mode + optional procedural sound -> captions -> preview + contact sheet + scene stills -> technical and creative QA -> final approval -> final render -> export`

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

Four centralized themes, six layout presets, three motion presets, and three pacing profiles
parameterize those primitives without generating runtime code. `kinetic-pop`, the default for new
projects, combines high-contrast editorial type, semantic chapter colors, a deterministic
topic-specific hero object, and tactile evidence treatments derived only from validated scene and
evidence fields. Motion communicates scan timing, comparison, emphasis, or chapter progress; it is
not random decoration and may not strobe. Scene-boundary transitions may reframe Kinetic Pop, after
which its viewport remains stable. Whole-frame motion must reveal, follow, focus, or re-contextualize
something, and attention changes land at information boundaries. The first frame carries value or
visual proof. The three legacy themes preserve their existing visual grammar. Project configuration
also carries one bounded, resolution-independent safe zone shared by captions, essential scene
content, covers, and retention overlays. The selected evidence-linked cover is rendered by its own
composition.
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

Persistence is deliberately filesystem-only. There is no database, local account system, cloud
service, queue, platform analytics integration, direct social publishing, background scheduler,
or custom-scene-code runtime. The optional official TikTok boundary described in ADR-004 transfers
one explicitly authorized package to the identified account's TikTok inbox as a draft; it does
not publish the post.

## ADR-002: provider output is drafting data, never proof

Fixture generation is deterministic and offline. Manual generation exports a versioned prompt
packet and imports strict JSON. Codex CLI generation is explicitly opt-in, uses the installed
login, an excerpt-only temporary directory, read-only/ephemeral execution, sanitized environment
variables, strict output schemas, timeouts, and one bounded schema-repair retry. Claims receive a
distinct critique pass; scripts receive deterministic editorial and retention plans and critiques
regardless of provider. Generation, critique, and engagement scoring never grant approval.

## ADR-003: local audio and human-operated organic experiments

User-recorded narration is supported but not required. The selected cross-platform offline model
runtime is `kokoro-js` with `onnx-community/Kokoro-82M-v1.0-ONNX`, pinned to revision
`1939ad2a8e416c0acfeecc08a694d14ef25f2231`, `q8`, and CPU. Model acquisition is a separate,
explicit one-time action. It writes to the Git-ignored `.techshort/models/kokoro` cache and emits
file hashes plus an aggregate SHA-256. Normal synthesis reopens that cache with remote models
disabled, so it cannot silently fetch a different revision.

The Kokoro boundary is a fixed Node helper with a strict versioned JSON contract. It accepts only
an allowlisted stock English voice, bounded speed, and up to 100 stable-ID script segments. It
produces numbered 24 kHz WAV files plus inert JSON metadata; it does not accept SSML, executable
markup, provider-selected paths, or voice-cloning input. Segment synthesis makes narration
addressable without treating audio as proof. The model and runtime are Apache-2.0, while selected
voice and generated-output rights remain `unknown` until a human records an accurate rights
decision.

Both providers synthesize one approved script segment at a time, normalize each segment to 48 kHz
mono PCM, retain content-addressed segment WAVs, and concatenate them with an exact 140 ms pause.
The synthesis receipt binds every segment's text approval, audio hash, frame count, provider, and
runtime state. System.Speech word-progress events are aligned only onto exact approved tokens.
Kokoro emits no word events, so its manifest honestly uses proportional word timing inside each
exact synthesized segment interval. Renderer captions, SRT/VTT, QA, and final-review hashing all
resolve the same timing manifest; provider-inserted text can never become caption text.

Windows System.Speech remains the zero-cost integrated fallback. It receives only the current
human-approved script, invokes a fixed local synthesis helper, and writes audio, a transcript, and
a strict content-derived receipt. Installed voice discovery is local. Neither local path uses a
cloud TTS endpoint, API key, arbitrary downloaded code, or provider-selected executable path.
Optional sound accents are generated from allowlisted retention cue enums with deterministic
oscillators, bounded amplitude, and no downloaded samples.

Organic experimentation begins only after a current approved export exists. A cover experiment
renders two or three approved cover candidates around the exact same video and locks evidence,
claims, limitation, factual content, and rights hashes. Experiment and variant approval decisions
are append-only. Immutable publication packages bind approved media, cover, captions, reviewed
copy, accessibility text, checksums, and a separate human consent receipt. Package generation is
not publication. The operator may use the platform's own composer manually, or may make a
separately consented TikTok draft transfer through the official boundary in ADR-004.

The feedback path is:

`approved export -> controlled cover variants -> experiment approval -> local package + package consent -> manual composer or separately consented TikTok draft transfer -> operator finishes and publishes an organic post -> manual aggregate snapshots -> conservative comparison -> recommendation -> recommendation approval -> explicit cover application -> normal downstream invalidation`

Observation manifests accept cumulative post-level totals only and reject person-level fields.
The evaluator uses comparable post-age windows and configured minimum views. Wilson intervals are
limited to completion and skip proportions; aggregate metrics without defensible variance remain
explicitly uncertain. Recommendations never edit factual artifacts, and analysis never applies a
change. Only a separately approved cover recommendation can reach the existing cover-selection
service, which invalidates storyboard, rights, and final approval when selection changes.

## ADR-004: official TikTok draft transfer, never direct publication

TikTok automation is intentionally limited to the official Content Posting API's draft-upload
flow with the `video.upload` scope. The fixed operation initializes a TikTok inbox upload,
transfers the exact reviewed MP4, and polls its provider status. It does not use Direct Post,
request `video.publish`, choose public visibility, schedule a post, open a browser, reuse cookies
or sessions, or claim that a draft was published. See TikTok's official
[Upload API reference](https://developers.tiktok.com/doc/content-posting-api-reference-upload-video/),
[status reference](https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status),
and [content-sharing guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines/).

This is a separate authorization boundary from package preparation and manual-package consent.
Before any network request, a new human decision must reproduce the exact confirmation phrase and
bind the current immutable package hash, video hash, experiment and variant, the TikTok OAuth
subject hash, and a human-readable account label. Preflight revalidates the package against the
current approved export, experiment, evidence, claims, limitation, and rights state. Intent,
consent, preflight, attempt, and chained status receipts are persisted before and after the
network boundary as append-only, content-derived records.

The access token and TikTok OpenID are accepted only from the current process environment and are
never written to a manifest, package, diagnostic, error report, or log. The low-level client uses
fixed official HTTPS hosts, bounded requests and responses, one whole-file upload, timeouts, and
redacted diagnostics. A definite provider rejection is recorded as failed. A timeout, disconnect,
or other uncertain network result is recorded as ambiguous and is never re-uploaded automatically;
the operator must inspect TikTok before considering a newly reviewed package and intent. When an
ambiguous receipt retains a publish ID, status polling may resolve it without uploading again.
Normal tests inject a fake transport and never contact TikTok.

TikTok's draft-upload operation transfers only the MP4. The reviewed standalone cover PNG,
post copy, SRT/VTT sidecars, and accessibility metadata remain in the local package. Burned-in
captions remain inside the reviewed MP4, but the operator must select the reviewed cover and
finish all post metadata in TikTok before publishing. A TikTok developer app, an OAuth grant with
`video.upload`, and an access token for the intended account are operator-provided prerequisites.
The access token and OpenID must come from the same OAuth token response. V1 deliberately accepts
only MP4 files up to 64,000,000 bytes so the transfer is one non-retriable chunk; larger reviewed
videos stay on the manual package path.

## Dependency decisions

- pypdf (BSD-3-Clause): text-PDF extraction and page labels; OCR remains out of scope.
- Pydantic and Typer (MIT): strict schemas and the local CLI.
- Streamlit (Apache-2.0): restart-safe local review surface.
- kokoro-js 1.2.1 and the pinned Kokoro ONNX model (Apache-2.0): optional local segment
  synthesis after an explicit one-time model-cache setup; runtime inference is `q8` on CPU with
  remote model access disabled.
- Remotion: the requested renderer, under its own commercial-use terms. Operators must confirm
  that their team/use qualifies or obtain the appropriate license.
- Atkinson Hyperlegible: bundled renderer font under the SIL Open Font License 1.1.
