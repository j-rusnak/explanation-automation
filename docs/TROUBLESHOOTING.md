# Troubleshooting

- **`python` is missing:** install maintained CPython 3.11–3.14 and reopen PowerShell. `scripts/setup.ps1` also searches the standard per-user installation directory.
- **PowerShell blocks npm.ps1:** use `npm.cmd`, as all documented commands do.
- **Browser readiness fails:** rerun setup with network access so the pinned Remotion tooling can install its compatible Chrome Headless Shell, then rerun `techshort doctor` before working offline.
- **PDF says OCR required:** V1 intentionally does not guess text from scans. Provide a text-based PDF, Markdown, or text version.
- **PDF extraction is rejected as oversized:** convert it to a smaller text-based source or split it; techshort caps both input size and cumulative extracted output.
- **Codex provider unavailable:** install/authenticate the current Codex CLI or use `--provider fixture` / `--provider manual`. No API key is required for the offline workflow.
- **Codex returns schema errors:** update the CLI, run `codex login status`, and retry once. techshort permits only one bounded schema-repair attempt.
- **Narration import is rejected:** confirm FFmpeg/FFprobe is installed and the file contains a valid positive-duration audio stream; a renamed or malformed file is not accepted.
- **Permissively licensed narration is rejected:** provide concrete creator and license metadata (plus URL/attribution when required), or correct the asset in the rights reviewer before approval.
- **Export blocked:** run `techshort status <slug> --json`, repair stale/failed artifacts, rerun QA, watch the preview, then approve the final gate.
- **Narration differs from captions:** correct the approved script or re-record narration, import it, regenerate captions, and review again. Audio changes invalidate final approval.
