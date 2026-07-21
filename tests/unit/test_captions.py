from __future__ import annotations

import re
from pathlib import Path

import pytest

from techshort.alignment import (
    as_srt,
    as_vtt,
    caption_warnings,
    cues_from_script,
    write_caption_files,
)
from techshort.domain.models import ScriptManifest, ScriptSegment
from techshort.providers.fixture import FixtureProvider


def test_caption_timing_is_monotonic_and_serializes() -> None:
    provider = FixtureProvider()
    claims = provider.generate_claims(" ".join(provider.phrases), "source-x", "a" * 64)
    script = provider.generate_script(claims, "everyday-mechanism")
    cues = cues_from_script(script)
    assert cues[0].start == 0
    assert all(left.end <= right.start for left, right in zip(cues, cues[1:], strict=False))
    assert "00:00:00,000 -->" in as_srt(cues)
    assert as_vtt(cues).startswith("WEBVTT")
    assert not caption_warnings(cues)


def test_fixture_captions_meet_reading_speed_and_avoid_orphan_cues() -> None:
    provider = FixtureProvider()
    claims = provider.generate_claims(" ".join(provider.phrases), "source-x", "a" * 64)
    script = provider.generate_script(claims, "everyday-mechanism")

    cues = cues_from_script(script)

    assert min(cue.end - cue.start for cue in cues) >= 0.8
    assert max(len(re.sub(r"\s+", "", cue.text)) / (cue.end - cue.start) for cue in cues) <= 20
    assert all(len(cue.text.split()) >= 2 for cue in cues)


def test_caption_chunks_rebalance_a_trailing_singleton_without_changing_words() -> None:
    factual_text = "Neighboring lines can describe different instants."
    script = ScriptManifest(
        version_id="script-balanced-cues",
        claims_version_id="claims-x",
        angles_version_id="angles-x",
        angle_selection_id="selection-x",
        angle="everyday-mechanism",
        segments=[
            ScriptSegment(
                segment_id="segment-fact",
                text=factual_text,
                segment_type="factual",
                claim_ids=["claim-x"],
                approximate_duration=4,
            ),
            ScriptSegment(
                segment_id="segment-limit",
                text="This example has a limitation.",
                segment_type="limitation",
                claim_ids=["claim-x"],
                approximate_duration=2,
            ),
        ],
    )

    cues = cues_from_script(script)
    factual_cues = [cue for cue in cues if cue.end <= 4]

    assert len(factual_cues) == 2
    assert all(len(cue.text.split()) >= 2 for cue in factual_cues)
    assert " ".join(cue.text for cue in factual_cues) == factual_text
    assert all(len(cue.text) <= 42 for cue in factual_cues)


def test_caption_timing_can_scale_to_narration_duration() -> None:
    provider = FixtureProvider()
    claims = provider.generate_claims(" ".join(provider.phrases), "source-x", "a" * 64)
    script = provider.generate_script(claims, "everyday-mechanism")

    cues = cues_from_script(script, target_duration=54.321)

    assert cues[-1].end == 54.321
    assert all(left.end <= right.start for left, right in zip(cues, cues[1:], strict=False))
    scale = 54.321 / sum(segment.approximate_duration for segment in script.segments)
    expected_boundaries: list[float] = []
    elapsed = 0.0
    for segment in script.segments:
        elapsed += segment.approximate_duration
        expected_boundaries.append(elapsed * scale)
    assert all(
        any(cue.end == pytest.approx(boundary) for cue in cues) for boundary in expected_boundaries
    )


def test_infeasible_caption_budget_preserves_boundary_and_surfaces_excess_speed() -> None:
    script = ScriptManifest(
        version_id="script-infeasible-cues",
        claims_version_id="claims-x",
        angles_version_id="angles-x",
        angle_selection_id="selection-x",
        angle="everyday-mechanism",
        segments=[
            ScriptSegment(
                segment_id="segment-fact",
                text="Dense technical narration still keeps its approved timing boundary intact.",
                segment_type="factual",
                claim_ids=["claim-x"],
                approximate_duration=1,
            ),
            ScriptSegment(
                segment_id="segment-limit",
                text="This example has a limitation.",
                segment_type="limitation",
                claim_ids=["claim-x"],
                approximate_duration=2,
            ),
        ],
    )

    cues = cues_from_script(script)
    first_segment_cues = [cue for cue in cues if cue.end <= 1]

    assert first_segment_cues[-1].end == 1
    assert all(
        left.end == right.start
        for left, right in zip(first_segment_cues, first_segment_cues[1:], strict=False)
    )
    assert any(
        len(re.sub(r"\s+", "", cue.text)) / (cue.end - cue.start) > 20 for cue in first_segment_cues
    )


def test_long_unbroken_word_is_split_without_empty_cues() -> None:
    script = ScriptManifest(
        version_id="script-long-word",
        claims_version_id="claims-x",
        angles_version_id="angles-x",
        angle_selection_id="selection-x",
        angle="everyday-mechanism",
        segments=[
            ScriptSegment(
                segment_id="segment-fact",
                text="electroencephalographically" * 4,
                segment_type="factual",
                claim_ids=["claim-x"],
                approximate_duration=4,
            ),
            ScriptSegment(
                segment_id="segment-limit",
                text="This remains a bounded limitation.",
                segment_type="limitation",
                claim_ids=["claim-x"],
                approximate_duration=2,
            ),
        ],
    )

    cues = cues_from_script(script)

    assert cues
    assert all(cue.text and len(cue.text) <= 42 for cue in cues)
    assert not caption_warnings(cues)


def test_scaled_caption_serialization_has_matching_terminal_time(tmp_path: Path) -> None:
    provider = FixtureProvider()
    claims = provider.generate_claims(" ".join(provider.phrases), "source-x", "a" * 64)
    script = provider.generate_script(claims, "everyday-mechanism")
    cues = cues_from_script(script, target_duration=50)

    srt, vtt = write_caption_files(tmp_path, cues)
    assert "00:00:50,000" in srt.read_text(encoding="utf-8")
    assert "00:00:50.000" in vtt.read_text(encoding="utf-8")
