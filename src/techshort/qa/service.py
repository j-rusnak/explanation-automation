from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from techshort.alignment import caption_warnings, cues_from_script
from techshort.domain.models import (
    AssetManifest,
    ClaimsManifest,
    EvidenceManifest,
    QACheck,
    QAReport,
    ReviewStatus,
    ScriptManifest,
    StoryboardManifest,
)
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.ingestion import resolve_evidence_text


def _check(check_id: str, passed: bool, success: str, failure: str, hard: bool = True) -> QACheck:
    return QACheck(
        check_id=check_id,
        status="pass" if passed else "failure",
        message=success if passed else failure,
        hard_blocker=hard and not passed,
    )


def run_qa(store: ProjectStore, media_path: Path | None = None) -> QAReport:
    checks: list[QACheck] = []
    blockers: list[str] = []
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    assets_path = store.path("assets/asset-manifest.json")
    assets = (
        load_model(assets_path, AssetManifest)
        if assets_path.exists()
        else AssetManifest(version_id="assets-empty")
    )
    evidence_map = {item.evidence_id: item for item in evidence.evidence}
    evidence_valid = True
    for span in evidence.evidence:
        try:
            evidence_valid &= (
                resolve_evidence_text(store, span.source_id, span.char_start, span.char_end)
                == span.excerpt
            )
        except (OSError, ValueError):
            evidence_valid = False
    claims_complete = all(
        c.evidence_span_ids and set(c.evidence_span_ids).issubset(evidence_map)
        for c in claims.claims
    )
    checks.append(
        _check(
            "evidence-completeness",
            evidence_valid and claims_complete,
            "All claim evidence resolves exactly",
            "Evidence is missing or no longer resolves",
        )
    )
    approved_claims = {
        c.claim_id
        for c in claims.claims
        if c.review_status == ReviewStatus.APPROVED and c.approval_hash
    }
    approval_valid = all(
        s.review_status == ReviewStatus.APPROVED
        and (not s.claim_ids or set(s.claim_ids).issubset(approved_claims))
        for s in script.segments
    )
    checks.append(
        _check(
            "approval-validity",
            approval_valid,
            "Script and claim approvals are valid",
            "Unapproved or stale claim/script dependency",
        )
    )
    limitation = any(s.segment_type == "limitation" and s.claim_ids for s in script.segments)
    checks.append(
        _check(
            "required-limitation",
            limitation,
            "A cited limitation is present",
            "A cited meaningful limitation is required",
        )
    )
    rights = all(
        a.rights_status in {"original", "user-owned", "permissively-licensed"}
        and a.embedding_allowed
        and a.review_status == ReviewStatus.APPROVED
        for a in assets.assets
    )
    checks.append(
        _check(
            "rights-completeness",
            rights,
            "All embedded assets have approved rights",
            "Unknown, restricted, citation-only, or unapproved asset rights",
        )
    )
    project = store.project()
    stale = any(
        getattr(project.approvals, gate) == ReviewStatus.STALE
        for gate in ("claims", "script", "storyboard", "rights")
    )
    checks.append(
        _check(
            "stale-dependencies",
            not stale,
            "No stale dependencies",
            "An upstream change invalidated downstream work",
        )
    )
    duration = sum(scene.duration for scene in storyboard.scenes)
    checks.append(
        _check(
            "duration",
            45 <= duration <= 75,
            f"Duration is {duration:.1f}s",
            f"Duration {duration:.1f}s is outside 45-75s",
            hard=False,
        )
    )
    caption_issues = caption_warnings(cues_from_script(script))
    checks.append(
        QACheck(
            check_id="caption-overflow",
            status="warning" if caption_issues else "pass",
            message="; ".join(caption_issues)
            if caption_issues
            else "Caption lines fit the 42-character limit",
            hard_blocker=False,
        )
    )
    citations = all(scene.claim_ids for scene in storyboard.scenes if scene.evidence_label)
    checks.append(
        _check(
            "missing-citations",
            citations,
            "Evidence-labeled scenes cite claims",
            "An evidence-labeled scene lacks claim IDs",
        )
    )
    storyboard_approved = all(
        scene.review_status == ReviewStatus.APPROVED for scene in storyboard.scenes
    )
    checks.append(
        _check(
            "storyboard-approval",
            storyboard_approved,
            "All scenes are approved",
            "Storyboard contains unapproved scenes",
        )
    )
    if media_path:
        checks.extend(
            _media_checks(media_path, project.width, project.height, project.fps, duration)
        )
    blockers = [item.message for item in checks if item.status == "failure" and item.hard_blocker]
    report = QAReport(project_id=project.project_id, checks=checks, export_blockers=blockers)
    atomic_write_model(store.path("renders/previews/qa-report.json"), report)
    return report


def _media_checks(
    path: Path, width: int, height: int, fps: int, expected_duration: float
) -> list[QACheck]:
    if not path.exists() or path.stat().st_size == 0:
        return [_check("renderer-failure", False, "", "Rendered video is missing or empty")]
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return [
            QACheck(
                check_id="media-probe",
                status="warning",
                message="ffprobe is unavailable; media metadata was not independently verified",
                hard_blocker=False,
            )
        ]
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        return [_check("renderer-failure", False, "", f"ffprobe failed: {result.stderr.strip()}")]
    data: dict[str, object] = json.loads(result.stdout)
    streams = data.get("streams", [])
    typed_streams = streams if isinstance(streams, list) else []
    video: dict[str, object] = next(
        (
            stream
            for stream in typed_streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        {},
    )
    format_data = data.get("format", {})
    typed_format = format_data if isinstance(format_data, dict) else {}
    actual_duration = float(typed_format.get("duration", 0))
    return [
        _check(
            "resolution",
            video.get("width") == width and video.get("height") == height,
            "Resolution is correct",
            "Rendered resolution is incorrect",
        ),
        _check(
            "frame-rate",
            video.get("r_frame_rate") in {f"{fps}/1", str(fps)},
            "Frame rate is correct",
            "Rendered frame rate is incorrect",
        ),
        _check(
            "media-duration",
            abs(actual_duration - expected_duration) < 1.5,
            "Media duration matches storyboard",
            "Media duration differs from storyboard",
        ),
    ]
