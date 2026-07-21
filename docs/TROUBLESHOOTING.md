# Troubleshooting

- **`python` is missing:** install maintained CPython 3.11–3.14 and reopen PowerShell. `scripts/setup.ps1` also searches the standard per-user installation directory.
- **PowerShell blocks npm.ps1:** use `npm.cmd`, as all documented commands do.
- **Browser readiness fails:** rerun setup with network access so the pinned Remotion tooling can install its compatible Chrome Headless Shell, then rerun `techshort doctor` before working offline.
- **PDF says OCR required:** V1 intentionally does not guess text from scans. Provide a text-based PDF, Markdown, or text version.
- **PDF extraction is rejected as oversized:** convert it to a smaller text-based source or split it; techshort caps both input size and cumulative extracted output.
- **Codex provider unavailable:** install/authenticate the current Codex CLI or use `--provider fixture` / `--provider manual`. No API key is required for the offline workflow.
- **Codex returns schema errors:** update the CLI, run `codex login status`, and retry once. techshort permits only one bounded schema-repair attempt.
- **Narration import is rejected:** confirm FFmpeg/FFprobe is installed and the file contains a valid positive-duration audio stream; a renamed or malformed file is not accepted.
- **Preview says narration is required:** import reviewed narration, or explicitly choose caption-led output with `techshort audio mode <slug> silent-reviewed`. Missing audio never switches modes automatically.
- **Storyboard approval says a cover is missing:** run `techshort cover generate <slug>`, inspect all three directions, then run `techshort cover select <slug> <candidate-id>` before approving the storyboard.
- **Pacing or safe-zone changes made approvals stale:** this is intentional. Reinspect the storyboard and cover, then regenerate the preview, contact sheet, scene stills, captions if affected, and QA before repeating final approval.
- **Retention QA says the schedule is missing or stale:** regenerate the script with the selected provider, review the narrative/beat/retention artifacts, then reapprove the script. Do not hand-edit version IDs or copy a plan from another script.
- **Cold-open or cadence QA fails:** keep the first honest beat at five seconds or less, declare the first attention event by two seconds, and keep every planned gap--including the last one--at five seconds or less. Re-hooks must advance an approved mechanism or evidence payoff rather than use engagement bait.
- **Creative QA reports a warning:** inspect `renders/<preview-or-final>/creative-quality.json`, the contact sheet, and the representative still beside every storyboard scene. The aggregate score is advisory, but hard cover/provenance/accessibility/media failures still block export.
- **Caption or motion accessibility fails:** lengthen or split overlapping/too-fast cues and remove strobe or rapid flash directions. The motion check is not full pixel-luminance analysis, so also watch the exact rendered preview before approval.
- **Permissively licensed narration is rejected:** provide concrete creator and license metadata (plus URL/attribution when required), or correct the asset in the rights reviewer before approval.
- **Export blocked:** run `techshort status <slug> --json`, repair stale/failed artifacts, rerun QA, watch the preview, then approve the final gate.
- **Narration differs from captions:** correct the approved script or re-record narration, import it, regenerate captions, and review again. Audio changes invalidate final approval.
