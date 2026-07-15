from __future__ import annotations

from techshort.alignment import as_srt, as_vtt, caption_warnings, cues_from_script
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
