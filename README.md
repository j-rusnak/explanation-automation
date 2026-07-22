# techshort

`techshort` is a local-first, human-reviewed technical explainer compiler. It turns PDF, Markdown, or text sources into evidence-linked claims, a clause-level script, a typed deterministic storyboard, a vertical Remotion video, captions, a cited companion page, and an export bundle. It also supports offline synthetic narration, deterministic sound accents, controlled cover variants, aggregate-only organic experiment analysis, and immutable packages for manual TikTok or Instagram Reels upload. It remains useful offline and does not require an API key or platform account integration.

The hard invariant is simple: every factual script clause cites one or more approved claims, and every approved claim cites exact evidence that still resolves in the ingested source. Deterministic QA and five human gates block final export when provenance, rights, staleness, limitation, or media checks fail.

Short-form engagement is also deterministic and reviewable. Every generated script receives an
honest cold-open contract, a typed 45-75-second cadence, claim-linked attention events at gaps of
no more than five seconds, two distinct mid-video re-hooks, an evidence payoff, and a limitation
reframe. These controls improve editorial craft without treating attention as proof or promising
platform performance.

## Requirements and licenses

- Windows PowerShell (the tested host), Python 3.11–3.14, Node.js 22, npm, and Git. Final verification used Python 3.13.14 and Node.js 22.17.1.
- [Remotion 4.0.489](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md). Its current custom license permits some individuals/small teams to use it without charge; other organizations and automated-video products may require a paid license. Confirm eligibility before commercial use.
- Setup explicitly downloads and verifies Remotion's Chrome Headless Shell. Its npm package includes an FFmpeg build marked non-redistributable; `node_modules` is excluded from Git and must not be redistributed. Review your own distribution obligations.
- [pypdf](https://github.com/py-pdf/pypdf/blob/main/LICENSE) is BSD-3-Clause, Pydantic/Typer are MIT, Streamlit is Apache-2.0, and Atkinson Hyperlegible is SIL OFL 1.1.
- The pinned `kokoro-js` runtime and pinned Kokoro ONNX model are Apache-2.0. That covers the model/runtime artifacts; it does not automatically establish rights to a selected generated voice or its output. Synthetic narration remains `unknown` until a human rights review records the applicable terms.

This repository already contained an MIT `LICENSE`; techshort did not add or change it.

## Install

Install a supported Python and Node.js 22, then from the repository root run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

The exact commands performed are:

```powershell
python -m venv .venv  # only when .venv does not already exist
.\.venv\Scripts\python.exe -m pip install pip==26.1.2
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" --no-deps --no-build-isolation
npm.cmd ci
npm.cmd exec remotion -- browser ensure
.\.venv\Scripts\python.exe scripts\export_schemas.py
.\.venv\Scripts\techshort.exe doctor
```

Direct Python dependencies and all npm dependencies are exact-pinned; `requirements.lock` and `package-lock.json` lock the resolved transitive environments.

### Optional one-time Kokoro model setup

Normal setup installs the pinned local runtime but intentionally does not download the optional
model. On a machine that will use Kokoro narration, run this explicit one-time command while
network access is available:

```powershell
.\.venv\Scripts\techshort.exe audio setup --provider kokoro --yes
```

The command invokes the fixed helper, downloads only `onnx-community/Kokoro-82M-v1.0-ONNX` at revision
`1939ad2a8e416c0acfeecc08a694d14ef25f2231`, using the `q8` model on CPU. It then reports the
cache file hashes and aggregate SHA-256 in a strict local manifest. Synthesis opens that same cache with remote model
access disabled, so no network connection is needed after setup. `.techshort/` is Git-ignored;
model files must not be committed or placed in project exports.

## Doctor and reviewer

```powershell
.\.venv\Scripts\techshort.exe doctor
.\.venv\Scripts\streamlit.exe run reviewer\streamlit_app.py
```

Open `http://localhost:8501`. The reviewer has ten restart-safe steps for project, sources, claims/evidence, angles/script, storyboard/assets, narration/captions, preview, QA, export, and organic experiments. It displays source/generated content as escaped inert text; repository Streamlit configuration disables telemetry.

The reviewer now exposes four deterministic art directions. New projects use the recommended
`kinetic-pop` hybrid: high-contrast editorial typography, a recurring topic-specific hero object,
and tactile evidence receipts. Its viewport stays stable after short scene-boundary transitions;
scan lines, comparisons, highlights, and progress rails move only when they explain a state change.
The quieter `blueprint`, `signal-lab`, and
`technical-editorial` themes remain available for existing projects. The reviewer also exposes
three evidence-linked cover candidates, narrative, retention, and visual critiques, the exact
attention-event schedule, scene layout/motion controls, local narration and sound controls,
hash-tracked representative stills, and the manual organic experiment workflow. Cover choice is
part of storyboard approval: changing the theme, pacing, safe zone, scene treatment, or selected
cover invalidates downstream review.

## Complete sample workflow

The sample source is original project prose about rolling-shutter distortion. The normal deterministic flow is:

```powershell
.\.venv\Scripts\techshort.exe init rolling-shutter --title "Rolling-Shutter Distortion"
.\.venv\Scripts\techshort.exe style pacing rolling-shutter high-retention
.\.venv\Scripts\techshort.exe style safe-zone rolling-shutter --top 0.06 --right 0.14 --bottom 0.17 --left 0.067
.\.venv\Scripts\techshort.exe audio mode rolling-shutter silent-reviewed
.\.venv\Scripts\techshort.exe ingest rolling-shutter examples\rolling-shutter\rolling-shutter.md
.\.venv\Scripts\techshort.exe claims generate rolling-shutter --provider fixture
.\.venv\Scripts\techshort.exe review rolling-shutter --gate claims
.\.venv\Scripts\techshort.exe script angles rolling-shutter --provider fixture
.\.venv\Scripts\techshort.exe script select-angle rolling-shutter everyday-mechanism
.\.venv\Scripts\techshort.exe script generate rolling-shutter --provider fixture --angle everyday-mechanism
.\.venv\Scripts\techshort.exe review rolling-shutter --gate script
.\.venv\Scripts\techshort.exe storyboard generate rolling-shutter --provider fixture
.\.venv\Scripts\techshort.exe cover generate rolling-shutter
.\.venv\Scripts\techshort.exe cover select rolling-shutter cover-scanline
.\.venv\Scripts\techshort.exe review rolling-shutter --gate storyboard
.\.venv\Scripts\techshort.exe review rolling-shutter --gate rights
.\.venv\Scripts\techshort.exe captions generate rolling-shutter
.\.venv\Scripts\techshort.exe preview rolling-shutter
.\.venv\Scripts\techshort.exe qa rolling-shutter
.\.venv\Scripts\techshort.exe evidence-page rolling-shutter
.\.venv\Scripts\techshort.exe review rolling-shutter --gate final
.\.venv\Scripts\techshort.exe render rolling-shutter
.\.venv\Scripts\techshort.exe export rolling-shutter
```

Or run the same sequence with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/demo.ps1
```

The equivalent one-command CLI demo is explicit about recording fixture review decisions:

```powershell
.\.venv\Scripts\techshort.exe demo rolling-shutter --yes
```

New projects default to `narrated`, so missing audio fails render and QA. The sample command above explicitly selects the caption-led `silent-reviewed` path. To use user-recorded narration instead, omit that mode command and insert these commands before the rights gate and caption generation:

```powershell
.\.venv\Scripts\techshort.exe audio import rolling-shutter C:\path\to\narration.wav --rights-status user-owned --creator "Your name"
.\.venv\Scripts\techshort.exe audio import-transcript rolling-shutter C:\path\to\narration.txt
```

For the current synthetic-first workflow, omit the `silent-reviewed` mode command and run this
after script approval. Manual recording is not required:

```powershell
.\.venv\Scripts\techshort.exe audio voices --provider kokoro
.\.venv\Scripts\techshort.exe audio synthesize rolling-shutter --provider kokoro --voice af_heart --speed 1.1
.\.venv\Scripts\techshort.exe audio sound-design rolling-shutter --preset subtle
```

Synthesis defaults its rights assertion to `unknown`, so previewing is safe but final rights approval
remains blocked. Review the selected voice/output terms in the reviewer, record only the status and
license details they actually support, then regenerate narration with those accurate rights options
before approving rights. Do not choose a permissive status merely to make the sample export pass.

The transcript command is optional but enables deterministic word-error QA against the approved script. Alternatively, configure an installed CLI and an existing local model file in the current PowerShell process; techshort never downloads a model:

```powershell
$env:TECHSHORT_WHISPER_CLI = 'C:\path\to\whisper-cli.exe'
$env:TECHSHORT_WHISPER_MODEL = 'C:\path\to\model.bin'
```

The renderer burns deterministic captions into the video. Timing uses probed narration duration when audio is present and otherwise falls back to approved script durations only when `silent-reviewed` was explicitly chosen. Without a transcript or verified local transcription, QA tells the final reviewer to compare narration manually. Changing audio later requires rights approval, caption generation, preview, QA, and final approval to be repeated; changing its transcript requires preview, QA, and final approval to be repeated.

### Offline synthetic narration and sound design

User-recorded narration is supported, but it is not required. The repository contains a pinned
Kokoro runtime for offline segment synthesis after the one-time model setup above. Kokoro is the
default project-level provider; Windows System.Speech remains the zero-cost Windows fallback.
There is no voice-cloning path: both runtimes select only an installed or explicitly allowlisted
stock voice.

The Kokoro Node helper accepts strict JSON rather than arbitrary text flags, markup, or code. List
its reviewed English voices with:

```powershell
node renderer/scripts/kokoro-local.mjs voices
```

Its input contract is exactly `schemaVersion`, `voice`, `speed`, and `segments`; every segment is
exactly `segmentId` plus one line of inert `text`. Speed is bounded from `0.75` to `1.5`, segment
IDs must be unique stable IDs, and the input is limited to 100 segments and 128 KiB:

```json
{
  "schemaVersion": "1.0.0",
  "voice": "af_heart",
  "speed": 1,
  "segments": [
    {
      "segmentId": "segment-01",
      "text": "A rolling shutter records neighboring rows at different moments."
    }
  ]
}
```

The low-level synthesis command exists for runtime verification and integration work; it is not a
project manifest or rights approval command. Create the output directory first, then pass a JSON
file matching the contract:

```powershell
New-Item -ItemType Directory -Force .techshort\kokoro-output | Out-Null
node renderer/scripts/kokoro-local.mjs synthesize `
  --cache-dir .techshort/models/kokoro `
  --input C:\path\to\kokoro-input.json `
  --output-dir .techshort\kokoro-output
```

Successful stdout is strict JSON containing the provider, model ID, pinned revision, `q8` dtype,
CPU device, runtime version, selected voice and speed, aggregate model-cache SHA-256, and one
record per `segmentId` with its deterministic WAV filename, 24 kHz sample rate, sample count, and
duration. Synthesis never enables remote model access. Any generated WAV still needs to enter the
normal asset workflow and receive human rights review before embedding. Normal project synthesis
uses the safer `techshort audio synthesize ... --provider kokoro` command above; the low-level
helper exists for runtime diagnostics.

On Windows, list enabled System.Speech voices after approving the script:

```powershell
.\.venv\Scripts\techshort.exe audio voices --provider sapi
.\.venv\Scripts\techshort.exe audio synthesize rolling-shutter --provider sapi --voice "<installed voice name>" --rate 1 --volume 100
.\.venv\Scripts\techshort.exe audio sound-design rolling-shutter --preset subtle
```

Both providers write hash-bound, per-segment audio, transcript, timing, provenance receipt, and
asset records; neither calls a cloud TTS service during synthesis. SAPI timing uses verified engine
word events. Kokoro currently uses exact synthesized segment boundaries and explicitly labeled
proportional word timing because its runtime does not emit word events. The default synthetic-voice
rights status is `unknown`, which intentionally blocks final export.
Review the installed voice and output terms, then rerun synthesis with the accurate
`--rights-status`, `--license`, and `--required-attribution` values when applicable. Do not label
output original, owned, or permissively licensed without evidence.

`audio sound-design` creates a quiet original procedural WAV from the current allowlisted
retention cues. It never downloads music or samples. The resulting sound asset still requires
human rights review, and both audio commands invalidate affected downstream approvals. Generate
captions, preview, QA, and final approval again after the final audio is selected.

#### Kokoro troubleshooting

- If synthesis says the cache is missing or lacks the pinned ONNX model, rerun the one-time
  `setup` command with network access. Do not enable remote model access during synthesis.
- If setup reports a different revision, dtype, or device than documented above, stop and inspect
  the installed lockfile/runtime before generating narration. Normal operation is the pinned
  revision, `q8`, and CPU only.
- An empty or modified cache should be replaced by rerunning setup, not copied into Git. The
  `.techshort/` directory being absent from `git status` is expected.
- `techshort audio voices` lists the Kokoro allowlist by default. Use `--provider sapi` to list
  enabled Windows System.Speech fallback voices.

### Zero-cost organic cover experiments

Experiments begin from a current approved export and reviewed cover candidates. They never log
in, open a browser, upload, post, or fetch analytics. Create and inspect immutable cover variants:

```powershell
.\.venv\Scripts\techshort.exe experiment create-cover rolling-shutter `
  --name "rolling-shutter-cover-01" `
  --hypothesis "A mechanism-first cover may improve completion rate." `
  --platform tiktok `
  --primary-metric completion-rate `
  --minimum-views 500 `
  --json
.\.venv\Scripts\techshort.exe experiment list rolling-shutter --json
.\.venv\Scripts\techshort.exe experiment approve rolling-shutter <experiment-id> --reviewer local-reviewer
.\.venv\Scripts\techshort.exe experiment status rolling-shutter <experiment-id> --json
```

Prepare one immutable package per approved variant. The package commands remain local and do not
publish anything:

```powershell
.\.venv\Scripts\techshort.exe publication diagnostics tiktok --provider manual --json
.\.venv\Scripts\techshort.exe publication prepare-request rolling-shutter <experiment-id> <variant-id> `
  --post-copy "<reviewed post copy>" `
  --alt-text "<accessible description>" `
  --hashtag CameraTech `
  --json
.\.venv\Scripts\techshort.exe publication package rolling-shutter <request-json-path> --json
.\.venv\Scripts\techshort.exe publication consent-package rolling-shutter `
  <request-json-path> <pending-package-manifest-path> `
  --state granted `
  --reviewer local-reviewer `
  --confirmation "I explicitly authorize manual publication of this exact variant package." `
  --json
```

Inspect the granted package, then manually upload it in the platform's own composer. No official
provider, API credential, account session, or automated browser posting is implemented. After
each real organic post reaches a comparable observation age, manually record only actual
aggregate totals in JSON or CSV. Never invent metrics and never include viewer identifiers,
usernames, handles, email addresses, device IDs, or other person-level rows.

```powershell
.\.venv\Scripts\techshort.exe experiment metrics-template rolling-shutter <experiment-id> --format json --output actual-observations.json
.\.venv\Scripts\techshort.exe experiment import-observations rolling-shutter <experiment-id> <completed-template-path> --format json
.\.venv\Scripts\techshort.exe experiment analyze rolling-shutter <experiment-id> --json
.\.venv\Scripts\techshort.exe experiment approve-recommendation rolling-shutter <experiment-id> <recommendation-id> --reviewer local-reviewer
.\.venv\Scripts\techshort.exe experiment apply-recommendation rolling-shutter <experiment-id> <recommendation-id> --reviewer local-reviewer
```

Analysis uses the latest cumulative snapshot for each variant, requires comparable observation
windows and the configured minimum views, and never changes production. Wilson intervals are
available only for completion and skip proportions. They cover sampling error under that model,
not organic distribution, posting time, or audience-mix confounding; other aggregate metrics
remain explicitly uncertain. Only a conclusive, separately approved cover recommendation can be
applied, and applying a changed cover invalidates storyboard, rights, and final review.

See [organic experiments](docs/EXPERIMENTS.md) for the observation fields, storage layout,
interpretation limits, and complete manual workflow.

Successful sample outputs are written to:

- `projects/rolling-shutter/renders/final/final.mp4`
- `projects/rolling-shutter/export/rolling-shutter.mp4`
- `projects/rolling-shutter/export/evidence.html`
- `projects/rolling-shutter/export/` for the complete portable bundle

## Verification

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest
npm.cmd run format:check
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run test:renderer
```

`powershell -ExecutionPolicy Bypass -File scripts/check.ps1` runs all of these. Normal tests are offline and never invoke a model. The real renderer E2E is explicitly enabled with `TECHSHORT_RUN_RENDER_E2E=1`.

```powershell
$env:TECHSHORT_RUN_RENDER_E2E = '1'
.\.venv\Scripts\python.exe -m pytest tests\e2e\test_render_pipeline.py
```

The package also provides one-command aliases:

```powershell
npm.cmd run setup
npm.cmd test
npm.cmd run demo
npm.cmd run render-sample
```

## Providers

- `fixture`: deterministic offline claims/critique/angles/script/storyboard used by the complete example and tests.
- Every script-generation path persists a narrative brief, factual locks, beat plan, retention plan, editorial critique, and retention critique. Fixture generation uses angle-specific topic direction; manual and Codex output receive deterministic provider-neutral constraints after strict import. These artifacts remain drafting constraints, never proof or approval.
- `manual`: exports an untrusted-data prompt packet and strictly validates imported JSON before applying the same local editorial and retention checks.
- `codex`: optional Codex CLI provider. It requires a locally installed authenticated CLI with `codex exec`, `--ephemeral`, `--sandbox read-only`, `--output-schema`, and `--output-last-message`. It uses an excerpt-only temporary directory, argument arrays, a timeout, no code execution, and strict Pydantic validation. A live authenticated claims-plus-critique smoke was run on the tested host; the offline path remains unaffected when Codex is missing.

Manual and Codex storyboard generation receives a validated, prose-free retention context with
beat timing, allowlisted event kinds, visual devices, and claim IDs. Free-form event purpose and
sound metadata are excluded, and stale or blocking context is rejected before a prompt is written.

Only the current, validated retention chain reaches Remotion. Its allowlisted event kind, visual
device, ID, and narration-scaled time drive a short safe-zone-contained geometric pulse on an
exact frame; provider text, event prose, paths, sounds, and code are excluded from the render
payload.

## Storage and security

Runtime projects live under `projects/<slug>` and are Git-ignored. Writes are atomic and validated. Regeneration archives the prior manifest version. Edits transitively stale downstream artifacts and append invalidation records to review history. Sources, extracted full text, narration, renders, secrets, exports, dependencies, and temporary provider data are excluded from Git.

See [engagement and retention](docs/ENGAGEMENT.md), [organic experiments](docs/EXPERIMENTS.md), [architecture](docs/ARCHITECTURE.md), [security threat model](docs/SECURITY.md), [rights policy](docs/RIGHTS.md), and [troubleshooting](docs/TROUBLESHOOTING.md).

## Current limitations

- OCR is deliberately unsupported; scanned/empty PDFs are reported rather than guessed.
- PDF bounding boxes and printed page labels are stored only when reliably available; pypdf V1 uses page index plus exact character locators.
- SAPI narration uses verified engine word events. Kokoro word emphasis is an explicitly labeled proportional estimate inside exact synthesized segment boundaries; provider words never replace approved caption text. Imported recordings still need a hash-bound transcript or configured local Whisper model for deterministic comparison.
- Deterministic creative QA catches measurable risks such as dense copy, repeated layouts, missing units, exposed internal IDs, caption speed, and weak cover structure. It is a production aid, not a substitute for watching the preview.
- Retention plans and creative QA encode useful short-form heuristics, not a guarantee of views or watch time. Organic cover experiments use manually imported aggregates and remain observational; there is no platform-analytics integration, account automation, automatic publishing, or causal-performance guarantee.
- Flash QA checks declared and inferred motion cues and blocks unsafe declared rates, but it is not a full rendered-pixel luminance-and-area analysis. A human must inspect the exact preview, contact sheet, and scene stills.
- The optional procedural sound-design track uses only allowlisted deterministic cues and is rights-tracked. It is not music, a sample library, adaptive scoring, or proof that sound will improve performance.
- Kokoro requires one explicit networked model-setup step before offline use. It is the default project provider; Windows System.Speech remains an offline fallback. Both synthetic paths require human review of voice/output rights, and `unknown` deliberately blocks embedding.
- V2 cover generation is deterministic and specialized for the rolling-shutter fixture. General-source cover drafting still requires manual/provider-specific candidates that satisfy the same strict cover schema.
- The Streamlit UI is a review surface, not a nonlinear editor.
- PDF parsing runs in-process; file/page/output bounds reduce but do not eliminate parser memory risk from a novel malicious PDF.
- The rights report is an organizational aid, not legal clearance.
