# techshort

`techshort` is a local-first, human-reviewed technical explainer compiler. It turns PDF, Markdown, or text sources into evidence-linked claims, a clause-level script, a typed deterministic storyboard, a vertical Remotion video, captions, a cited companion page, and an export bundle. It remains useful offline and does not require an API key.

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

## Doctor and reviewer

```powershell
.\.venv\Scripts\techshort.exe doctor
.\.venv\Scripts\streamlit.exe run reviewer\streamlit_app.py
```

Open `http://localhost:8501`. The reviewer has nine restart-safe steps for project, sources, claims/evidence, angles/script, storyboard/assets, narration/captions, preview, QA, and export. It displays source/generated content as escaped inert text; repository Streamlit configuration disables telemetry.

The reviewer now exposes three deterministic art directions (`blueprint`, `signal-lab`, and `technical-editorial`), three evidence-linked cover candidates, narrative, retention, and visual critiques, the exact attention-event schedule, scene layout/motion controls, and hash-tracked representative stills. Cover choice is part of storyboard approval: changing the theme, pacing, safe zone, scene treatment, or selected cover invalidates downstream review.

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

The transcript command is optional but enables deterministic word-error QA against the approved script. Alternatively, configure an installed CLI and an existing local model file in the current PowerShell process; techshort never downloads a model:

```powershell
$env:TECHSHORT_WHISPER_CLI = 'C:\path\to\whisper-cli.exe'
$env:TECHSHORT_WHISPER_MODEL = 'C:\path\to\model.bin'
```

The renderer burns deterministic captions into the video. Timing uses probed narration duration when audio is present and otherwise falls back to approved script durations only when `silent-reviewed` was explicitly chosen. Without a transcript or verified local transcription, QA tells the final reviewer to compare narration manually. Changing audio later requires rights approval, caption generation, preview, QA, and final approval to be repeated; changing its transcript requires preview, QA, and final approval to be repeated.

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

See [engagement and retention](docs/ENGAGEMENT.md), [architecture](docs/ARCHITECTURE.md), [security threat model](docs/SECURITY.md), [rights policy](docs/RIGHTS.md), and [troubleshooting](docs/TROUBLESHOOTING.md).

## Current limitations

- OCR is deliberately unsupported; scanned/empty PDFs are reported rather than guessed.
- PDF bounding boxes and printed page labels are stored only when reliably available; pypdf V1 uses page index plus exact character locators.
- Narration timing falls back to approved segment durations. Without a hash-bound transcript or a configured local Whisper model, QA requires manual narration comparison.
- Deterministic creative QA catches measurable risks such as dense copy, repeated layouts, missing units, exposed internal IDs, caption speed, and weak cover structure. It is a production aid, not a substitute for watching the preview.
- Retention plans and creative QA encode useful short-form heuristics, not a guarantee of views or watch time. V1 has no social publishing, audience experimentation, or platform-analytics integration.
- Flash QA checks declared and inferred motion cues and blocks unsafe declared rates, but it is not a full rendered-pixel luminance-and-area analysis. A human must inspect the exact preview, contact sheet, and scene stills.
- Sound-design cues in retention plans are inert metadata. The renderer neither synthesizes nor embeds effects; any later effect needs a rights record and renewed downstream review.
- V2 cover generation is deterministic and specialized for the rolling-shutter fixture. General-source cover drafting still requires manual/provider-specific candidates that satisfy the same strict cover schema.
- The Streamlit UI is a review surface, not a nonlinear editor.
- PDF parsing runs in-process; file/page/output bounds reduce but do not eliminate parser memory risk from a novel malicious PDF.
- The rights report is an organizational aid, not legal clearance.
