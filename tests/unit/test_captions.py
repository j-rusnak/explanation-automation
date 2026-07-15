from __future__ import annotations

from pathlib import Path

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


def test_caption_timing_can_scale_to_narration_duration() -> None:
    provider = FixtureProvider()
    claims = provider.generate_claims(" ".join(provider.phrases), "source-x", "a" * 64)
    script = provider.generate_script(claims, "everyday-mechanism")

    cues = cues_from_script(script, target_duration=54.321)

    assert cues[-1].end == 54.321
    assert all(left.end <= right.start for left, right in zip(cues, cues[1:], strict=False))


def test_long_unbroken_word_is_split_without_empty_cues() -> None:
    script = ScriptManifest(
        version_id="script-long-word",
        claims_version_id="claims-x",
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
