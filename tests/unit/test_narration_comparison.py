from __future__ import annotations

import pytest

from techshort.alignment import compare_narration, normalized_words


def test_narration_comparison_ignores_case_punctuation_and_unicode_width() -> None:
    script = "Rolling-shutter cameras don\u2019t expose every row at once: １２ ms."
    transcript = "rolling shutter cameras DON'T expose every row at once 12 MS"

    comparison = compare_narration(script, transcript)

    assert normalized_words(script) == normalized_words(transcript)
    assert comparison.status == "pass"
    assert comparison.word_error_rate == 0


def test_narration_comparison_has_deterministic_warning_and_failure_thresholds() -> None:
    script = "one two three four five six seven eight nine ten"

    warning = compare_narration(script, "one two changed four five six changed eight nine ten")
    failure = compare_narration(
        script, "one two changed changed changed six changed eight nine ten"
    )

    assert warning.word_error_rate == pytest.approx(0.2)
    assert warning.status == "warning"
    assert failure.word_error_rate == pytest.approx(0.4)
    assert failure.status == "failure"


def test_narration_comparison_rejects_unbounded_input() -> None:
    oversized = "word " * 2_001

    with pytest.raises(ValueError, match="safety bound"):
        compare_narration("short approved script", oversized)
