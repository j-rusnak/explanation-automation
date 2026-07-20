from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from techshort.alignment import cues_from_script
from techshort.domain.hashing import stable_hash
from techshort.domain.models import AngleSelection, derive_angle_selection_id
from techshort.generation.editorial import (
    build_rolling_shutter_beat_plan,
    build_rolling_shutter_brief,
)
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


def test_multi_topic_golden_corpus_flags_missing_retention_metadata() -> None:
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
        non_pass = {
            check.check_id: check.status for check in first.checks if check.status != "pass"
        }
        assert non_pass == {"rehook-payoff-placement": "warning"}
        assert first.status == "warning"
        assert first.score == 96


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


def test_retention_checks_detect_slow_open_sparse_cadence_and_dead_air() -> None:
    payload = _fixture("mechanism.json").model_dump(mode="json")
    scenes = payload["scenes"]
    assert isinstance(scenes, list)
    opening = scenes[0]
    sparse = scenes[1]
    assert isinstance(opening, dict)
    assert isinstance(sparse, dict)
    opening["duration_seconds"] = 8
    opening["motion_beats"] = ["late-reveal"]
    sparse["duration_seconds"] = 14
    sparse["motion_beats"] = ["single-hold"]
    captions = payload["captions"]
    assert isinstance(captions, list)
    payload["captions"] = [
        captions[0],
        {
            "cue_id": "after-gap",
            "start_seconds": 6,
            "end_seconds": 8,
            "text": "The explanation resumes after a long gap.",
        },
    ]

    checks = _checks(CreativeQualityInput.model_validate(payload))

    assert checks["cold-open-timing"] == "failure"
    assert checks["visual-beat-cadence"] == "failure"
    assert checks["dead-air-static-stretches"] == "failure"


def test_retention_checks_require_rehook_and_payoff_without_rewarding_bait() -> None:
    payload = _fixture("comparison.json").model_dump(mode="json")
    cover = payload["cover"]
    scenes = payload["scenes"]
    assert isinstance(cover, dict)
    assert isinstance(scenes, list)
    cover["headline"] = "Wait until the end: you won't believe this proves everything"
    for scene in scenes:
        assert isinstance(scene, dict)
        if scene["engagement_role"] in {"rehook", "payoff"}:
            scene["engagement_role"] = "mechanism"
        scene["motion_beats"] = ["steady-step", "continue-step"]

    result = evaluate_creative_quality(CreativeQualityInput.model_validate(payload))
    checks = {check.check_id: check for check in result.checks}

    assert checks["rehook-payoff-placement"].status == "warning"
    assert checks["hook-integrity"].status == "failure"
    assert checks["hook-integrity"].remediation is not None
    assert "remove bait" in checks["hook-integrity"].remediation


def test_legacy_scene_positions_roles_and_motion_tokens_do_not_fake_retention_pass() -> None:
    snapshot = _fixture("comparison.json")

    result = evaluate_creative_quality(snapshot)
    check = next(item for item in result.checks if item.check_id == "rehook-payoff-placement")

    assert check.status == "warning"
    assert check.details == {
        "timing_source": "missing-retention-plan",
        "declared_rehook_scene_ids": "s2",
        "declared_payoff_scene_ids": "s3",
        "legacy_scene_roles_accepted": "false",
    }
    assert check.remediation is not None
    assert "retention plan" in check.remediation


def test_caption_timing_and_flashing_proxies_are_actionable() -> None:
    payload = _fixture("timeline.json").model_dump(mode="json")
    scenes = payload["scenes"]
    captions = payload["captions"]
    assert isinstance(scenes, list)
    assert isinstance(captions, list)
    first_scene = scenes[0]
    first_cue = captions[0]
    second_cue = captions[1]
    assert isinstance(first_scene, dict)
    assert isinstance(first_cue, dict)
    assert isinstance(second_cue, dict)
    first_scene["flash_events_per_second"] = 4
    first_scene["motion_intensity"] = "energetic"
    first_cue["end_seconds"] = 0.4
    second_cue["start_seconds"] = 0.3

    result = evaluate_creative_quality(CreativeQualityInput.model_validate(payload))
    checks = {check.check_id: check for check in result.checks}

    assert checks["caption-timing-accessibility"].status == "failure"
    assert checks["motion-intensity-flashing"].status == "failure"
    assert checks["motion-intensity-flashing"].details["maximum_flash_events_per_second"] == "4.000"


def test_retention_roles_are_singular() -> None:
    payload = _fixture("architecture.json").model_dump(mode="json")
    scenes = payload["scenes"]
    assert isinstance(scenes, list)
    second = scenes[1]
    assert isinstance(second, dict)
    second["engagement_role"] = "cold-open"

    with pytest.raises(ValidationError, match="at most one cold-open"):
        CreativeQualityInput.model_validate(payload)


def test_persisted_retention_timing_overrides_scene_estimates_and_hook_policy() -> None:
    payload = _fixture("mechanism.json").model_dump(mode="json")
    payload["retention"] = {
        "plan_version_id": "retention-test",
        "cold_open_duration_seconds": 5,
        "cold_open_text": "A rolling shutter records rows at different moments.",
        "truth_up_front": True,
        "deceptive_withholding": False,
        "total_duration_seconds": 20,
        "max_attention_gap_seconds": 7,
        "events": [
            {
                "event_id": "event-open",
                "beat_id": "beat-open",
                "scheduled_at_seconds": 1.5,
                "event_kind": "pattern-interrupt",
            },
            {
                "event_id": "event-rehook",
                "beat_id": "beat-rehook",
                "scheduled_at_seconds": 7,
                "event_kind": "re-hook",
            },
            {
                "event_id": "event-evidence",
                "beat_id": "beat-evidence",
                "scheduled_at_seconds": 11,
                "event_kind": "evidence-payoff",
            },
            {
                "event_id": "event-limit",
                "beat_id": "beat-limit",
                "scheduled_at_seconds": 14,
                "event_kind": "limitation-reframe",
            },
            {
                "event_id": "event-final",
                "beat_id": "beat-final",
                "scheduled_at_seconds": 18,
                "event_kind": "final-payoff",
            },
        ],
    }
    snapshot = CreativeQualityInput.model_validate(payload)
    checks = {check.check_id: check for check in evaluate_creative_quality(snapshot).checks}

    assert checks["cold-open-timing"].status == "pass"
    assert checks["cold-open-timing"].details["timing_source"] == "retention-plan"
    assert checks["rehook-payoff-placement"].status == "pass"
    assert checks["hook-integrity"].status == "pass"

    payload["retention"]["truth_up_front"] = False
    payload["retention"]["deceptive_withholding"] = True
    dishonest = CreativeQualityInput.model_validate(payload)
    assert _checks(dishonest)["hook-integrity"] == "failure"


def test_current_manifest_adapter_preserves_quality_metadata() -> None:
    provider = FixtureProvider()
    source_text = "\n\n".join(provider.phrases)
    claims = provider.generate_claims(source_text, "source-test", "a" * 64)
    angles = provider.generate_angles(claims)
    selected = next(item for item in angles.candidates if item.angle == "everyday-mechanism")
    selected_hash = stable_hash(selected)
    selection = AngleSelection(
        selection_id=derive_angle_selection_id(
            angles.version_id, "everyday-mechanism", selected_hash
        ),
        angles_version_id=angles.version_id,
        selected_angle="everyday-mechanism",
        selected_candidate_hash=selected_hash,
    )
    brief = build_rolling_shutter_brief(claims, angles, selection)
    beat_plan = build_rolling_shutter_beat_plan(brief)
    script = provider.generate_script(
        claims,
        "everyday-mechanism",
        angles_version_id=angles.version_id,
        angle_selection_id=selection.selection_id,
    )
    retention_plan = provider.generate_retention_plan(brief, beat_plan, script)
    storyboard = provider.generate_storyboard(script)
    cover = CreativeCoverInput(
        cover_id="cover-test",
        headline="Why Straight Blades Look Bent",
        focal_visual="scanline-warped blade comparison",
        layout="split-hero",
        citation="Camera timing note · Sensor readout",
    )

    legacy_snapshot = creative_input_from_manifests(
        storyboard,
        script,
        cues_from_script(script),
        cover,
        case_id="adapter-legacy-test",
        topic_kind="mechanism",
        pacing="high-retention",
    )
    assert legacy_snapshot.retention is None
    assert not any(
        scene.engagement_role in {"rehook", "payoff"} for scene in legacy_snapshot.scenes
    )
    legacy_check = next(
        check
        for check in evaluate_creative_quality(legacy_snapshot).checks
        if check.check_id == "rehook-payoff-placement"
    )
    assert legacy_check.status == "warning"
    assert legacy_check.details["timing_source"] == "missing-retention-plan"

    snapshot = creative_input_from_manifests(
        storyboard,
        script,
        cues_from_script(script),
        cover,
        case_id="adapter-test",
        topic_kind="mechanism",
        pacing="high-retention",
        retention_plan=retention_plan,
    )

    assert len(snapshot.scenes) == len(storyboard.scenes)
    assert snapshot.scenes[0].narration == script.segments[0].text
    assert snapshot.scenes[0].layout == storyboard.scenes[0].layout
    assert snapshot.scenes[0].engagement_role == "cold-open"
    assert any(scene.engagement_role == "rehook" for scene in snapshot.scenes)
    assert any(scene.engagement_role == "payoff" for scene in snapshot.scenes)
    assert snapshot.pacing == "high-retention"
    assert snapshot.retention is not None
    assert snapshot.retention.plan_version_id == retention_plan.version_id
    assert snapshot.retention.events[0].scheduled_at_seconds <= 2
    assert any("pattern-interrupt" in beat for beat in snapshot.scenes[0].motion_beats)
    checks = _checks(snapshot)
    assert checks["cold-open-timing"] == "pass"
    assert checks["visual-beat-cadence"] == "pass"
    assert checks["rehook-payoff-placement"] == "pass"
    assert checks["hook-integrity"] == "pass"
    assert checks["exposed-internal-ids"] == "pass"
    assert checks["primitive-layout-diversity"] == "pass"
    assert checks["static-motion-budget"] == "pass"

    retimed = creative_input_from_manifests(
        storyboard,
        script,
        cues_from_script(script, target_duration=65),
        cover,
        case_id="adapter-retimed-test",
        topic_kind="mechanism",
        pacing="high-retention",
        retention_plan=retention_plan,
    )
    assert retimed.retention is not None
    expected_scale = 65 / retention_plan.cadence.total_duration_seconds
    assert retimed.retention.total_duration_seconds == pytest.approx(65)
    assert retimed.retention.timing_scale == pytest.approx(expected_scale)
    assert sum(scene.duration_seconds for scene in retimed.scenes) == pytest.approx(65)
    assert retimed.retention.events[0].scheduled_at_seconds == pytest.approx(
        retention_plan.attention_events[0].scheduled_at_seconds * expected_scale
    )
    retimed_checks = {check.check_id: check for check in evaluate_creative_quality(retimed).checks}
    assert retimed_checks["cold-open-timing"].details["timing_scale"] == f"{expected_scale:.3f}"
    assert (
        retimed_checks["visual-beat-cadence"].details["plan_scene_runtime_delta_seconds"] == "0.00"
    )
