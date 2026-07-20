from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from techshort.alignment import cues_from_script
from techshort.providers.fixture import FixtureProvider
from techshort.qa.creative import (
    CreativeCoverInput,
    CreativeQualityInput,
    creative_input_from_manifests,
    evaluate_creative_quality,
)

QUALITY_FIXTURES = Path("tests/fixtures/quality")


def _fixture(name: str) -> CreativeQualityInput:
    payload = json.loads((QUALITY_FIXTURES / name).read_text(encoding="utf-8"))
    return CreativeQualityInput.model_validate(payload)


def _checks(snapshot: CreativeQualityInput) -> dict[str, str]:
    result = evaluate_creative_quality(snapshot)
    return {check.check_id: check.status for check in result.checks}


def test_multi_topic_golden_corpus_is_strict_and_passes() -> None:
    paths = sorted(QUALITY_FIXTURES.glob("*.json"))
    assert len(paths) >= 5

    snapshots = [_fixture(path.name) for path in paths]
    assert {snapshot.topic_kind for snapshot in snapshots} >= {
        "mechanism",
        "chart",
        "comparison",
        "timeline",
        "architecture",
    }
    for snapshot in snapshots:
        first = evaluate_creative_quality(snapshot)
        second = evaluate_creative_quality(snapshot)
        assert first == second
        assert first.status == "pass", {
            check.check_id: check.message for check in first.checks if check.status != "pass"
        }
        assert first.score == 100


def test_quality_snapshot_rejects_unknown_fields() -> None:
    payload = _fixture("mechanism.json").model_dump(mode="json")
    payload["unexpected_runtime_instruction"] = "run this"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CreativeQualityInput.model_validate(payload)


def test_creative_checks_detect_compound_quality_regressions() -> None:
    payload = _fixture("mechanism.json").model_dump(mode="json")
    cover = payload["cover"]
    assert isinstance(cover, dict)
    cover["headline"] = (
        "This excessively long cover headline attempts to explain every technical detail "
        "before anyone has chosen to watch the actual vertical explainer video"
    )
    cover["focal_visual"] = "placeholder"
    cover["citation"] = "claim-001"

    scenes = payload["scenes"]
    assert isinstance(scenes, list)
    for index, scene in enumerate(scenes):
        assert isinstance(scene, dict)
        scene["primitive"] = "ChartReveal"
        scene["layout"] = "default"
        scene["duration_seconds"] = 10
        scene["motion_beats"] = []
        scene["citation"] = None
        scene["evidence_label"] = None
        scene["series"] = [1.0, 2.0]
        scene["labels"] = ["one"]
        scene["x_axis_label"] = None
        scene["y_axis_label"] = None
        scene["units"] = None
        if index == 0:
            scene["title"] = "A title " + "with too many words " * 12
            scene["on_screen_text"] = scene["narration"]
            scene["body"] = "dense " * 55
            scene["color_encodings"] = {"before": "#CC0000", "after": "#CC0000"}
            scene["non_color_cues"] = []

    payload["captions"] = [
        {
            "cue_id": "too-fast",
            "start_seconds": 0,
            "end_seconds": 0.5,
            "text": (
                "This caption is far too long to read in half a second and it also needs "
                "more than two mobile lines.\norphan"
            ),
        }
    ]
    snapshot = CreativeQualityInput.model_validate(payload)
    checks = _checks(snapshot)

    expected_failures = {
        "cover-headline",
        "cover-focal-visual",
        "exposed-internal-ids",
        "scene-text-density",
        "scene-title-length",
        "primitive-layout-diversity",
        "static-motion-budget",
        "chart-context",
        "citation-presentation",
        "caption-reading-speed",
        "caption-two-line-limit",
        "color-independent-differentiation",
    }
    assert {check_id for check_id, status in checks.items() if status == "failure"} >= (
        expected_failures
    )
    assert checks["narration-screen-duplication"] == "warning"
    assert checks["caption-orphan-words"] == "warning"


def test_color_proxy_accepts_redundant_labels_but_warns_on_confusable_colors() -> None:
    payload = _fixture("comparison.json").model_dump(mode="json")
    scenes = payload["scenes"]
    assert isinstance(scenes, list)
    comparison = scenes[0]
    assert isinstance(comparison, dict)
    comparison["color_encodings"] = {"left": "#777777", "right": "#777777"}

    redundant = CreativeQualityInput.model_validate(payload)
    assert _checks(redundant)["color-independent-differentiation"] == "warning"

    comparison["non_color_cues"] = []
    color_only = CreativeQualityInput.model_validate(payload)
    assert _checks(color_only)["color-independent-differentiation"] == "failure"


def test_current_manifest_adapter_preserves_quality_metadata() -> None:
    provider = FixtureProvider()
    source_text = "\n\n".join(provider.phrases)
    claims = provider.generate_claims(source_text, "source-test", "a" * 64)
    angles = provider.generate_angles(claims)
    script = provider.generate_script(
        claims,
        "everyday-mechanism",
        angles_version_id=angles.version_id,
        angle_selection_id="selection-test",
    )
    storyboard = provider.generate_storyboard(script)
    cover = CreativeCoverInput(
        cover_id="cover-test",
        headline="Why Straight Blades Look Bent",
        focal_visual="scanline-warped blade comparison",
        layout="split-hero",
        citation="Camera timing note · Sensor readout",
    )

    snapshot = creative_input_from_manifests(
        storyboard,
        script,
        cues_from_script(script),
        cover,
        case_id="adapter-test",
        topic_kind="mechanism",
    )

    assert len(snapshot.scenes) == len(storyboard.scenes)
    assert snapshot.scenes[0].narration == script.segments[0].text
    assert snapshot.scenes[0].layout == storyboard.scenes[0].layout
    checks = _checks(snapshot)
    assert checks["exposed-internal-ids"] == "failure"
    assert checks["primitive-layout-diversity"] == "pass"
    assert checks["static-motion-budget"] == "pass"
