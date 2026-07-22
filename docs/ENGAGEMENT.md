# Engagement and retention

`techshort` treats attention as an editorial constraint, never as permission to weaken
evidence, hide a limitation, or manufacture certainty. The goal is a fast, clear technical
explanation whose opening promise is paid off with approved evidence on screen. These controls
can improve craft, but they cannot guarantee reach, retention, or platform success.

## Default short-form contract

- The cold open is the first script beat, lasts no more than five seconds, and names the real
  subject or result. The first declared visual attention event must occur by two seconds.
- Scripts support the product's 45-75-second window, preserve the 130-170-word target, and cap
  narration at 175 words per minute overall. Individual beats are short and remain readable.
- A typed retention plan opens bounded curiosity threads, schedules claim-linked attention
  events, places two distinct mid-video re-hooks, pays off visible evidence, states one meaningful
  limitation, and resolves every opening promise.
- No planned interval--including the opening and closing intervals--may exceed five seconds
  without a purposeful attention event. Renderer micro-beats add restrained development inside
  scenes; they do not replace the declared, evidence-linked event schedule.
- `high-retention` pacing is the project default. `brisk` and `measured` remain available for
  denser topics and accessibility needs. Changing pacing invalidates storyboard and downstream
  review.
- Content uses a conservative, resolution-independent shared TikTok/Reels safe zone. Default
  insets are top `0.06`, right `0.14`, bottom `0.17`, and left `0.067` of frame dimensions.
- Captions are readable on their first frame, use a short bounded entrance, and show cue progress
  without word-by-word flicker.

Configure these project-level controls before storyboard review:

```powershell
.\.venv\Scripts\techshort.exe style pacing <slug> high-retention
.\.venv\Scripts\techshort.exe style safe-zone <slug> --top 0.06 --right 0.14 --bottom 0.17 --left 0.067
```

The values are stored in `project.json`, validated independently in Python and TypeScript, and
included in review dependency hashes. Changing either setting makes visual approvals and renders
stale.

## Honest hooks and provider-neutral constraints

An approved hook may show a result before explaining it, state a mechanism before a
demonstration, or ask a bounded question. It must identify the real subject, cite approved claims
when factual, and promise only a payoff the evidence supports.

Script generation persists a narrative brief, beat plan, retention plan, editorial critique, and
retention critique for fixture, manual, and Codex-provider output. Fixture artifacts use
topic-specific direction; manual and Codex results receive the same deterministic provider-neutral
constraints after their strict JSON is imported. These artifacts organize approved evidence but
are not proof and do not grant human approval.

Before generic storyboard generation, the current brief, beat plan, retention plan, and critique
are revalidated. Manual and Codex prompt packets receive only an inert schedule of beat timing,
allowlisted visual devices, event kinds, and claim/evidence IDs. Free-form purpose text and sound
cues are removed, and stale or blocking planning state stops the prompt from being created.

The retention schema and critique reject deceptive withholding, false urgency, proof
overclaiming, unsupported engagement claims, unresolved curiosity threads, and engagement bait
such as "wait until the end." Re-hooks must advance the mechanism, reveal evidence, correct a
misconception, or change a comparison--not merely demand continued attention.

## Deterministic rendering

Only current, validated retention-plan data reaches Remotion. Event times are scaled to the
actual narration-driven render duration and bound to exact output frames. Each event produces one
short, safe-zone-contained geometric pulse for an allowlisted device; it cannot inject text,
HTML, code, paths, sound, or arbitrary assets. Missing, partial, stale, or mismatched declared
retention chains fail before rendering. Older projects with no declared retention chain can still
render without synthetic event claims, but QA reports the missing explicit schedule.

Pacing profiles control deterministic transition duration, micro-beat frequency, and restrained
decorative movement. Scene cuts remain visually populated; the renderer does not fade through an
empty background. Event overlays last 0.72 seconds with smooth 0.30-second ramps and never use a
strobe.

## Deterministic engagement QA

Creative QA reports measurable proxies for:

- cold-open duration and time to the first declared visual event;
- visual-beat cadence and static/dead-air stretches;
- explicit re-hook, evidence-payoff, limitation, and final-payoff placement;
- hook integrity and factual provenance;
- caption timing, reading speed, line length, overlap, and gaps;
- sustained motion intensity and declared or inferred flashing risk;
- density, duplication, layout diversity, contrast, citations, cover structure, contact sheets,
  and per-scene representative stills.

The aggregate creative-quality score is advisory. Provenance, approvals, the meaningful
limitation, rights, dependency freshness, safe-zone geometry, caption-timing accessibility,
motion/flashing safety, and media integrity remain export gates. A high deterministic score is
not evidence that a video will perform well with a real audience.

The flash check analyzes declared and inferred motion cues and blocks rates over three per second.
It is not a full rendered-pixel luminance-and-area analysis. Final reviewers must watch the exact
preview and inspect the contact sheet and scene stills before approval; authors should remain
below the W3C three-flashes-per-second threshold.

## Sound, accessibility, and rights

User-recorded narration remains supported, and Windows users may explicitly synthesize the
current approved script with an installed System.Speech voice. Narration is required unless the
reviewer selects `silent-reviewed`; silence is never an automatic fallback. Synthetic voice
rights default to `unknown` and block export until reviewed. Retention events may carry an
allowlisted sound-design suggestion such as `source-click`; it remains inert until a human runs
`audio sound-design`. That command generates a bounded original procedural track without samples,
then invalidates rights and downstream review. The renderer never turns arbitrary text into audio.

Any narration, music, or effect actually embedded in an export needs an asset record, embedding
permission, and rights approval. Adding a sound later also invalidates downstream captions,
preview, QA, and final review. Caption and motion checks are accessibility aids, not substitutes
for a human accessibility review of the final pixels and audio.

## Platform basis and iteration

The defaults follow current platform guidance without pretending there is one guaranteed viral
formula:

- TikTok's [Creative Starter Pack](https://ads.tiktok.com/business/library/AUNZ_Creative_Starter_Pack_TakeItToTikTok.pdf)
  emphasizes an early hook, 9:16 high-resolution video, attention triggers, sound, and a clear
  hook/body/close.
- TikTok's [Creative Codes](https://ads.tiktok.com/business/library/Creative_Codes_ENG.pdf)
  recommends early value, movement, text, transitions, and scene changes while describing its
  sample structure as guidance rather than a prescription.
- Meta's [Reels guidance](https://www.facebook.com/business/ads/facebook-instagram-reels-ads)
  emphasizes vertical video, quality audio, and key messages inside safe zones.
- W3C explains the [three-flashes-or-below threshold](https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold.html)
  and [prerecorded caption requirement](https://www.w3.org/WAI/WCAG22/Understanding/captions-prerecorded).

Actual success must be learned from real published-video observations. techshort neither publishes
automatically nor calls platform analytics APIs. Its current experiment integration compares two
or three approved covers around one identical approved MP4. It prepares immutable local packages
with explicit consent, after which a human posts each variant in the platform's own composer.

The operator may then import actual cumulative post-level totals--never fabricated metrics or
viewer-level rows--at comparable post ages. Analysis enforces minimum views and window tolerance.
Completion and skip proportions receive conservative Wilson intervals; views, average watch time,
and engagement totals remain descriptive because aggregate imports do not provide defensible
variance or independent-event assumptions. These intervals cover modeled sampling error only.
Organic distribution, posting time, account state, audience mix, competition, and outside events
remain confounders, so a leading result is not a causal claim or a promise of future performance.

Analysis writes a recommendation but changes nothing. A human must approve a conclusive result and
then separately apply it. Application is currently limited to the selected cover and uses normal
storyboard, rights, and final-gate invalidation. See [local organic experiments](EXPERIMENTS.md).
