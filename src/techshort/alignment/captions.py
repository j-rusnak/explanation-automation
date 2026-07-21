from __future__ import annotations

import os
import re
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

from techshort.domain.models import ScriptManifest

from .comparison import normalized_words
from .timing import NarrationTimingManifest, SegmentTiming, WordTiming, validate_timing_projection


@dataclass(frozen=True)
class CaptionCue:
    index: int
    start: float
    end: float
    text: str


MAX_CAPTION_CHARACTERS = 42
MIN_CAPTION_DURATION_SECONDS = 0.8
MAX_CAPTION_CHARACTERS_PER_SECOND = 20.0
MIN_READABLE_CAPTION_CHARACTERS = round(
    MIN_CAPTION_DURATION_SECONDS * MAX_CAPTION_CHARACTERS_PER_SECOND
)
_DANGLING_CAPTION_ENDINGS = frozenset(
    """
    a although am an and any are as at be because been being but by can could did do does
    each every for from had has have if in into is like may might must no nor not of on onto
    or over per shall should so some than that the though through to under unless was were
    when while will with without would yet
    """.split()
)
_CLOSING_PUNCTUATION = "\"'\u2019\u201d)]}"
_ChunkScore = tuple[int, int, int, int, int, tuple[int, ...]]
_ChunkPlan = tuple[_ChunkScore, list[str]]


def _visible_character_count(text: str) -> int:
    return max(1, len(re.sub(r"\s+", "", text)))


def _wrapped_caption_chunks(text: str) -> list[str]:
    chunks = textwrap.wrap(
        text,
        width=MAX_CAPTION_CHARACTERS,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=True,
        drop_whitespace=True,
    ) or [text]
    for index in range(len(chunks) - 1, 0, -1):
        current_words = chunks[index].split()
        previous_words = chunks[index - 1].split()
        if len(current_words) != 1:
            continue
        merged = f"{chunks[index - 1]} {chunks[index]}"
        if len(merged) <= MAX_CAPTION_CHARACTERS:
            chunks[index - 1] = merged
            del chunks[index]
            continue
        if len(previous_words) < 3:
            continue
        rebalanced_current = f"{previous_words[-1]} {chunks[index]}"
        rebalanced_previous = " ".join(previous_words[:-1])
        if (
            len(rebalanced_current) <= MAX_CAPTION_CHARACTERS
            and len(rebalanced_previous) <= MAX_CAPTION_CHARACTERS
        ):
            chunks[index - 1] = rebalanced_previous
            chunks[index] = rebalanced_current
    return chunks


def _terminal_token(text: str) -> str:
    return text.split()[-1].rstrip(_CLOSING_PUNCTUATION) if text.split() else ""


def has_dangling_caption_ending(text: str) -> bool:
    """Return whether a cue stops on a connective that needs following words."""
    terminal = _terminal_token(text)
    if terminal.endswith((".", "?", "!")):
        return False
    normalized = re.sub(r"^\W+|\W+$", "", terminal, flags=re.UNICODE).casefold()
    return normalized in _DANGLING_CAPTION_ENDINGS


def _boundary_penalty(text: str) -> int:
    terminal = _terminal_token(text)
    if terminal.endswith((".", "?", "!")):
        return 0
    if terminal.endswith((";", ":")):
        return 1
    if terminal.endswith(","):
        return 2
    return 3


def _optimized_phrase_chunks(text: str) -> list[str] | None:
    words = " ".join(text.split()).split()
    if not words or any(len(word) > MAX_CAPTION_CHARACTERS for word in words):
        return None
    total_visible = _visible_character_count(" ".join(words))
    minimum_visible = min(MIN_READABLE_CAPTION_CHARACTERS, total_visible)
    best: list[_ChunkPlan | None] = [None] * (len(words) + 1)
    best[-1] = ((0, 0, 0, 0, 0, ()), [])

    for start in range(len(words) - 1, -1, -1):
        for end in range(start + 1, len(words) + 1):
            chunk = " ".join(words[start:end])
            if len(chunk) > MAX_CAPTION_CHARACTERS:
                break
            if _visible_character_count(chunk) < minimum_visible:
                continue
            tail = best[end]
            if tail is None:
                continue
            tail_score, tail_chunks = tail
            final_chunk = end == len(words)
            boundary_penalty = 0 if final_chunk else _boundary_penalty(chunk)
            raggedness = (len(chunk) - 34) ** 2
            score: _ChunkScore = (
                tail_score[0] + (0 if final_chunk else int(has_dangling_caption_ending(chunk))),
                tail_score[1] + 1,
                tail_score[2] + boundary_penalty * 20 + raggedness,
                tail_score[3] + boundary_penalty,
                tail_score[4] + raggedness,
                (-end, *tail_score[5]),
            )
            candidate = (score, [chunk, *tail_chunks])
            current_best = best[start]
            if current_best is None or score < current_best[0]:
                best[start] = candidate
    return best[0][1] if best[0] is not None else None


def _required_caption_duration(chunks: list[str]) -> float:
    return sum(
        max(
            MIN_CAPTION_DURATION_SECONDS,
            _visible_character_count(chunk) / MAX_CAPTION_CHARACTERS_PER_SECOND,
        )
        for chunk in chunks
    )


def _caption_chunks(text: str, segment_duration: float) -> list[str]:
    """Split narration at readable phrase boundaries without changing its words."""
    baseline = _wrapped_caption_chunks(text)
    baseline_dangling = sum(has_dangling_caption_ending(chunk) for chunk in baseline[:-1])
    if not baseline_dangling:
        return baseline
    optimized = _optimized_phrase_chunks(text)
    if optimized is None:
        return baseline
    optimized_dangling = sum(has_dangling_caption_ending(chunk) for chunk in optimized[:-1])
    if optimized_dangling >= baseline_dangling:
        return baseline
    baseline_fits = _required_caption_duration(baseline) <= segment_duration + 1e-9
    optimized_fits = _required_caption_duration(optimized) <= segment_duration + 1e-9
    return baseline if baseline_fits and not optimized_fits else optimized


def _cue_durations(chunks: list[str], segment_duration: float) -> list[float]:
    """Allocate time by readable character load while preserving the segment boundary."""
    character_counts = [_visible_character_count(chunk) for chunk in chunks]
    readable_minimums = [
        max(
            MIN_CAPTION_DURATION_SECONDS,
            character_count / MAX_CAPTION_CHARACTERS_PER_SECOND,
        )
        for character_count in character_counts
    ]
    required_duration = sum(readable_minimums)
    total_characters = sum(character_counts)
    if required_duration <= segment_duration:
        remaining = segment_duration - required_duration
        return [
            minimum + remaining * character_count / total_characters
            for minimum, character_count in zip(readable_minimums, character_counts, strict=True)
        ]

    # If the approved segment timing cannot satisfy both accessibility budgets,
    # scale both requirements equally. QA will surface the infeasible script honestly.
    infeasible_scale = segment_duration / required_duration
    return [minimum * infeasible_scale for minimum in readable_minimums]


def _timed_segment_cues(
    *,
    index: int,
    text: str,
    segment_timing: SegmentTiming,
    words: list[WordTiming],
) -> list[CaptionCue]:
    """Build approved-text cues from canonical word starts when possible."""

    segment_duration = segment_timing.end_seconds - segment_timing.start_seconds
    chunks = _caption_chunks(text, segment_duration)
    chunk_words = [normalized_words(chunk) for chunk in chunks]
    if tuple(word for chunk in chunk_words for word in chunk) == tuple(
        word.canonical for word in words
    ):
        result: list[CaptionCue] = []
        word_cursor = 0
        for chunk_index, (chunk, normalized_chunk) in enumerate(
            zip(chunks, chunk_words, strict=True)
        ):
            chunk_start = words[word_cursor].start_seconds
            word_cursor += len(normalized_chunk)
            chunk_end = (
                segment_timing.end_seconds
                if chunk_index == len(chunks) - 1
                else words[word_cursor].start_seconds
            )
            result.append(CaptionCue(index + chunk_index, chunk_start, chunk_end, chunk))
        return result

    # A very long unbroken identifier can be split inside a token to satisfy the
    # content bound. In that rare case, retain the approved chunks and allocate
    # them proportionally inside the exact timed segment interval.
    durations = _cue_durations(chunks, segment_duration)
    result = []
    current = segment_timing.start_seconds
    for chunk_index, (chunk, duration) in enumerate(zip(chunks, durations, strict=True)):
        chunk_end = (
            segment_timing.end_seconds
            if chunk_index == len(chunks) - 1
            else current + duration
        )
        result.append(CaptionCue(index + chunk_index, current, chunk_end, chunk))
        current = chunk_end
    return result


def cues_from_script(
    script: ScriptManifest,
    *,
    target_duration: float | None = None,
    timing: NarrationTimingManifest | None = None,
) -> list[CaptionCue]:
    """Create deterministic cue-level captions from approved script timing.

    When a verified timing manifest is supplied, cue text still comes only from
    the approved script while cue boundaries follow its canonical word timings.
    Without one, ``target_duration`` preserves the legacy proportional timing.
    The same cues are used for SRT, VTT, and the renderer payload so burned
    captions cannot drift from sidecars.
    """
    if timing is not None:
        validate_timing_projection(timing, script)
        if (
            target_duration is not None
            and abs(target_duration - timing.audio_duration_seconds) > 0.05
        ):
            raise ValueError("target caption duration differs from narration timing audio")
        words_by_segment: dict[str, list[WordTiming]] = {
            segment.segment_id: [] for segment in timing.segments
        }
        for word in timing.words:
            words_by_segment[word.segment_id].append(word)
        cues: list[CaptionCue] = []
        next_index = 1
        for script_segment, segment_timing in zip(
            script.segments, timing.segments, strict=True
        ):
            segment_cues = _timed_segment_cues(
                index=next_index,
                text=script_segment.text,
                segment_timing=segment_timing,
                words=words_by_segment[script_segment.segment_id],
            )
            cues.extend(segment_cues)
            next_index += len(segment_cues)
        return cues

    script_duration = sum(segment.approximate_duration for segment in script.segments)
    if target_duration is not None and target_duration <= 0:
        raise ValueError("target caption duration must be positive")
    timing_scale = target_duration / script_duration if target_duration is not None else 1.0
    fallback_cues: list[CaptionCue] = []
    current = 0.0
    elapsed_script_duration = 0.0
    index = 1
    for segment in script.segments:
        # textwrap always consumes input, including a single word longer than the
        # line limit. This avoids non-advancing loops for technical identifiers.
        segment_duration = segment.approximate_duration * timing_scale
        chunks = _caption_chunks(segment.text, segment_duration)
        durations = _cue_durations(chunks, segment_duration)
        elapsed_script_duration += segment.approximate_duration
        segment_end = elapsed_script_duration * timing_scale
        for chunk_index, (chunk, duration) in enumerate(zip(chunks, durations, strict=True)):
            cue_end = segment_end if chunk_index == len(chunks) - 1 else current + duration
            fallback_cues.append(
                CaptionCue(index=index, start=current, end=cue_end, text=chunk)
            )
            current = cue_end
            index += 1
    if fallback_cues and target_duration is not None:
        # Remove accumulated floating-point error while preserving monotonic cues.
        last = fallback_cues[-1]
        fallback_cues[-1] = CaptionCue(last.index, last.start, target_duration, last.text)
    return fallback_cues


def _time(value: float, vtt: bool = False) -> str:
    milliseconds = round(value * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def as_srt(cues: list[CaptionCue]) -> str:
    return (
        "\n\n".join(
            f"{cue.index}\n{_time(cue.start)} --> {_time(cue.end)}\n{cue.text}" for cue in cues
        )
        + "\n"
    )


def as_vtt(cues: list[CaptionCue]) -> str:
    body = "\n\n".join(
        f"{_time(cue.start, True)} --> {_time(cue.end, True)}\n{cue.text}" for cue in cues
    )
    return f"WEBVTT\n\n{body}\n"


def caption_warnings(cues: list[CaptionCue]) -> list[str]:
    return [
        f"caption {cue.index} exceeds {MAX_CAPTION_CHARACTERS} characters"
        for cue in cues
        if len(cue.text) > MAX_CAPTION_CHARACTERS
    ]


def write_caption_files(directory: Path, cues: list[CaptionCue]) -> tuple[Path, Path]:
    """Atomically write matching SRT and VTT caption sidecars."""
    directory.mkdir(parents=True, exist_ok=True)
    srt = directory / "captions.srt"
    vtt = directory / "captions.vtt"
    _atomic_write_text(srt, as_srt(cues))
    _atomic_write_text(vtt, as_vtt(cues))
    return srt, vtt


def _atomic_write_text(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
