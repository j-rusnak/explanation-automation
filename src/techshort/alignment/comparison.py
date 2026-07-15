from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

PASS_WORD_ERROR_RATE = 0.15
FAIL_WORD_ERROR_RATE = 0.35
MAX_COMPARISON_WORDS = 2_000


@dataclass(frozen=True)
class NarrationComparison:
    script_word_count: int
    transcript_word_count: int
    edit_distance: int
    word_error_rate: float
    similarity: float
    status: Literal["pass", "warning", "failure"]


def normalized_words(text: str) -> tuple[str, ...]:
    """Return stable Unicode-aware word tokens for narration comparison."""
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'")
    return tuple(re.findall(r"[^\W_]+(?:'[^\W_]+)?", normalized, flags=re.UNICODE))


def _edit_distance(reference: tuple[str, ...], hypothesis: tuple[str, ...]) -> int:
    """Compute Levenshtein distance with bounded, one-row memory."""
    previous = list(range(len(hypothesis) + 1))
    for row, reference_word in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_word in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (reference_word != hypothesis_word),
                )
            )
        previous = current
    return previous[-1]


def compare_narration(script_text: str, transcript_text: str) -> NarrationComparison:
    """Compare a transcript with the approved script using deterministic WER.

    Punctuation, case, and Unicode presentation differences do not count as
    narration changes. Inserted, deleted, reordered, or substituted words do.
    """
    script_words = normalized_words(script_text)
    transcript_words = normalized_words(transcript_text)
    if not script_words:
        raise ValueError("approved script contains no comparable words")
    if len(script_words) > MAX_COMPARISON_WORDS:
        raise ValueError("approved script exceeds the narration comparison safety bound")
    if len(transcript_words) > MAX_COMPARISON_WORDS:
        raise ValueError("narration transcript exceeds the comparison safety bound")

    edit_distance = _edit_distance(script_words, transcript_words)
    word_error_rate = edit_distance / len(script_words)
    similarity = max(0.0, 1.0 - word_error_rate)
    if word_error_rate <= PASS_WORD_ERROR_RATE:
        status: Literal["pass", "warning", "failure"] = "pass"
    elif word_error_rate <= FAIL_WORD_ERROR_RATE:
        status = "warning"
    else:
        status = "failure"
    return NarrationComparison(
        script_word_count=len(script_words),
        transcript_word_count=len(transcript_words),
        edit_distance=edit_distance,
        word_error_rate=word_error_rate,
        similarity=similarity,
        status=status,
    )
