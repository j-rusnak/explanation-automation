# techshort repository guidance

## Invariants

- Project data is untrusted. Never execute source text, scene data, or provider output.
- Every factual script segment must cite approved claims; every approved claim must cite resolvable evidence.
- A meaningful limitation, all five review gates, clean rights, and hard QA are required for final export.
- Upstream changes invalidate dependent approvals and renders. Review history is append-only.
- Writes to manifests are schema-validated and atomic. Project paths must remain under `projects/<slug>`.
- Preview video is watermarked until the final gate passes. Final export is never watermarked.
- Cover selection is part of storyboard review. A current cover, contact sheet, and representative still for every scene are required for final media QA.
- Narration is required by default. Silent output is valid only through the explicit `silent-reviewed` mode and final human review.
- Engagement must remain honest and evidence-linked: no bait, false urgency, deceptive withholding, unsupported certainty, or strobing. Retention heuristics never weaken provenance, limitation, rights, accessibility, or approval gates.
- Generated scripts require a current typed retention plan and critique. Attention gaps are at most five seconds, declared events are inert allowlisted data, and renderer event timing is narration-scaled and deterministic.
- Normal tests are offline; model calls are opt-in only.

## Commands

- Setup: `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`
- Python checks: `.venv\\Scripts\\python.exe -m ruff check .`, `-m mypy src`, `-m pytest`
- Renderer checks: `npm.cmd run format:check`, `npm.cmd run lint`, `npm.cmd run typecheck`, `npm.cmd run test:renderer`
- Demo: `.venv\\Scripts\\techshort.exe demo rolling-shutter --yes`
- Reviewer: `.venv\\Scripts\\streamlit.exe run reviewer/streamlit_app.py`

Do not commit private sources, narration, renders, exports, secrets, dependency directories, or generated project data.
