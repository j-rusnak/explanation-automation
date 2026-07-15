# techshort

`techshort` is a local-first, human-reviewed technical explainer compiler. It turns PDF, Markdown, or text sources into evidence-linked claims, a clause-level script, a typed deterministic storyboard, a vertical Remotion video, captions, a cited companion page, and an export bundle. It remains useful offline and does not require an API key.

The hard invariant is simple: every factual script clause cites one or more approved claims, and every approved claim cites exact evidence that still resolves in the ingested source. Deterministic QA and five human gates block final export when provenance, rights, staleness, limitation, or media checks fail.

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

## Complete sample workflow

The sample source is original project prose about rolling-shutter distortion. The normal deterministic flow is:

```powershell
.\.venv\Scripts\techshort.exe init rolling-shutter --title "Rolling-Shutter Distortion"
.\.venv\Scripts\techshort.exe ingest rolling-shutter examples\rolling-shutter\rolling-shutter.md
.\.venv\Scripts\techshort.exe claims generate rolling-shutter --provider fixture
.\.venv\Scripts\techshort.exe review rolling-shutter --gate claims
.\.venv\Scripts\techshort.exe script angles rolling-shutter --provider fixture
.\.venv\Scripts\techshort.exe script select-angle rolling-shutter everyday-mechanism
.\.venv\Scripts\techshort.exe script generate rolling-shutter --provider fixture --angle everyday-mechanism
.\.venv\Scripts\techshort.exe review rolling-shutter --gate script
.\.venv\Scripts\techshort.exe storyboard generate rolling-shutter --provider fixture
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

To use user-recorded narration, insert these commands before the rights gate and caption generation:

```powershell
.\.venv\Scripts\techshort.exe audio import rolling-shutter C:\path\to\narration.wav --rights-status user-owned --creator "Your name"
.\.venv\Scripts\techshort.exe audio import-transcript rolling-shutter C:\path\to\narration.txt
```

The transcript command is optional but enables deterministic word-error QA against the approved script. Alternatively, configure an installed CLI and an existing local model file in the current PowerShell process; techshort never downloads a model:

```powershell
$env:TECHSHORT_WHISPER_CLI = 'C:\path\to\whisper-cli.exe'
$env:TECHSHORT_WHISPER_MODEL = 'C:\path\to\model.bin'
```

The renderer burns deterministic captions into the video. Timing uses probed narration duration when audio is present and otherwise falls back to approved script durations. Without a transcript or verified local transcription, QA tells the final reviewer to compare narration manually. Changing audio later requires rights approval, caption generation, preview, QA, and final approval to be repeated; changing its transcript requires preview, QA, and final approval to be repeated.

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
- `manual`: exports an untrusted-data prompt packet and strictly validates imported JSON.
- `codex`: optional Codex CLI provider. It requires a locally installed authenticated CLI with `codex exec`, `--ephemeral`, `--sandbox read-only`, `--output-schema`, and `--output-last-message`. It uses an excerpt-only temporary directory, argument arrays, a timeout, no code execution, and strict Pydantic validation. A live authenticated claims-plus-critique smoke was run on the tested host; the offline path remains unaffected when Codex is missing.

## Storage and security

Runtime projects live under `projects/<slug>` and are Git-ignored. Writes are atomic and validated. Regeneration archives the prior manifest version. Edits transitively stale downstream artifacts and append invalidation records to review history. Sources, extracted full text, narration, renders, secrets, exports, dependencies, and temporary provider data are excluded from Git.

See [architecture](docs/ARCHITECTURE.md), [security threat model](docs/SECURITY.md), [rights policy](docs/RIGHTS.md), and [troubleshooting](docs/TROUBLESHOOTING.md).

## Current limitations

- OCR is deliberately unsupported; scanned/empty PDFs are reported rather than guessed.
- PDF bounding boxes and printed page labels are stored only when reliably available; pypdf V1 uses page index plus exact character locators.
- Narration timing falls back to approved segment durations. Without a hash-bound transcript or a configured local Whisper model, QA requires manual narration comparison.
- The Streamlit UI is a review surface, not a nonlinear editor.
- PDF parsing runs in-process; file/page/output bounds reduce but do not eliminate parser memory risk from a novel malicious PDF.
- The rights report is an organizational aid, not legal clearance.
