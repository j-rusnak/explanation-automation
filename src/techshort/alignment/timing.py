from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.domain.hashing import stable_hash
from techshort.domain.models import ScriptManifest, now_utc

MAX_TIMING_WORDS = 2_000
DEFAULT_MINIMUM_ALIGNMENT_COVERAGE = 0.65
DEFAULT_MAXIMUM_WORD_ERROR_RATE = 0.35
DEFAULT_MAXIMUM_INTERPOLATED_GAP_WORDS = 3

TimingSource = Literal[
    "sapi-speak-progress",
    "local-whisper",
    "proportional-fallback",
]
ObservationSource = Literal["sapi-speak-progress", "local-whisper"]
ManifestTimingQuality = Literal[
    "engine-reported",
    "asr-aligned",
    "mixed",
    "proportional-fallback",
]
WordTimingQuality = Literal[
    "engine-reported",
    "asr-aligned",
    "interpolated",
    "proportional-fallback",
]
TimingOrigin = Literal[
    "engine-event",
    "asr-event",
    "interpolated",
    "proportional",
    "next-engine-event",
    "next-asr-event",
    "segment-boundary",
    "audio-boundary",
]

_WORD_PATTERN = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)?", flags=re.UNICODE)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_TIMING_TOLERANCE = 1e-7


def canonical_word_form(value: str) -> str:
    """Normalize one display token with the narration-comparison rules."""

    normalized = unicodedata.normalize("NFKC", value).casefold().replace("\u2019", "'")
    words = _WORD_PATTERN.findall(normalized)
    if len(words) != 1:
        raise ValueError("timing display text must normalize to exactly one word")
    return str(words[0])


def canonical_script_text(script: ScriptManifest) -> str:
    """Return the stable approved narration text represented by a script."""

    return "\n".join(" ".join(segment.text.split()) for segment in script.segments).strip()


def derive_word_id(
    segment_id: str,
    segment_word_index: int,
    display_text: str,
    canonical: str,
    char_start: int,
    char_end: int,
) -> str:
    return (
        "word-"
        + stable_hash(
            {
                "segment_id": segment_id,
                "segment_word_index": segment_word_index,
                "display_text": display_text,
                "canonical": canonical,
                "char_start": char_start,
                "char_end": char_end,
            }
        )[:16]
    )


@dataclass(frozen=True)
class CanonicalScriptWord:
    word_id: str
    segment_id: str
    segment_index: int
    segment_word_index: int
    global_word_index: int
    display_text: str
    canonical: str
    char_start: int
    char_end: int


def canonical_script_words(script: ScriptManifest) -> tuple[CanonicalScriptWord, ...]:
    """Project exact display tokens and source spans from ordered script segments."""

    words: list[CanonicalScriptWord] = []
    for segment_index, segment in enumerate(script.segments):
        segment_words = list(_WORD_PATTERN.finditer(segment.text))
        if not segment_words:
            raise ValueError(f"script segment {segment.segment_id} contains no timing words")
        for segment_word_index, match in enumerate(segment_words):
            display_text = match.group(0)
            canonical = canonical_word_form(display_text)
            words.append(
                CanonicalScriptWord(
                    word_id=derive_word_id(
                        segment.segment_id,
                        segment_word_index,
                        display_text,
                        canonical,
                        match.start(),
                        match.end(),
                    ),
                    segment_id=segment.segment_id,
                    segment_index=segment_index,
                    segment_word_index=segment_word_index,
                    global_word_index=len(words),
                    display_text=display_text,
                    canonical=canonical,
                    char_start=match.start(),
                    char_end=match.end(),
                )
            )
            if len(words) > MAX_TIMING_WORDS:
                raise ValueError("approved script exceeds the 2,000-word timing safety bound")
    if not words:
        raise ValueError("approved script contains no timing words")
    return tuple(words)


class EngineWordObservation(BaseModel):
    """One bounded, inert timing observation emitted by a local engine."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    sequence_index: int = Field(ge=0, le=MAX_TIMING_WORDS * 4)
    text: str = Field(min_length=1, max_length=256)
    start_seconds: float = Field(ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    character_position: int | None = Field(default=None, ge=0)
    character_count: int | None = Field(default=None, ge=1)

    @field_validator("text")
    @classmethod
    def inert_text(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("engine timing text must be nonempty inert text")
        return value

    @model_validator(mode="after")
    def valid_interval_and_character_span(self) -> EngineWordObservation:
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("engine observation end must follow its start")
        if (self.character_position is None) != (self.character_count is None):
            raise ValueError("engine character position and count must be supplied together")
        return self


class WordTiming(BaseModel):
    """Timing for one exact approved-script display token."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    word_id: str = Field(pattern=r"^word-[0-9a-f]{16}$")
    segment_id: str = Field(min_length=1, max_length=128)
    segment_word_index: int = Field(ge=0, lt=MAX_TIMING_WORDS)
    global_word_index: int = Field(ge=0, lt=MAX_TIMING_WORDS)
    display_text: str = Field(min_length=1, max_length=256)
    canonical: str = Field(min_length=1, max_length=256)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    source: TimingSource
    quality: WordTimingQuality
    start_origin: TimingOrigin
    end_origin: TimingOrigin
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("segment_id")
    @classmethod
    def safe_segment_id(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("timing segment ID is invalid")
        return value

    @field_validator("display_text")
    @classmethod
    def inert_display_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("timing display text may not contain NUL bytes")
        return value

    @model_validator(mode="after")
    def exact_identity_and_interval(self) -> WordTiming:
        if self.char_end <= self.char_start:
            raise ValueError("word character span must be ordered")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("word timing interval must have positive duration")
        if canonical_word_form(self.display_text) != self.canonical:
            raise ValueError("word canonical form does not match its display text")
        expected = derive_word_id(
            self.segment_id,
            self.segment_word_index,
            self.display_text,
            self.canonical,
            self.char_start,
            self.char_end,
        )
        if self.word_id != expected:
            raise ValueError("word timing ID does not match its exact script token")
        if self.source == "proportional-fallback" and self.quality != "proportional-fallback":
            raise ValueError("proportional word sources must be labeled proportional fallback")
        if self.quality == "proportional-fallback" and self.source != "proportional-fallback":
            raise ValueError("proportional word quality must identify the fallback source")
        if self.quality == "interpolated" and self.start_origin != "interpolated":
            raise ValueError("interpolated word quality requires an interpolated start")
        return self


class SegmentTiming(BaseModel):
    """An ordered, nonoverlapping interval for one script segment."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    segment_id: str = Field(min_length=1, max_length=128)
    segment_index: int = Field(ge=0, lt=MAX_TIMING_WORDS)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    word_ids: list[str] = Field(min_length=1, max_length=MAX_TIMING_WORDS)

    @field_validator("segment_id")
    @classmethod
    def safe_segment_id(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("timing segment ID is invalid")
        return value

    @field_validator("word_ids")
    @classmethod
    def unique_word_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("segment timing word IDs must be unique")
        if any(re.fullmatch(r"word-[0-9a-f]{16}", item) is None for item in value):
            raise ValueError("segment timing contains an invalid word ID")
        return value

    @model_validator(mode="after")
    def ordered_interval(self) -> SegmentTiming:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("segment timing interval must have positive duration")
        return self


class TimingAlignmentStats(BaseModel):
    """Deterministic alignment accounting retained even when timing falls back."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    observation_source: ObservationSource | None = None
    script_word_count: int = Field(ge=1, le=MAX_TIMING_WORDS)
    provider_word_count: int = Field(ge=0, le=MAX_TIMING_WORDS * 4)
    matched_word_count: int = Field(ge=0, le=MAX_TIMING_WORDS)
    insertion_count: int = Field(ge=0, le=MAX_TIMING_WORDS * 4)
    deletion_count: int = Field(ge=0, le=MAX_TIMING_WORDS)
    substitution_count: int = Field(ge=0, le=MAX_TIMING_WORDS)
    edit_distance: int = Field(ge=0, le=MAX_TIMING_WORDS * 5)
    word_error_rate: float = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    interpolated_word_count: int = Field(ge=0, le=MAX_TIMING_WORDS)
    proportional_word_count: int = Field(ge=0, le=MAX_TIMING_WORDS)
    fallback_reason: str | None = Field(default=None, min_length=1, max_length=400)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> TimingAlignmentStats:
        if (
            self.matched_word_count + self.deletion_count + self.substitution_count
            != self.script_word_count
        ):
            raise ValueError("alignment script word accounting is inconsistent")
        if (
            self.matched_word_count + self.insertion_count + self.substitution_count
            != self.provider_word_count
        ):
            raise ValueError("alignment provider word accounting is inconsistent")
        if (
            self.insertion_count + self.deletion_count + self.substitution_count
            != self.edit_distance
        ):
            raise ValueError("alignment edit accounting is inconsistent")
        expected_error_rate = self.edit_distance / self.script_word_count
        expected_coverage = self.matched_word_count / self.script_word_count
        if abs(self.word_error_rate - expected_error_rate) > 1e-9:
            raise ValueError("alignment word error rate does not match its counts")
        if abs(self.coverage - expected_coverage) > 1e-9:
            raise ValueError("alignment coverage does not match its counts")
        return self


class NarrationTimingManifest(BaseModel):
    """Strict provenance for narration timing projected onto approved words."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)

    schema_version: Literal["1.0.0"] = "1.0.0"
    timing_id: str = Field(pattern=r"^timing-[0-9a-f]{16}$")
    source: TimingSource
    quality: ManifestTimingQuality
    audio_asset_id: str = Field(min_length=1, max_length=128)
    audio_path: str
    audio_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_duration_seconds: float = Field(gt=0)
    script_version_id: str = Field(min_length=1, max_length=128)
    script_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_approval_hashes: dict[str, str]
    synthesis_id: str | None = Field(default=None, pattern=r"^synthesis-[0-9a-f]{16}$")
    synthesis_receipt_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    segments: list[SegmentTiming] = Field(min_length=1, max_length=MAX_TIMING_WORDS)
    words: list[WordTiming] = Field(min_length=1, max_length=MAX_TIMING_WORDS)
    alignment: TimingAlignmentStats
    created_at: datetime = Field(default_factory=now_utc)

    @field_validator("audio_asset_id", "script_version_id")
    @classmethod
    def safe_identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("timing manifest identifier is invalid")
        return value

    @field_validator("audio_path")
    @classmethod
    def project_relative_audio_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not value.strip():
            raise ValueError("timing audio path must be project-relative and traversal-free")
        return str(path)

    @field_validator("segment_approval_hashes")
    @classmethod
    def valid_segment_approval_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("timing manifest requires approved script segments")
        if any(
            not _IDENTIFIER.fullmatch(key) or not _HASH.fullmatch(digest)
            for key, digest in value.items()
        ):
            raise ValueError("timing manifest contains invalid segment approval hashes")
        return value

    @field_validator("created_at")
    @classmethod
    def aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timing manifest timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def complete_ordered_projection_and_identity(self) -> NarrationTimingManifest:
        if (self.synthesis_id is None) != (self.synthesis_receipt_hash is None):
            raise ValueError("synthesis ID and receipt hash must be supplied together")
        if len(self.words) != self.alignment.script_word_count:
            raise ValueError("timing words do not match alignment script word count")
        if [word.global_word_index for word in self.words] != list(range(len(self.words))):
            raise ValueError("timing words must have contiguous global indexes")
        if len({word.word_id for word in self.words}) != len(self.words):
            raise ValueError("timing word IDs must be unique")
        for left, right in zip(self.words, self.words[1:], strict=False):
            if left.end_seconds > right.start_seconds + _TIMING_TOLERANCE:
                raise ValueError("timing word intervals must be ordered and nonoverlapping")
        if any(
            word.end_seconds > self.audio_duration_seconds + _TIMING_TOLERANCE
            for word in self.words
        ):
            raise ValueError("timing word falls outside the active audio duration")

        expected_segment_indexes = list(range(len(self.segments)))
        if [segment.segment_index for segment in self.segments] != expected_segment_indexes:
            raise ValueError("segment timing indexes must be contiguous")
        if len({segment.segment_id for segment in self.segments}) != len(self.segments):
            raise ValueError("segment timing IDs must be unique")
        if set(self.segment_approval_hashes) != {segment.segment_id for segment in self.segments}:
            raise ValueError("segment timings must match the approved-segment hash set")
        words_by_segment: dict[str, list[WordTiming]] = {
            segment.segment_id: [] for segment in self.segments
        }
        for word in self.words:
            if word.segment_id not in words_by_segment:
                raise ValueError("timing word references an undeclared script segment")
            words_by_segment[word.segment_id].append(word)
        flattened_ids: list[str] = []
        for segment in self.segments:
            linked = words_by_segment[segment.segment_id]
            if [word.segment_word_index for word in linked] != list(range(len(linked))):
                raise ValueError("segment word indexes must be contiguous")
            linked_ids = [word.word_id for word in linked]
            if linked_ids != segment.word_ids:
                raise ValueError("segment timing word order does not match timing words")
            if (
                segment.start_seconds > linked[0].start_seconds + _TIMING_TOLERANCE
                or segment.end_seconds + _TIMING_TOLERANCE < linked[-1].end_seconds
            ):
                raise ValueError("segment interval does not contain its word timings")
            if segment.end_seconds > self.audio_duration_seconds + _TIMING_TOLERANCE:
                raise ValueError("segment timing falls outside the active audio duration")
            flattened_ids.extend(linked_ids)
        if flattened_ids != [word.word_id for word in self.words]:
            raise ValueError("timing words must be grouped in ordered script segments")
        for segment_left, segment_right in zip(self.segments, self.segments[1:], strict=False):
            if segment_left.end_seconds > segment_right.start_seconds + _TIMING_TOLERANCE:
                raise ValueError("segment timing intervals must be ordered and nonoverlapping")

        proportional_count = sum(word.quality == "proportional-fallback" for word in self.words)
        interpolated_count = sum(word.quality == "interpolated" for word in self.words)
        if proportional_count != self.alignment.proportional_word_count:
            raise ValueError("alignment proportional count does not match timing words")
        if interpolated_count != self.alignment.interpolated_word_count:
            raise ValueError("alignment interpolation count does not match timing words")
        if self.source == "proportional-fallback" and (
            self.quality != "proportional-fallback" or proportional_count != len(self.words)
        ):
            raise ValueError("fallback manifest must label every word as proportional")
        if self.quality == "engine-reported" and any(
            word.quality != "engine-reported" for word in self.words
        ):
            raise ValueError("engine-reported manifest contains non-engine timing")
        if self.quality == "asr-aligned" and any(
            word.quality != "asr-aligned" for word in self.words
        ):
            raise ValueError("ASR-aligned manifest contains non-ASR timing")

        expected_id = derive_narration_timing_id(self.model_dump(mode="json"))
        if self.timing_id != expected_id:
            raise ValueError("timing manifest ID does not match its exact content")
        return self


def derive_narration_timing_id(payload: dict[str, object]) -> str:
    identity: dict[str, object] = {
        "synthesis_id": None,
        "synthesis_receipt_hash": None,
    }
    identity.update(
        {
            key: value
            for key, value in payload.items()
            if key not in {"schema_version", "timing_id", "created_at"}
        }
    )
    return "timing-" + stable_hash(identity)[:16]


@dataclass(frozen=True)
class TimingProjection:
    source: TimingSource
    quality: ManifestTimingQuality
    segments: tuple[SegmentTiming, ...]
    words: tuple[WordTiming, ...]
    alignment: TimingAlignmentStats


@dataclass(frozen=True)
class _ObservedToken:
    canonical: str
    start_seconds: float
    end_seconds: float | None
    confidence: float | None


def _flatten_observations(
    observations: list[EngineWordObservation], audio_duration_seconds: float
) -> tuple[_ObservedToken, ...]:
    if [item.sequence_index for item in observations] != list(range(len(observations))):
        raise ValueError("engine observations must have contiguous sequence indexes")
    if len(observations) > MAX_TIMING_WORDS * 4:
        raise ValueError("engine observations exceed the timing safety bound")
    previous_start = -1.0
    flattened: list[_ObservedToken] = []
    for observation in observations:
        if observation.start_seconds < previous_start:
            raise ValueError("engine observations must be ordered by audio position")
        if observation.start_seconds >= audio_duration_seconds:
            raise ValueError("engine observation starts outside the active audio duration")
        if (
            observation.end_seconds is not None
            and observation.end_seconds > audio_duration_seconds + _TIMING_TOLERANCE
        ):
            raise ValueError("engine observation ends outside the active audio duration")
        previous_start = observation.start_seconds
        tokens = _WORD_PATTERN.findall(
            unicodedata.normalize("NFKC", observation.text).casefold().replace("\u2019", "'")
        )
        if not tokens:
            continue
        if len(flattened) + len(tokens) > MAX_TIMING_WORDS * 4:
            raise ValueError("engine word tokens exceed the timing safety bound")
        if observation.end_seconds is not None and len(tokens) > 1:
            token_duration = (observation.end_seconds - observation.start_seconds) / len(tokens)
        else:
            token_duration = None
        for index, token in enumerate(tokens):
            start = (
                observation.start_seconds + token_duration * index
                if token_duration is not None
                else observation.start_seconds
            )
            end = (
                observation.start_seconds + token_duration * (index + 1)
                if token_duration is not None
                else observation.end_seconds
            )
            flattened.append(_ObservedToken(token, start, end, observation.confidence))
    return tuple(flattened)


def _alignment_path(
    reference: tuple[str, ...], hypothesis: tuple[str, ...]
) -> tuple[dict[int, int], int, int, int]:
    """Return exact match indexes and deterministic Levenshtein operation counts."""

    rows = len(reference)
    columns = len(hypothesis)
    # One direction byte per cell keeps the bounded 2,000 x 8,000 case finite.
    directions = [bytearray(columns + 1) for _ in range(rows + 1)]
    for column in range(1, columns + 1):
        directions[0][column] = 2  # insertion / left
    previous = list(range(columns + 1))
    for row in range(1, rows + 1):
        directions[row][0] = 1  # deletion / up
        current = [row]
        for column in range(1, columns + 1):
            substitution_cost = reference[row - 1] != hypothesis[column - 1]
            candidates = (
                (previous[column - 1] + int(substitution_cost), 0),
                (previous[column] + 1, 1),
                (current[column - 1] + 1, 2),
            )
            cost, direction = min(candidates)
            current.append(cost)
            directions[row][column] = direction
        previous = current

    matches: dict[int, int] = {}
    insertions = deletions = substitutions = 0
    row, column = rows, columns
    while row or column:
        direction = directions[row][column]
        if row and column and direction == 0:
            row -= 1
            column -= 1
            if reference[row] == hypothesis[column]:
                matches[row] = column
            else:
                substitutions += 1
        elif row and (not column or direction == 1):
            row -= 1
            deletions += 1
        else:
            column -= 1
            insertions += 1
    return matches, insertions, deletions, substitutions


def _baseline_boundaries(
    script: ScriptManifest,
    canonical: tuple[CanonicalScriptWord, ...],
    audio_duration_seconds: float,
) -> list[float]:
    script_duration = sum(segment.approximate_duration for segment in script.segments)
    scale = audio_duration_seconds / script_duration
    boundaries = [0.0] * (len(canonical) + 1)
    global_index = 0
    segment_start = 0.0
    for segment in script.segments:
        segment_words: list[CanonicalScriptWord] = []
        while global_index + len(segment_words) < len(canonical):
            word = canonical[global_index + len(segment_words)]
            if word.segment_id != segment.segment_id:
                break
            segment_words.append(word)
        segment_duration = segment.approximate_duration * scale
        weights = [max(1, len(word.canonical)) for word in segment_words]
        total_weight = sum(weights)
        elapsed_weight = 0
        for word, weight in zip(segment_words, weights, strict=True):
            boundaries[word.global_word_index] = (
                segment_start + segment_duration * elapsed_weight / total_weight
            )
            elapsed_weight += weight
        segment_start += segment_duration
        global_index += len(segment_words)
        boundaries[global_index] = segment_start
    boundaries[-1] = audio_duration_seconds
    return boundaries


def _proportional_projection(
    script: ScriptManifest,
    canonical: tuple[CanonicalScriptWord, ...],
    audio_duration_seconds: float,
    stats: TimingAlignmentStats,
) -> TimingProjection:
    boundaries = _baseline_boundaries(script, canonical, audio_duration_seconds)
    words = tuple(
        WordTiming(
            word_id=item.word_id,
            segment_id=item.segment_id,
            segment_word_index=item.segment_word_index,
            global_word_index=item.global_word_index,
            display_text=item.display_text,
            canonical=item.canonical,
            char_start=item.char_start,
            char_end=item.char_end,
            start_seconds=boundaries[index],
            end_seconds=boundaries[index + 1],
            source="proportional-fallback",
            quality="proportional-fallback",
            start_origin="proportional",
            end_origin=("audio-boundary" if index == len(canonical) - 1 else "proportional"),
        )
        for index, item in enumerate(canonical)
    )
    segments = _segments_from_words(script, words, boundaries)
    adjusted_stats = stats.model_copy(
        update={
            "interpolated_word_count": 0,
            "proportional_word_count": len(words),
        }
    )
    return TimingProjection(
        source="proportional-fallback",
        quality="proportional-fallback",
        segments=segments,
        words=words,
        alignment=adjusted_stats,
    )


def _segments_from_words(
    script: ScriptManifest,
    words: tuple[WordTiming, ...],
    boundaries: list[float],
) -> tuple[SegmentTiming, ...]:
    result: list[SegmentTiming] = []
    cursor = 0
    for segment_index, segment in enumerate(script.segments):
        linked: list[WordTiming] = []
        while cursor + len(linked) < len(words):
            word = words[cursor + len(linked)]
            if word.segment_id != segment.segment_id:
                break
            linked.append(word)
        if not linked:
            raise ValueError(f"script segment {segment.segment_id} contains no timing words")
        end_index = cursor + len(linked)
        result.append(
            SegmentTiming(
                segment_id=segment.segment_id,
                segment_index=segment_index,
                start_seconds=linked[0].start_seconds,
                end_seconds=boundaries[end_index],
                word_ids=[word.word_id for word in linked],
            )
        )
        cursor = end_index
    return tuple(result)


def proportional_timing_projection(
    script: ScriptManifest, audio_duration_seconds: float
) -> TimingProjection:
    """Build an explicitly labeled fallback projection without engine output."""

    if audio_duration_seconds <= 0:
        raise ValueError("timing audio duration must be positive")
    canonical = canonical_script_words(script)
    stats = TimingAlignmentStats(
        observation_source=None,
        script_word_count=len(canonical),
        provider_word_count=0,
        matched_word_count=0,
        insertion_count=0,
        deletion_count=len(canonical),
        substitution_count=0,
        edit_distance=len(canonical),
        word_error_rate=1.0,
        coverage=0.0,
        interpolated_word_count=0,
        proportional_word_count=len(canonical),
        fallback_reason="no engine word observations were supplied",
    )
    return _proportional_projection(script, canonical, audio_duration_seconds, stats)


def proportional_segment_timing_projection(
    script: ScriptManifest,
    audio_duration_seconds: float,
    segment_intervals: list[tuple[str, float, float]],
) -> TimingProjection:
    """Project words only inside exact receipted segment PCM intervals."""

    if audio_duration_seconds <= 0:
        raise ValueError("timing audio duration must be positive")
    if [item[0] for item in segment_intervals] != [
        segment.segment_id for segment in script.segments
    ]:
        raise ValueError("receipted timing intervals must match ordered script segments")
    for index, (_segment_id, start, end) in enumerate(segment_intervals):
        if start < 0 or end <= start or end > audio_duration_seconds + _TIMING_TOLERANCE:
            raise ValueError("receipted segment interval is outside the active audio duration")
        if index and start < segment_intervals[index - 1][2] - _TIMING_TOLERANCE:
            raise ValueError("receipted segment intervals must be ordered and nonoverlapping")

    canonical = canonical_script_words(script)
    words: list[WordTiming] = []
    segments: list[SegmentTiming] = []
    canonical_cursor = 0
    for segment_index, (segment_id, start, end) in enumerate(segment_intervals):
        linked: list[CanonicalScriptWord] = []
        while canonical_cursor + len(linked) < len(canonical):
            word = canonical[canonical_cursor + len(linked)]
            if word.segment_id != segment_id:
                break
            linked.append(word)
        if not linked:
            raise ValueError(f"script segment {segment_id} contains no timing words")
        weights = [max(1, len(word.canonical)) for word in linked]
        total_weight = sum(weights)
        elapsed_weight = 0
        segment_words: list[WordTiming] = []
        for word_index, (word, weight) in enumerate(zip(linked, weights, strict=True)):
            word_start = start + (end - start) * elapsed_weight / total_weight
            elapsed_weight += weight
            word_end = (
                end
                if word_index == len(linked) - 1
                else start + (end - start) * elapsed_weight / total_weight
            )
            segment_words.append(
                WordTiming(
                    word_id=word.word_id,
                    segment_id=word.segment_id,
                    segment_word_index=word.segment_word_index,
                    global_word_index=word.global_word_index,
                    display_text=word.display_text,
                    canonical=word.canonical,
                    char_start=word.char_start,
                    char_end=word.char_end,
                    start_seconds=word_start,
                    end_seconds=word_end,
                    source="proportional-fallback",
                    quality="proportional-fallback",
                    start_origin="proportional",
                    end_origin=(
                        "segment-boundary" if word_index == len(linked) - 1 else "proportional"
                    ),
                )
            )
        words.extend(segment_words)
        segments.append(
            SegmentTiming(
                segment_id=segment_id,
                segment_index=segment_index,
                start_seconds=start,
                end_seconds=end,
                word_ids=[word.word_id for word in segment_words],
            )
        )
        canonical_cursor += len(linked)
    stats = TimingAlignmentStats(
        observation_source=None,
        script_word_count=len(canonical),
        provider_word_count=0,
        matched_word_count=0,
        insertion_count=0,
        deletion_count=len(canonical),
        substitution_count=0,
        edit_distance=len(canonical),
        word_error_rate=1.0,
        coverage=0.0,
        interpolated_word_count=0,
        proportional_word_count=len(canonical),
        fallback_reason="synthesis receipt contains no word-boundary events",
    )
    return TimingProjection(
        source="proportional-fallback",
        quality="proportional-fallback",
        segments=tuple(segments),
        words=tuple(words),
        alignment=stats,
    )


def align_engine_observations(
    script: ScriptManifest,
    observations: list[EngineWordObservation],
    *,
    audio_duration_seconds: float,
    source: ObservationSource,
    minimum_coverage: float = DEFAULT_MINIMUM_ALIGNMENT_COVERAGE,
    maximum_word_error_rate: float = DEFAULT_MAXIMUM_WORD_ERROR_RATE,
    maximum_interpolated_gap_words: int = DEFAULT_MAXIMUM_INTERPOLATED_GAP_WORDS,
) -> TimingProjection:
    """Align inert engine words to approved tokens without adopting engine prose.

    Only exact normalized token matches receive observed times. Inserted provider
    words are never projected into caption content. Small internal deletion gaps
    may be interpolated; every other gap is explicitly proportional. Low-quality
    or impossible alignments return a completely labeled proportional fallback.
    """

    if audio_duration_seconds <= 0:
        raise ValueError("timing audio duration must be positive")
    if not 0 <= minimum_coverage <= 1:
        raise ValueError("minimum alignment coverage must be between zero and one")
    if maximum_word_error_rate < 0:
        raise ValueError("maximum word error rate must be nonnegative")
    if not 0 <= maximum_interpolated_gap_words <= 20:
        raise ValueError("maximum interpolated gap must be between zero and twenty")

    canonical = canonical_script_words(script)
    provider = _flatten_observations(observations, audio_duration_seconds)
    matches, insertions, deletions, substitutions = _alignment_path(
        tuple(word.canonical for word in canonical),
        tuple(word.canonical for word in provider),
    )
    edit_distance = insertions + deletions + substitutions
    coverage = len(matches) / len(canonical)
    word_error_rate = edit_distance / len(canonical)
    base_stats = TimingAlignmentStats(
        observation_source=source,
        script_word_count=len(canonical),
        provider_word_count=len(provider),
        matched_word_count=len(matches),
        insertion_count=insertions,
        deletion_count=deletions,
        substitution_count=substitutions,
        edit_distance=edit_distance,
        word_error_rate=word_error_rate,
        coverage=coverage,
        interpolated_word_count=0,
        proportional_word_count=0,
    )
    if not provider:
        return _proportional_projection(
            script,
            canonical,
            audio_duration_seconds,
            base_stats.model_copy(update={"fallback_reason": "engine output contained no words"}),
        )
    if coverage < minimum_coverage or word_error_rate > maximum_word_error_rate:
        reason = (
            f"engine alignment quality was insufficient: {coverage:.1%} coverage, "
            f"{word_error_rate:.1%} word error"
        )
        return _proportional_projection(
            script,
            canonical,
            audio_duration_seconds,
            base_stats.model_copy(update={"fallback_reason": reason}),
        )

    baseline = _baseline_boundaries(script, canonical, audio_duration_seconds)
    anchors = {
        reference_index: provider[hypothesis_index]
        for reference_index, hypothesis_index in matches.items()
    }
    boundaries: list[float | None] = [None] * (len(canonical) + 1)
    boundary_origins: list[TimingOrigin | None] = [None] * (len(canonical) + 1)
    for reference_index, token in anchors.items():
        boundaries[reference_index] = token.start_seconds
        boundary_origins[reference_index] = (
            "engine-event" if source == "sapi-speak-progress" else "asr-event"
        )
    if boundaries[0] is None:
        boundaries[0] = 0.0
        boundary_origins[0] = "proportional"
    boundaries[-1] = audio_duration_seconds
    boundary_origins[-1] = "audio-boundary"

    known_indexes = [index for index, value in enumerate(boundaries) if value is not None]
    impossible_reason: str | None = None
    for left_index, right_index in zip(known_indexes, known_indexes[1:], strict=False):
        left_time = boundaries[left_index]
        right_time = boundaries[right_index]
        assert left_time is not None and right_time is not None
        if right_time <= left_time and right_index > left_index:
            impossible_reason = "engine word starts cannot form positive ordered intervals"
            break
        missing_count = right_index - left_index - 1
        if missing_count <= 0:
            continue
        observed_bounds = left_index in anchors and right_index in anchors
        same_segment = (
            observed_bounds
            and canonical[left_index].segment_id == canonical[right_index].segment_id
        )
        interpolate = same_segment and missing_count <= maximum_interpolated_gap_words
        baseline_span = baseline[right_index] - baseline[left_index]
        for index in range(left_index + 1, right_index):
            fraction = (
                (baseline[index] - baseline[left_index]) / baseline_span
                if baseline_span > 0
                else (index - left_index) / (right_index - left_index)
            )
            boundaries[index] = left_time + (right_time - left_time) * fraction
            boundary_origins[index] = "interpolated" if interpolate else "proportional"
    if impossible_reason is not None:
        return _proportional_projection(
            script,
            canonical,
            audio_duration_seconds,
            base_stats.model_copy(update={"fallback_reason": impossible_reason}),
        )
    if any(value is None for value in boundaries) or any(
        origin is None for origin in boundary_origins
    ):
        raise AssertionError("timing boundary projection left an unassigned value")
    concrete_boundaries = [cast(float, value) for value in boundaries]
    if any(
        right <= left
        for left, right in zip(concrete_boundaries, concrete_boundaries[1:], strict=False)
    ):
        return _proportional_projection(
            script,
            canonical,
            audio_duration_seconds,
            base_stats.model_copy(
                update={"fallback_reason": "aligned boundaries produced a zero-length word"}
            ),
        )

    words: list[WordTiming] = []
    for index, item in enumerate(canonical):
        start_origin = boundary_origins[index]
        next_origin = boundary_origins[index + 1]
        assert start_origin is not None and next_origin is not None
        observed = anchors.get(index)
        end = concrete_boundaries[index + 1]
        if (
            observed is not None
            and observed.end_seconds is not None
            and concrete_boundaries[index] < observed.end_seconds <= end + _TIMING_TOLERANCE
        ):
            end = min(observed.end_seconds, end)
            end_origin: TimingOrigin = (
                "engine-event" if source == "sapi-speak-progress" else "asr-event"
            )
        elif next_origin == "engine-event":
            end_origin = "next-engine-event"
        elif next_origin == "asr-event":
            end_origin = "next-asr-event"
        elif next_origin == "audio-boundary":
            end_origin = "audio-boundary"
        else:
            end_origin = next_origin

        if start_origin == "proportional":
            word_source: TimingSource = "proportional-fallback"
            word_quality: WordTimingQuality = "proportional-fallback"
        elif start_origin == "interpolated":
            word_source = source
            word_quality = "interpolated"
        elif source == "sapi-speak-progress":
            word_source = source
            word_quality = "engine-reported"
        else:
            word_source = source
            word_quality = "asr-aligned"
        words.append(
            WordTiming(
                word_id=item.word_id,
                segment_id=item.segment_id,
                segment_word_index=item.segment_word_index,
                global_word_index=item.global_word_index,
                display_text=item.display_text,
                canonical=item.canonical,
                char_start=item.char_start,
                char_end=item.char_end,
                start_seconds=concrete_boundaries[index],
                end_seconds=end,
                source=word_source,
                quality=word_quality,
                start_origin=start_origin,
                end_origin=end_origin,
                confidence=observed.confidence if observed is not None else None,
            )
        )

    word_tuple = tuple(words)
    proportional_count = sum(word.quality == "proportional-fallback" for word in words)
    interpolated_count = sum(word.quality == "interpolated" for word in words)
    stats = base_stats.model_copy(
        update={
            "interpolated_word_count": interpolated_count,
            "proportional_word_count": proportional_count,
        }
    )
    exact_quality: ManifestTimingQuality = (
        "engine-reported" if source == "sapi-speak-progress" else "asr-aligned"
    )
    quality: ManifestTimingQuality = (
        exact_quality if not proportional_count and not interpolated_count else "mixed"
    )
    return TimingProjection(
        source=source,
        quality=quality,
        segments=_segments_from_words(script, word_tuple, concrete_boundaries),
        words=word_tuple,
        alignment=stats,
    )


def validate_timing_projection(manifest: NarrationTimingManifest, script: ScriptManifest) -> None:
    """Verify that persisted timings are a complete projection of this script."""

    if manifest.script_version_id != script.version_id:
        raise ValueError("timing manifest targets a different script version")
    expected_approvals = {
        segment.segment_id: segment.approval_hash
        for segment in script.segments
        if segment.approval_hash is not None
    }
    if len(expected_approvals) != len(script.segments):
        raise ValueError("every timed script segment must have an approval hash")
    if manifest.segment_approval_hashes != expected_approvals:
        raise ValueError("timing manifest does not match current script approvals")
    expected = canonical_script_words(script)
    if len(expected) != len(manifest.words):
        raise ValueError("timing manifest is not a complete approved-script projection")
    for canonical, timed in zip(expected, manifest.words, strict=True):
        if (
            timed.word_id != canonical.word_id
            or timed.segment_id != canonical.segment_id
            or timed.segment_word_index != canonical.segment_word_index
            or timed.global_word_index != canonical.global_word_index
            or timed.display_text != canonical.display_text
            or timed.canonical != canonical.canonical
            or timed.char_start != canonical.char_start
            or timed.char_end != canonical.char_end
        ):
            raise ValueError("timing manifest word projection differs from approved script text")
    expected_segments = [segment.segment_id for segment in script.segments]
    if [segment.segment_id for segment in manifest.segments] != expected_segments:
        raise ValueError("timing manifest segment order differs from the approved script")
