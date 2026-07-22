# Local organic experiments

techshort provides a zero-cost, human-operated loop for comparing approved cover treatments. It
renders immutable variants, prepares local upload packages, imports real aggregate observations,
and produces a conservative recommendation. Package preparation remains local and
side-effect-free. An optional, separately consented integration can transfer one exact package to
TikTok's inbox as a draft through the official Content Posting API. techshort never directly
publishes or schedules a post, opens an automated browser, reuses cookies or sessions, purchases
traffic, or calls a platform analytics API.

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

## 2. Build immutable publication packages

These diagnostics report local package-building capability only and do not read credentials.
The separate `upload-diagnostics` command below reports whether the two TikTok environment
variables are present without displaying their values.

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
consent. The operator may upload the granted package manually in TikTok's or Instagram's own
composer. Account sessions, captions entered on-platform, publication timing, and platform terms
remain the operator's responsibility.

### Optional official TikTok draft transfer

TikTok packages have one additional path: transfer the reviewed MP4 to the identified account's
TikTok inbox as a draft. This uses TikTok's official Upload API and requires an operator-created
TikTok developer app, OAuth authorization for the intended account, and the `video.upload` scope.
It does not use Direct Post or `video.publish`, publish publicly, choose visibility, schedule a
post, or automate TikTok's browser interface. Review the current official
[Upload API reference](https://developers.tiktok.com/doc/content-posting-api-reference-upload-video/)
and [content-sharing guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines/)
before enabling it.

Provide the OAuth access token and OpenID from the same token response, and only in the current
process environment. Do not put
actual values in `.env.example`, a project manifest, a package, a command transcript, or Git:

```powershell
$env:TECHSHORT_TIKTOK_ACCESS_TOKEN = '<OAuth access token>'
$env:TECHSHORT_TIKTOK_OPEN_ID = '<OAuth OpenID for the intended account>'
```

Diagnostics are secret-safe. Preflight is local and makes no network request; it validates the
current immutable package, final export, experiment, variant, evidence, claims, limitation,
rights, media, captions, and credential availability:

```powershell
.\.venv\Scripts\techshort.exe publication upload-diagnostics --json
.\.venv\Scripts\techshort.exe publication upload-preflight <slug> <granted-package-manifest-path> `
  --account-label "<recognizable TikTok account>" `
  --reviewer local-reviewer `
  --json
```

API transfer requires a second human consent distinct from package consent. It binds the exact
package and video hashes to the SHA-256 of the OAuth account subject. The confirmation must match
exactly; `--execute` is also mandatory because this command crosses the network boundary:

```powershell
.\.venv\Scripts\techshort.exe publication upload-draft <slug> <granted-package-manifest-path> `
  --account-label "<recognizable TikTok account>" `
  --reviewer local-reviewer `
  --confirmation "I explicitly authorize transfer of this exact package to the identified TikTok account as a draft." `
  --execute `
  --json
```

The command persists the intent, consent, preflight, attempt, and initial status receipt before
network transfer. It then appends provider-status receipts; it never rewrites or silently removes
an earlier decision. Poll only a known nonterminal attempt:

```powershell
.\.venv\Scripts\techshort.exe publication upload-status <slug> <experiment-id> <intent-id> `
  --network `
  --json
```

Do not repeat `upload-draft` after a timeout, disconnect, malformed response, or other ambiguous
outcome. techshort records that outcome as `ambiguous` and will not re-upload it automatically.
If the receipt contains a publish ID, `upload-status` may resolve the existing attempt without
sending the video again. Otherwise inspect the intended TikTok account first; if a genuinely new
transfer is needed, prepare and approve a new immutable package, intent, and consent.

Only the MP4 is transferred. Burned-in captions remain in that MP4, but the separate reviewed
cover PNG, SRT/VTT sidecars, post copy, hashtags, alt text, and checklist remain local. TikTok's
draft API cannot attach the separate cover file, so the operator must select that reviewed cover,
finish the post metadata, inspect the draft, and publish it inside TikTok. A successful transfer or
status receipt is not evidence that the post was published.
This conservative V1 uploads one MP4 chunk no larger than 64,000,000 bytes. Use the manual package
workflow for a larger reviewed video.

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
  uploads/<tiktok-intent-id>/
    intent.json
    consent.json
    preflight.json
    attempt.json
    video.mp4
    receipts/
```

Manifests are strict, versioned, hash-bound, and atomically written. Publication packages contain
only the selected export media, cover, caption sidecars, reviewed metadata, checklist, and consent
receipt. Upload records contain account-subject hashes, inert labels, immutable package/video
bindings, and append-only status receipts--never tokens, browser state, cookies, viewer data, or
an instruction to publish automatically. Normal tests use fake transports and stay offline; this
documentation does not imply that a live TikTok upload has been run.
