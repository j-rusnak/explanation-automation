# Local organic experiments

techshort provides a zero-cost, human-operated loop for comparing approved cover treatments. It
renders immutable variants, prepares local upload packages, imports real aggregate observations,
and produces a conservative recommendation. It does not open a browser, authenticate with a
platform, upload a video, publish a post, purchase traffic, or call an analytics API.

The current production integration changes only the selected cover. Every variant shares the
same approved MP4, evidence, claims, limitation, script, rights state, and factual lock. A cover
experiment is therefore a presentation test, not permission to change factual content.

## 1. Create and approve variants

A cover experiment requires a current approved export, current exported SRT/VTT captions, and two
or three reviewed cover candidates. By default, the currently selected cover is the control and
the other reviewed candidates are treatments.

```powershell
.\.venv\Scripts\techshort.exe experiment create-cover <slug> `
  --name "cover-test-01" `
  --hypothesis "A mechanism-first cover may improve completion rate." `
  --platform tiktok `
  --primary-metric completion-rate `
  --minimum-views 500 `
  --json
.\.venv\Scripts\techshort.exe experiment list <slug> --json
.\.venv\Scripts\techshort.exe experiment approve <slug> <experiment-id> --reviewer local-reviewer
.\.venv\Scripts\techshort.exe experiment status <slug> <experiment-id> --json
```

Use `--candidate <candidate-id>` two or three times to test a subset. Inspect every rendered cover
before approval. Approval hashes the exact experiment, variants, shared media, covers, factual
artifacts, evidence, claims, limitation, and rights state. Decisions are append-only. Changed or
missing variant bytes block status, analysis, recommendation approval, and application.

## 2. Build packages for manual posting

Diagnostics report local packaging capability only. The `official` diagnostic is not a posting
integration and does not read credentials.

```powershell
.\.venv\Scripts\techshort.exe publication diagnostics tiktok --provider manual --json
.\.venv\Scripts\techshort.exe publication diagnostics instagram-reels --provider manual --json
```

For each approved variant, prepare reviewed copy and an accessible description, then build a
pending immutable package:

```powershell
.\.venv\Scripts\techshort.exe publication prepare-request <slug> <experiment-id> <variant-id> `
  --post-copy "<reviewed post copy without hashtags>" `
  --alt-text "<accessible description>" `
  --hashtag CameraTech `
  --json
.\.venv\Scripts\techshort.exe publication package <slug> <request-json-path> --json
```

Inspect the video, cover, captions, metadata, checksums, checklist, and pending consent receipt.
Granting consent creates another immutable package; it does not upload the package:

```powershell
.\.venv\Scripts\techshort.exe publication consent-package <slug> `
  <request-json-path> <pending-package-manifest-path> `
  --state granted `
  --reviewer local-reviewer `
  --confirmation "I explicitly authorize manual publication of this exact variant package." `
  --json
```

Consent applies only to the exact hash-bound package. A changed file requires a new request and
consent. The operator then uploads the granted package manually in TikTok's or Instagram's own
composer. Account sessions, captions entered on-platform, publication timing, and platform terms
remain the operator's responsibility.

## 3. Record real aggregate observations

Wait until each post reaches a comparable age, then copy actual aggregate totals from the
platform. Do not invent missing numbers, estimate unavailable metrics, scrape viewer lists, or
enter one row per viewer. The importer rejects unknown and person-level fields such as viewer or
user IDs, usernames, handles, email addresses, phone numbers, IP addresses, and device IDs.

Generate blank rows for the current approved variant IDs instead of retyping the schema:

```powershell
.\.venv\Scripts\techshort.exe experiment metrics-template <slug> <experiment-id> --format json --output actual-observations.json
```

The safe output filename is written below the experiment's `templates/` directory. Replace every
`REQUIRED_` placeholder with an actual content-level reference or timestamp, enter actual counts,
and leave genuinely unavailable optional metrics empty. Do not import the untouched template.

JSON may contain one object or a list. CSV may contain up to 100 rows; imports are capped at 256
KiB. The CLI derives and verifies the stable snapshot ID. Each row uses:

- `experiment_id`, `variant_id`, and `platform` (`tiktok` or `instagram-reels`);
- `publication_reference`, a content-level post reference with no account or viewer identity;
- timezone-aware `window_started_at`, `window_ended_at`, and `captured_at` timestamps;
- actual nonnegative `view_count`;
- optional `total_watch_time_seconds`, `completed_view_count`, `skipped_view_count`,
  `like_count`, `comment_count`, `share_count`, `save_count`, and `follow_count`.

If the platform does not expose the numerator required by the chosen primary metric, leave it
empty. Analysis will report insufficient data; do not derive or estimate it from an unrelated
platform display.

Snapshots for one variant must refer to the same post and start time. Later cumulative snapshots
cannot decrease previously reported totals. Completion and skip counts cannot exceed views.

```powershell
.\.venv\Scripts\techshort.exe experiment import-observations <slug> <experiment-id> <completed-template-path> --format json --json
.\.venv\Scripts\techshort.exe experiment status <slug> <experiment-id> --json
```

Importing new observations marks prior recommendations stale. Never edit IDs, hashes, or stored
recommendations to bypass that invalidation.

## 4. Analyze, approve, and apply

```powershell
.\.venv\Scripts\techshort.exe experiment analyze <slug> <experiment-id> --json
.\.venv\Scripts\techshort.exe experiment approve-recommendation <slug> <experiment-id> <recommendation-id> --reviewer local-reviewer --json
.\.venv\Scripts\techshort.exe experiment apply-recommendation <slug> <experiment-id> <recommendation-id> --reviewer local-reviewer --json
```

`analyze` reads the latest cumulative snapshot for each variant but changes nothing. A comparison
requires the configured minimum views and observation-window durations within the experiment's
tolerance. Completion-rate and skip-rate comparisons use conservative Wilson intervals. A
treatment leads only when its interval clears the control interval in the correct direction.
With several treatments, the recommendation remains conservative unless one reviewed result is
unambiguous under every required comparison.

Views, average watch time, likes, comments, shares, saves, and follows remain useful descriptive
aggregates, but these imports do not contain the variance or independent-event assumptions needed
for a defensible confidence interval. When such a metric is primary, analysis records aggregate
uncertainty instead of manufacturing a winner.

Wilson intervals address sampling error under their proportion model only. Organic posts are not
randomized: platform distribution, post timing, audience composition, competition, account state,
and external events may differ. A leading result is therefore observational evidence, not proof
that a cover caused the difference or that it will generalize.

An inconclusive `collect-more-data` result cannot be approved. Approval of a conclusive
recommendation still does not mutate production. `apply-recommendation` is a separate human
action. Selecting a different cover follows the normal invalidation path and makes storyboard,
rights, and final review stale; keeping the control changes no gate. Every application writes an
append-only receipt.

## Local storage

Experiment data remains under the project and is excluded from Git:

```text
projects/<slug>/experiments/<experiment-id>/
  experiment.json
  observations.json
  recommendations.json
  reviews.json
  applications.json
  variants/
  templates/
  publication-requests/
  publication/<variant-id>/<platform>/<package-id>/
```

Manifests are strict, versioned, hash-bound, and atomically written. Publication packages contain
only the selected export media, cover, caption sidecars, reviewed metadata, checklist, and consent
receipt. They do not contain credentials, browser state, viewer data, or an instruction to post
automatically.
