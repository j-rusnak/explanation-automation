from __future__ import annotations

import pytest
from pydantic import ValidationError

from techshort.domain.hashing import stable_hash
from techshort.domain.models import (
    CoverCandidate,
    CoverManifest,
    CoverSelection,
    RasterScanVisual,
    Scene,
    derive_cover_manifest_id,
    derive_cover_selection_id,
)


def _cover_candidate(candidate_id: str = "cover-scanline") -> CoverCandidate:
    return CoverCandidate(
        candidate_id=candidate_id,
        headline="Why straight blades look bent",
        subheadline="A sensor can scan one frame across time.",
        layout="split-hero",
        palette="signal-lab",
        hero={"kind": "scanline", "subject": "blade", "distortion": 0.7},
        claim_ids=["claim-row-timing", "claim-motion-skew"],
        evidence_ids=["evidence-01"],
        accessibility_description="A straight blade beside a scanline-warped blade.",
    )


def test_cover_manifest_and_selection_are_content_derived() -> None:
    candidates = [
        _cover_candidate("cover-scanline"),
        _cover_candidate("cover-split").model_copy(
            update={
                "layout": "editorial",
                "palette": "technical-editorial",
                "headline": "One frame, many moments",
            }
        ),
        _cover_candidate("cover-diagram").model_copy(
            update={
                "layout": "diagram-hero",
                "palette": "blueprint",
                "headline": "The scan that bends motion",
            }
        ),
    ]
    version_id = derive_cover_manifest_id("storyboard-current", candidates)
    manifest = CoverManifest(
        version_id=version_id,
        storyboard_version_id="storyboard-current",
        candidates=candidates,
    )
    selected = manifest.candidates[0]
    candidate_hash = stable_hash(selected)
    selection = CoverSelection(
        selection_id=derive_cover_selection_id(
            manifest.version_id, selected.candidate_id, candidate_hash
        ),
        cover_version_id=manifest.version_id,
        selected_candidate_id=selected.candidate_id,
        selected_candidate_hash=candidate_hash,
    )

    assert selection.selection_id.startswith("cover-selection-")
    with pytest.raises(ValidationError, match="does not match"):
        CoverSelection.model_validate(
            {**selection.model_dump(mode="json"), "selection_id": "cover-selection-forged"}
        )


def test_new_primitive_requires_matching_typed_visual() -> None:
    scene = Scene(
        scene_id="scene-scan",
        order=0,
        start_time=0,
        duration=8,
        primitive="RasterScan",
        layout="full-diagram",
        motion="precise",
        script_segment_ids=["segment-1"],
        claim_ids=["claim-row-timing"],
        on_screen_text="Rows sample different moments",
        visual=RasterScanVisual(
            kind="raster-scan",
            direction="top-to-bottom",
            rows=16,
            subject="blade",
            distortion=0.65,
            scan_label="scan time",
            before_label="straight blade",
            after_label="assembled frame",
        ),
        accessibility_description="Rows scan downward while the blade moves.",
        evidence_label="DOCUMENTED",
        citation_label="Source-backed · p. 1",
        dependency_hash="a" * 64,
    )
    assert scene.visual.kind == "raster-scan"

    payload = scene.model_dump(mode="json")
    payload["primitive"] = "Timeline"
    with pytest.raises(ValidationError, match="does not match"):
        Scene.model_validate(payload)


def test_cover_and_typed_visual_text_remain_inert() -> None:
    cover_payload = _cover_candidate().model_dump(mode="json")
    cover_payload["headline"] = "<script>run()</script>"
    with pytest.raises(ValidationError, match="active content"):
        CoverCandidate.model_validate(cover_payload)

    with pytest.raises(ValidationError, match="active content"):
        RasterScanVisual(
            kind="raster-scan",
            direction="top-to-bottom",
            rows=12,
            subject="grid",
            distortion=0.4,
            scan_label="javascript:alert(1)",
            before_label="before",
            after_label="after",
        )
