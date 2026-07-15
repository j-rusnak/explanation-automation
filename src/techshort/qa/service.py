from __future__ import annotations

import json
import math
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from techshort.alignment import (
    as_srt,
    as_vtt,
    caption_warnings,
    compare_narration,
    cues_from_script,
)
from techshort.assets import BUILTIN_FONT_ASSET_IDS
from techshort.audio import active_audio, probe_duration, resolve_narration_transcript
from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    AngleSelection,
    AnglesManifest,
    AssetManifest,
    ClaimsManifest,
    EvidenceManifest,
    QACheck,
    QAReport,
    RenderManifest,
    ReviewStatus,
    ScriptManifest,
    SourceIndex,
    StoryboardManifest,
    derive_angle_selection_id,
    derive_angles_version_id,
    derive_script_version_id,
)
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.evidence import unsupported_assertion_tokens
from techshort.ingestion import resolve_evidence_text, verify_source_integrity
from techshort.rendering.tools import media_tool
from techshort.review import (
    current_artifact_hashes,
    has_current_approval,
    scene_dependency_hash,
)

PREVIEW_WIDTH = 360
PREVIEW_HEIGHT = 640
CAPTION_BOTTOM_INSET = 145
CAPTION_MIN_HEIGHT = 170
FULL_HEIGHT = 1920
MIN_TEXT_CONTRAST = 4.5
DEFAULT_THEME_COLORS = {
    "background": "#071124",
    "panel": "#13213d",
    "text": "#f7f9ff",
    "muted": "#b7c4e2",
    "accent": "#5eead4",
    "warning": "#ffd166",
    "danger": "#ff6b6b",
    "citation": "#a8b7ff",
}
DEFAULT_GRADIENT_HIGHLIGHT = "#183866"


def _check(
    check_id: str,
    passed: bool,
    success: str,
    failure: str,
    *,
    hard: bool = True,
) -> QACheck:
    return QACheck(
        check_id=check_id,
        status="pass" if passed else "failure",
        message=success if passed else failure,
        hard_blocker=hard and not passed,
    )


def _warning(check_id: str, message: str) -> QACheck:
    return QACheck(check_id=check_id, status="warning", message=message, hard_blocker=False)


def _approval_is_current(store: ProjectStore, object_type: str, object_id: str) -> bool:
    try:
        return has_current_approval(store, object_type, object_id)
    except (OSError, ValueError):
        return False


def _claim_support_texts(
    claim_id: str,
    claims_by_id: dict[str, Any],
    evidence_by_id: dict[str, Any],
) -> list[str]:
    claim = claims_by_id.get(claim_id)
    if claim is None:
        return []
    rows = [claim.text]
    rows.extend(
        value for value in (claim.reasoning, claim.scope, claim.limitation) if value is not None
    )
    rows.extend(
        evidence_by_id[evidence_id].excerpt
        for evidence_id in claim.evidence_span_ids
        if evidence_id in evidence_by_id
    )
    return rows


def _scene_assertion_text(scene: Any) -> str:
    visual = scene.visual
    rows = [
        scene.on_screen_text,
        scene.accessibility_description,
        visual.title,
        visual.body,
        visual.left,
        visual.right,
        *visual.labels,
        *(node.label for node in visual.nodes),
        *(edge.label for edge in visual.edges),
    ]
    if scene.primitive == "ChartReveal":
        rows.extend(format(value, "g") for value in visual.series)
    return " ".join(value for value in rows if value is not None)


def _storyboard_provenance_valid(
    storyboard: StoryboardManifest,
    claims_by_id: dict[str, Any],
    evidence_by_id: dict[str, Any],
) -> bool:
    for scene in storyboard.scenes:
        scene_claims = [claims_by_id.get(claim_id) for claim_id in scene.claim_ids]
        if not scene.claim_ids or any(claim is None for claim in scene_claims):
            return False
        if scene.visual.citation is not None and scene.visual.citation not in scene.claim_ids:
            return False
        expected_labels = {claim.evidence_label.upper() for claim in scene_claims if claim}
        expected_label = "INFERRED" if "INFERRED" in expected_labels else None
        if scene.evidence_label is None:
            return False
        if expected_label is not None:
            if scene.evidence_label != expected_label:
                return False
        elif scene.evidence_label not in expected_labels:
            return False
        support = [
            item
            for claim_id in scene.claim_ids
            for item in _claim_support_texts(claim_id, claims_by_id, evidence_by_id)
        ]
        if unsupported_assertion_tokens(_scene_assertion_text(scene), support):
            return False
        if scene.primitive == "SourceReceipt":
            evidence_id = scene.visual.evidence_id
            if evidence_id is None or evidence_id not in evidence_by_id:
                return False
            allowed_evidence = {
                item
                for claim in scene_claims
                if claim is not None
                for item in claim.evidence_span_ids
            }
            if evidence_id not in allowed_evidence:
                return False
    return True


def _write_report(
    store: ProjectStore,
    checks: list[QACheck],
    artifact_hashes: dict[str, str],
    media_path: Path | None,
    destination: str,
) -> QAReport:
    blockers = [item.message for item in checks if item.status == "failure" and item.hard_blocker]
    report = QAReport(
        project_id=store.project().project_id,
        checks=checks,
        export_blockers=blockers,
        artifact_hashes=artifact_hashes,
        media_path=(media_path.relative_to(store.root).as_posix() if media_path else None),
        media_hash=(sha256_file(media_path) if media_path and media_path.is_file() else None),
    )
    atomic_write_model(store.path(destination), report)
    return report


def run_qa(
    store: ProjectStore,
    media_path: Path | None = None,
    *,
    require_media: bool = True,
    destination: str | None = None,
) -> QAReport:
    """Run deterministic provenance, rights, caption, and media checks.

    Preview and final reports are written separately. A report without an exact
    media hash can be useful during authoring, but can never satisfy final review.
    """

    checks: list[QACheck] = []
    is_preview = media_path is None or "previews" in media_path.parts
    destination = destination or (
        "renders/previews/qa-report.json" if is_preview else "renders/final/qa-report.json"
    )
    if media_path is not None:
        try:
            media_path.resolve().relative_to(store.root.resolve())
        except ValueError:
            checks.append(
                _check(
                    "renderer-failure",
                    False,
                    "Rendered media stays inside the project",
                    "QA refuses media outside the active project",
                )
            )
            return _write_report(store, checks, {}, None, destination)
    try:
        sources = load_model(store.path("sources/source-index.json"), SourceIndex)
        evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
        claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
        angles = load_model(store.path("script/angles.json"), AnglesManifest)
        selection = load_model(store.path("script/angle-selection.json"), AngleSelection)
        script = load_model(store.path("script/script.json"), ScriptManifest)
        storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
        assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    except (OSError, ValueError) as exc:
        checks.append(
            _check(
                "manifest-validation",
                False,
                "All required manifests are schema-valid",
                f"Required manifest is missing or invalid: {exc}",
            )
        )
        return _write_report(store, checks, {}, media_path, destination)

    artifact_hashes: dict[str, str] = {}
    try:
        artifact_hashes = current_artifact_hashes(store)
        checks.append(
            _check(
                "manifest-validation",
                True,
                "All required manifests and active source bytes are schema-valid",
                "Required artifact is missing or invalid",
            )
        )
    except (OSError, ValueError) as exc:
        checks.append(
            _check(
                "manifest-validation",
                False,
                "All required manifests and active source bytes are schema-valid",
                f"Required artifact is missing, stale, or invalid: {exc}",
            )
        )

    source_by_id = {source.source_id: source for source in sources.sources}
    evidence_by_id = {span.evidence_id: span for span in evidence.evidence}
    evidence_valid = bool(evidence.evidence)
    for span in evidence.evidence:
        document = source_by_id.get(span.source_id)
        if document is None or span.source_hash != document.content_hash:
            evidence_valid = False
            continue
        try:
            verify_source_integrity(store, document)
            actual = resolve_evidence_text(
                store,
                span.source_id,
                span.char_start,
                span.char_end,
                expected_source_hash=span.source_hash,
                expected_extracted_hash=document.extracted_text_hash,
            )
            evidence_valid = evidence_valid and actual == span.excerpt
        except (OSError, ValueError):
            evidence_valid = False
    claims_have_evidence = bool(claims.claims) and all(
        claim.evidence_span_ids and set(claim.evidence_span_ids).issubset(evidence_by_id)
        for claim in claims.claims
    )
    checks.append(
        _check(
            "evidence-completeness",
            evidence_valid and claims_have_evidence,
            "Every claim has exact evidence that resolves in unchanged source bytes",
            "Evidence is missing, fabricated, stale, or no longer resolves exactly",
        )
    )

    claims_by_id = {claim.claim_id: claim for claim in claims.claims}
    claims_assertions_valid = True
    for claim in claims.claims:
        support = [
            evidence_by_id[evidence_id].excerpt
            for evidence_id in claim.evidence_span_ids
            if evidence_id in evidence_by_id
        ]
        claim_text = " ".join(
            value
            for value in (claim.text, claim.reasoning, claim.scope, claim.limitation)
            if value is not None
        )
        claims_assertions_valid = claims_assertions_valid and not unsupported_assertion_tokens(
            claim_text, support
        )
    script_assertions_valid = True
    for segment in script.segments:
        support = [
            item
            for claim_id in segment.claim_ids
            for item in _claim_support_texts(claim_id, claims_by_id, evidence_by_id)
        ]
        script_assertions_valid = script_assertions_valid and not unsupported_assertion_tokens(
            segment.text, support
        )
    storyboard_assertions_valid = _storyboard_provenance_valid(
        storyboard, claims_by_id, evidence_by_id
    )
    checks.append(
        _check(
            "assertion-provenance",
            claims_assertions_valid and script_assertions_valid and storyboard_assertions_valid,
            "Concrete numbers, units, citations, labels, and source receipts resolve to approved evidence",
            "A claim, script segment, or scene contains an unsupported number, unit, citation, label, or source receipt",
        )
    )

    project = store.project()
    approved_claim_ids = {
        claim.claim_id
        for claim in claims.claims
        if claim.review_status == ReviewStatus.APPROVED
        and _approval_is_current(store, "claim", claim.claim_id)
    }
    selected_candidate = next(
        (
            candidate
            for candidate in angles.candidates
            if candidate.angle == selection.selected_angle
        ),
        None,
    )
    angle_claims_valid = all(
        set(candidate.central_claim_ids).issubset(approved_claim_ids)
        for candidate in angles.candidates
    )
    script_claim_ids = {claim_id for segment in script.segments for claim_id in segment.claim_ids}
    selected_central_claims_present = selected_candidate is not None and set(
        selected_candidate.central_claim_ids
    ).issubset(script_claim_ids)
    version_chain_valid = (
        claims.evidence_version_id == evidence.version_id
        and angles.claims_version_id == claims.version_id
        and angles.version_id == derive_angles_version_id(claims.version_id, angles.candidates)
        and selection.angles_version_id == angles.version_id
        and selection.selection_id
        == derive_angle_selection_id(
            angles.version_id,
            selection.selected_angle,
            selection.selected_candidate_hash,
        )
        and script.angles_version_id == angles.version_id
        and script.angle_selection_id == selection.selection_id
        and script.angle == selection.selected_angle
        and script.version_id
        == derive_script_version_id(
            script.claims_version_id,
            script.angles_version_id,
            script.angle_selection_id,
            script.angle,
            script.segments,
        )
        and any(
            candidate.angle == selection.selected_angle
            and stable_hash(candidate) == selection.selected_candidate_hash
            for candidate in angles.candidates
        )
        and angle_claims_valid
        and selected_central_claims_present
        and script.claims_version_id == claims.version_id
        and storyboard.script_version_id == script.version_id
        and project.active_versions.get("evidence") == evidence.version_id
        and project.active_versions.get("claims") == claims.version_id
        and project.active_versions.get("angles") == angles.version_id
        and project.active_versions.get("angle_selection") == selection.selection_id
        and project.active_versions.get("script") == script.version_id
        and project.active_versions.get("storyboard") == storyboard.version_id
        and project.active_versions.get("assets") == assets.version_id
    )
    try:
        scene_dependencies_valid = all(
            scene.dependency_hash == scene_dependency_hash(scene, script)
            for scene in storyboard.scenes
        )
    except ValueError:
        scene_dependencies_valid = False
    checks.append(
        _check(
            "dependency-chain",
            version_chain_valid and scene_dependencies_valid,
            "Artifact versions and scene dependencies form one current chain",
            "An artifact version or scene dependency points to stale upstream state",
        )
    )

    segments_current = all(
        segment.review_status == ReviewStatus.APPROVED
        and _approval_is_current(store, "script-segment", segment.segment_id)
        and bool(segment.claim_ids)
        and set(segment.claim_ids).issubset(approved_claim_ids)
        for segment in script.segments
    )
    scenes_current = all(
        scene.review_status == ReviewStatus.APPROVED
        and _approval_is_current(store, "scene", scene.scene_id)
        for scene in storyboard.scenes
    )
    assets_current = all(
        asset.review_status == ReviewStatus.APPROVED
        and _approval_is_current(store, "asset-rights", asset.asset_id)
        for asset in assets.assets
    )
    gates_current = all(
        getattr(project.approvals, gate) == ReviewStatus.APPROVED
        for gate in ("claims", "script", "storyboard", "rights")
    )
    approvals_valid = (
        len(approved_claim_ids) == len(claims.claims)
        and segments_current
        and scenes_current
        and assets_current
        and _approval_is_current(store, "rights", assets.version_id)
        and gates_current
    )
    checks.append(
        _check(
            "approval-validity",
            approvals_valid,
            "All claim, script, storyboard, and rights approvals match exact current hashes",
            "An approval is missing, rejected, edited, stale, or hash-mismatched",
        )
    )

    limitation_segments = [
        segment
        for segment in script.segments
        if segment.segment_type == "limitation"
        and len(segment.text.split()) >= 8
        and segment.claim_ids
        and set(segment.claim_ids).issubset(approved_claim_ids)
    ]
    checks.append(
        _check(
            "required-limitation",
            bool(limitation_segments),
            "A meaningful evidence-linked limitation is present",
            "A meaningful evidence-linked limitation is required",
        )
    )

    scene_ids = {scene.scene_id for scene in storyboard.scenes}
    asset_ids = {asset.asset_id for asset in assets.assets}
    referenced_asset_ids = {asset_id for scene in storyboard.scenes for asset_id in scene.asset_ids}
    rights_valid = bool(BUILTIN_FONT_ASSET_IDS.issubset(asset_ids))
    for asset in assets.assets:
        path = store.path(asset.local_path)
        rights_valid = rights_valid and (
            asset.rights_status in {"original", "user-owned", "permissively-licensed"}
            and asset.embedding_allowed
            and asset.review_status == ReviewStatus.APPROVED
            and path.is_file()
            and sha256_file(path) == asset.sha256
            and set(asset.scene_usage).issubset(scene_ids)
        )
    rights_valid = rights_valid and referenced_asset_ids.issubset(asset_ids)
    checks.append(
        _check(
            "rights-completeness",
            rights_valid,
            "Every embedded asset, narration, and renderer font has approved reusable rights",
            "An embedded asset is missing, modified, unapproved, unknown, restricted, or citation-only",
        )
    )

    stale = bool(
        set(project.stale_artifacts).intersection(
            {
                "claims",
                "claims_critique",
                "angles",
                "angle_selection",
                "script",
                "storyboard",
                "rights",
            }
        )
    ) or any(
        getattr(project.approvals, gate) == ReviewStatus.STALE
        for gate in ("claims", "script", "storyboard", "rights")
    )
    checks.append(
        _check(
            "stale-dependencies",
            not stale,
            "No approved upstream dependency is stale",
            "An upstream change invalidated approved downstream work",
        )
    )

    segment_by_id = {segment.segment_id: segment for segment in script.segments}
    citation_valid = True
    for scene in storyboard.scenes:
        linked = [segment_by_id[item] for item in scene.script_segment_ids if item in segment_by_id]
        implied_claims = {claim_id for segment in linked for claim_id in segment.claim_ids}
        citation_valid = citation_valid and bool(linked) and bool(implied_claims)
        citation_valid = citation_valid and set(scene.claim_ids) == implied_claims
        citation_valid = citation_valid and set(scene.claim_ids).issubset(approved_claim_ids)
    checks.append(
        _check(
            "missing-citations",
            citation_valid,
            "Every narration segment and scene carries approved claim IDs",
            "A narration segment or scene is missing its approved claim citation",
        )
    )

    ordered_scenes = sorted(storyboard.scenes, key=lambda scene: scene.order)
    timeline_valid = bool(ordered_scenes) and [scene.order for scene in ordered_scenes] == list(
        range(len(ordered_scenes))
    )
    previous_end = 0.0
    for scene in ordered_scenes:
        timeline_valid = timeline_valid and scene.start_time + 0.01 >= previous_end
        previous_end = max(previous_end, scene.start_time + scene.duration)
    storyboard_duration = max(
        (scene.start_time + scene.duration for scene in storyboard.scenes), default=0.0
    )
    checks.append(
        _check(
            "timeline-structure",
            timeline_valid,
            "Scene order and timing are monotonic and non-overlapping",
            "Storyboard scene order or timing overlaps unexpectedly",
        )
    )

    narration: Path | None = None
    narration_duration: float | None = None
    try:
        narration = active_audio(store)
        narration_duration = probe_duration(narration) if narration else None
    except (OSError, ValueError):
        narration = None
        narration_duration = None
        if "audio_asset" in project.active_versions:
            checks.append(
                _check(
                    "audio-validity",
                    False,
                    "Imported narration is valid",
                    "The active narration asset is missing, stale, or invalid",
                )
            )
    if narration:
        checks.append(
            _check(
                "audio-validity",
                narration_duration is not None and narration_duration > 0,
                f"Imported narration is valid ({narration_duration:.1f}s)"
                if narration_duration
                else "Imported narration is valid",
                "Imported narration duration could not be verified",
            )
        )
        try:
            transcript = resolve_narration_transcript(store, narration)
            if transcript.text is None:
                checks.append(
                    _warning(
                        "narration-script-comparison",
                        "Narration was not transcribed locally "
                        f"({transcript.unavailable_reason}); compare it with the approved "
                        "script during final review",
                    )
                )
            else:
                script_text = " ".join(segment.text for segment in script.segments)
                comparison = compare_narration(script_text, transcript.text)
                transcript_hash = stable_hash(transcript.text)[:12]
                message = (
                    f"Narration from {transcript.source or 'local transcript'} has "
                    f"{comparison.word_error_rate:.1%} word error versus the approved script "
                    f"({comparison.transcript_word_count} transcript / "
                    f"{comparison.script_word_count} script words; transcript "
                    f"{transcript_hash})"
                )
                checks.append(
                    QACheck(
                        check_id="narration-script-comparison",
                        status=comparison.status,
                        message=message,
                        hard_blocker=comparison.status == "failure",
                    )
                )
        except (OSError, ValueError) as exc:
            checks.append(
                _check(
                    "narration-script-comparison",
                    False,
                    "Narration matches the approved script",
                    f"Narration transcript could not be validated: {exc}",
                )
            )

    expected_duration = narration_duration or storyboard_duration
    duration_valid = 45 <= expected_duration <= 75
    checks.append(
        _check(
            "duration",
            duration_valid,
            f"Target duration is {expected_duration:.1f}s",
            f"Duration {expected_duration:.1f}s is outside the required 45-75s range",
        )
    )

    cues = cues_from_script(script, target_duration=narration_duration)
    caption_issues = caption_warnings(cues)
    srt_path = store.path("captions/captions.srt")
    vtt_path = store.path("captions/captions.vtt")
    caption_files_match = (
        srt_path.is_file()
        and vtt_path.is_file()
        and srt_path.read_text(encoding="utf-8") == as_srt(cues)
        and vtt_path.read_text(encoding="utf-8") == as_vtt(cues)
    )
    checks.append(
        _check(
            "caption-integrity",
            caption_files_match,
            "SRT, VTT, and burned-caption cues share deterministic timing and text",
            "Caption sidecars are missing or differ from the current approved script/audio timing",
        )
    )
    checks.append(
        QACheck(
            check_id="caption-overflow",
            status="warning" if caption_issues else "pass",
            message="; ".join(caption_issues)
            if caption_issues
            else "Every rendered caption cue fits the 42-character content bound",
            hard_blocker=False,
        )
    )
    inset_ratio = CAPTION_BOTTOM_INSET / FULL_HEIGHT
    caption_height_ratio = CAPTION_MIN_HEIGHT / FULL_HEIGHT
    safe_zone_valid = inset_ratio >= 0.05 and caption_height_ratio <= 0.12 and not caption_issues
    checks.append(
        _check(
            "caption-safe-zone",
            safe_zone_valid,
            "Caption geometry remains inside the configured mobile safe zone",
            "Caption geometry or cue length can leave the configured mobile safe zone",
        )
    )

    word_count = sum(len(segment.text.split()) for segment in script.segments)
    checks.append(
        QACheck(
            check_id="script-word-count",
            status="pass" if 130 <= word_count <= 170 else "warning",
            message=f"Script contains {word_count} spoken words (target 130-170)",
            hard_blocker=False,
        )
    )

    contrast_pairs = _storyboard_text_contrast_pairs(storyboard)
    contrast_results = [
        (label, _contrast_ratio(foreground, background))
        for label, foreground, background in contrast_pairs
    ]
    contrast_failures = [
        f"{label} is {ratio:.1f}:1"
        for label, ratio in contrast_results
        if ratio < MIN_TEXT_CONTRAST
    ]
    minimum_contrast = min((ratio for _, ratio in contrast_results), default=0.0)
    checks.append(
        _check(
            "low-text-contrast",
            not contrast_failures,
            (
                f"All {len(contrast_results)} rendered text/background pairs meet the "
                f"{MIN_TEXT_CONTRAST:.1f}:1 threshold (lowest {minimum_contrast:.1f}:1)"
            ),
            (
                f"Rendered text contrast is below {MIN_TEXT_CONTRAST:.1f}:1: "
                + "; ".join(contrast_failures[:8])
            ),
        )
    )

    if media_path is None:
        checks.append(
            _check(
                "renderer-failure",
                not require_media,
                "Media check was explicitly deferred during authoring",
                "A rendered media file is required for hard QA",
            )
        )
    else:
        checks.extend(
            _media_checks(
                store,
                media_path,
                PREVIEW_WIDTH if is_preview else project.width,
                PREVIEW_HEIGHT if is_preview else project.height,
                project.fps,
                expected_duration,
                narration is not None,
                script,
                storyboard,
                assets,
                sources,
                is_preview,
            )
        )

    return _write_report(store, checks, artifact_hashes, media_path, destination)


def _media_checks(
    store: ProjectStore,
    path: Path,
    width: int,
    height: int,
    fps: int,
    expected_duration: float,
    audio_required: bool,
    script: ScriptManifest,
    storyboard: StoryboardManifest,
    assets: AssetManifest,
    sources: SourceIndex,
    is_preview: bool,
) -> list[QACheck]:
    checks: list[QACheck] = []
    if not path.is_file() or path.stat().st_size == 0:
        return [_check("renderer-failure", False, "", "Rendered video is missing or empty")]
    ffprobe = media_tool("ffprobe")
    if not ffprobe:
        return [
            _check(
                "media-probe",
                False,
                "ffprobe is available",
                "ffprobe is required for hard media QA",
            )
        ]
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        return [_check("renderer-failure", False, "", f"ffprobe failed: {result.stderr.strip()}")]
    try:
        data: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return [_check("media-probe", False, "", f"ffprobe returned invalid JSON: {exc}")]
    raw_streams = data.get("streams")
    streams: list[Any] = raw_streams if isinstance(raw_streams, list) else []
    video = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        {},
    )
    audio = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ),
        None,
    )
    raw_format = data.get("format")
    format_data: dict[str, Any] = raw_format if isinstance(raw_format, dict) else {}
    try:
        actual_duration = float(format_data.get("duration", 0))
    except (TypeError, ValueError):
        actual_duration = 0.0
    try:
        actual_fps = float(Fraction(str(video.get("r_frame_rate", "0/1"))))
    except (ValueError, ZeroDivisionError):
        actual_fps = 0.0
    checks.extend(
        [
            _check(
                "resolution",
                video.get("width") == width and video.get("height") == height,
                f"Resolution is {width}x{height}",
                "Rendered resolution is incorrect",
            ),
            _check(
                "frame-rate",
                math.isclose(actual_fps, fps, abs_tol=0.01),
                f"Frame rate is {actual_fps:.2f} fps",
                f"Rendered frame rate {actual_fps:.2f} does not match {fps} fps",
            ),
            _check(
                "codec",
                video.get("codec_name") == "h264"
                and video.get("pix_fmt") in {"yuv420p", "yuvj420p"},
                "Video is H.264 with a broadly compatible 4:2:0 pixel format",
                "Video codec or pixel format is not the required H.264 4:2:0 output",
            ),
            _check(
                "media-duration",
                abs(actual_duration - expected_duration) < 1.5,
                f"Media duration {actual_duration:.2f}s matches the approved timing",
                f"Media duration {actual_duration:.2f}s differs from approved timing {expected_duration:.2f}s",
            ),
            _check(
                "audio-stream",
                not audio_required or audio is not None,
                "Required narration audio stream is present"
                if audio_required
                else "No narration audio stream is required",
                "Imported narration is missing from the rendered media",
            ),
        ]
    )
    expected_frames = round(actual_duration * fps)
    frame_text = video.get("nb_read_frames") or video.get("nb_frames")
    try:
        actual_frames = int(str(frame_text))
    except (TypeError, ValueError):
        actual_frames = 0
    checks.append(
        _check(
            "missing-frames",
            actual_frames > 0 and abs(actual_frames - expected_frames) <= max(2, fps),
            f"Decoded {actual_frames} frames without a material gap",
            f"Decoded frame count {actual_frames} differs from expected {expected_frames}",
        )
    )

    manifest_path = path.parent / "render-manifest.json"
    manifest_valid = False
    if manifest_path.is_file():
        try:
            manifest = load_model(manifest_path, RenderManifest)
            relative_output = path.relative_to(store.root).as_posix()
            narration = active_audio(store)
            expected_audio_hash = sha256_file(narration) if narration else None
            manifest_valid = (
                manifest.width == width
                and manifest.height == height
                and math.isclose(manifest.fps, fps, abs_tol=0.01)
                and abs(manifest.duration - expected_duration) < 1.5
                and manifest.codec == "h264"
                and manifest.script_hash == stable_hash(script)
                and manifest.storyboard_hash == stable_hash(storyboard)
                and manifest.asset_hashes
                == {asset.asset_id: asset.sha256 for asset in assets.assets}
                and manifest.audio_hash == expected_audio_hash
                and manifest.source_hashes
                == {source.source_id: source.content_hash for source in sources.sources}
                and relative_output in manifest.output_paths
                and manifest.output_hashes.get(relative_output) == sha256_file(path)
                and manifest.watermarked is is_preview
                and manifest.renderer_version not in {"", "pending-lock"}
            )
        except (OSError, ValueError):
            manifest_valid = False
    checks.append(
        _check(
            "render-manifest",
            manifest_valid,
            "Render manifest matches the exact media and approved dependencies",
            "Render manifest is missing, stale, incomplete, or hash-mismatched",
        )
    )

    ffmpeg = media_tool("ffmpeg")
    if not ffmpeg:
        checks.append(
            _check(
                "blank-frames",
                False,
                "Representative frames are nonblank",
                "ffmpeg is required for blank-frame inspection",
            )
        )
        return checks
    frame_samples_ok = _representative_frames_are_nonblank(ffmpeg, path, actual_duration)
    checks.append(
        _check(
            "blank-frames",
            frame_samples_ok,
            "Representative frames contain visible nonblank content",
            "A representative frame is blank or could not be decoded",
        )
    )
    contact_sheet = path.parent / "contact-sheet.png"
    checks.append(
        _check(
            "contact-sheet",
            contact_sheet.is_file() and contact_sheet.stat().st_size > 1000,
            "Representative contact sheet is available for human review",
            "Renderer did not produce a representative contact sheet",
        )
    )
    return checks


def _representative_frames_are_nonblank(ffmpeg: str, path: Path, duration: float) -> bool:
    if duration <= 0:
        return False
    sample_times = [max(0.1, duration * ratio) for ratio in (0.15, 0.5, 0.85)]
    with tempfile.TemporaryDirectory(prefix="techshort-qa-frames-") as directory:
        root = Path(directory)
        for index, timestamp in enumerate(sample_times):
            target = root / f"frame-{index}.png"
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode or not target.is_file():
                return False
            with Image.open(target) as image:
                grayscale = image.convert("L")
                statistics = ImageStat.Stat(grayscale)
                extrema = grayscale.getextrema()
                if extrema is None:
                    return False
                if not isinstance(extrema[0], int) or not isinstance(extrema[1], int):
                    return False
                low, high = extrema
                if high - low < 12 or statistics.stddev[0] < 3:
                    return False
    return True


def _contrast_ratio(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = luminance(foreground), luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _storyboard_text_contrast_pairs(
    storyboard: StoryboardManifest,
) -> list[tuple[str, str, str]]:
    """Return the actual deterministic text surfaces used by the renderer.

    The renderer accepts per-scene color-token overrides. Checking only one
    caption color pair would allow an unreadable override into an otherwise
    valid final export, so this mirrors each primitive's rendered surfaces.
    """

    pairs: list[tuple[str, str, str]] = [
        ("captions text/background", DEFAULT_THEME_COLORS["text"], "#020817"),
        ("source receipt text/background", "#172033", "#f5f1e8"),
    ]
    for scene in storyboard.scenes:
        colors = {**DEFAULT_THEME_COLORS, **scene.theme_overrides}
        background = colors["background"]
        scope = scene.scene_id
        pairs.extend(
            (
                (f"{scope} title text/background", colors["text"], background),
                (f"{scope} citation/background", colors["citation"], background),
            )
        )
        if "background" not in scene.theme_overrides:
            pairs.extend(
                (
                    (
                        f"{scope} title text/gradient highlight",
                        colors["text"],
                        DEFAULT_GRADIENT_HIGHLIGHT,
                    ),
                    (
                        f"{scope} citation/gradient highlight",
                        colors["citation"],
                        DEFAULT_GRADIENT_HIGHLIGHT,
                    ),
                )
            )

        if scene.primitive == "KineticText":
            pairs.append((f"{scope} body muted/background", colors["muted"], background))
            if "background" not in scene.theme_overrides:
                pairs.append(
                    (
                        f"{scope} body muted/gradient highlight",
                        colors["muted"],
                        DEFAULT_GRADIENT_HIGHLIGHT,
                    )
                )
        elif scene.primitive == "MechanismDiagram":
            if any(node.state == "active" for node in scene.visual.nodes):
                pairs.append((f"{scope} active-node text/accent", background, colors["accent"]))
            if any(node.state != "active" for node in scene.visual.nodes):
                pairs.append((f"{scope} inactive-node text/background", colors["text"], "#26395f"))
            if any(edge.label for edge in scene.visual.edges):
                pairs.append(
                    (f"{scope} edge-label warning/background", colors["warning"], background)
                )
        elif scene.primitive in {"ParameterSimulation", "Comparison"}:
            pairs.append((f"{scope} panel text/background", colors["text"], colors["panel"]))
        elif scene.primitive == "LimitationCard":
            pairs.extend(
                (
                    (f"{scope} card title/background", colors["text"], "#2b2431"),
                    (f"{scope} card body/background", colors["muted"], "#2b2431"),
                    (f"{scope} card label/background", colors["warning"], "#2b2431"),
                )
            )
    return pairs
