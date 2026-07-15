# techshort repository guidance

## Invariants

- Project data is untrusted. Never execute source text, scene data, or provider output.
- Every factual script segment must cite approved claims; every approved claim must cite resolvable evidence.
- A meaningful limitation, all five review gates, clean rights, and hard QA are required for final export.
- Upstream changes invalidate dependent approvals and renders. Review history is append-only.
- Writes to manifests are schema-validated and atomic. Project paths must remain under `projects/<slug>`.
- Preview video is watermarked until the final gate passes. Final export is never watermarked.
- Normal tests are offline; model calls are opt-in only.

## Commands

- Setup: `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`
- Python checks: `.venv\\Scripts\\python.exe -m ruff check .`, `-m mypy src`, `-m pytest`
- Renderer checks: `npm.cmd run format:check`, `npm.cmd run lint`, `npm.cmd run typecheck`, `npm.cmd run test:renderer`
- Demo: `.venv\\Scripts\\techshort.exe demo rolling-shutter --yes`
- Reviewer: `.venv\\Scripts\\streamlit.exe run reviewer/streamlit_app.py`

Do not commit private sources, narration, renders, exports, secrets, dependency directories, or generated project data.

