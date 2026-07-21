from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.domain.hashing import stable_hash
from techshort.domain.models import now_utc
from techshort.domain.storage import ProjectStore


@dataclass(frozen=True)
class NarrationVoice:
    """One locally installed narration voice exposed without platform internals."""

    provider: str
    name: str
    culture: str
    gender: str
    age: str


@dataclass(frozen=True)
class SynthesizedNarration:
    """Registered audio and transcript produced from an approved script."""

    provider: str
    voice: NarrationVoice
    audio_path: Path
    transcript_path: Path
    receipt_path: Path
    duration_seconds: float
    rate: int
    volume: int


class NarrationEngineEvent(BaseModel):
    """One bounded word-progress event emitted by the local speech engine."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    spoken_text: str = Field(min_length=1, max_length=512)
    normalized_start_seconds: float = Field(ge=0)
    raw_character_position: int = Field(ge=0)
    raw_character_count: int = Field(gt=0)

    @field_validator("spoken_text")
    @classmethod
    def inert_spoken_text(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("speech progress text must be non-empty inert text")
        return value


class NarrationSegmentReceipt(BaseModel):
    """Exact normalized audio and engine provenance for one approved segment."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    segment_id: str = Field(min_length=1, max_length=128)
    order: int = Field(ge=0)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    engine_events: list[NarrationEngineEvent] = Field(min_length=1, max_length=4096)

    @field_validator("segment_id")
    @classmethod
    def inert_segment_id(cls, value: str) -> str:
        if "\x00" in value or "\r" in value or "\n" in value or not value.strip():
            raise ValueError("narration segment ID must be concise inert text")
        return value

    @field_validator("output_path")
    @classmethod
    def project_relative_output(cls, value: str) -> str:
        return _project_relative_path(value, "segment output")

    @model_validator(mode="after")
    def events_are_ordered_and_bounded(self) -> NarrationSegmentReceipt:
        starts = [event.normalized_start_seconds for event in self.engine_events]
        positions = [event.raw_character_position for event in self.engine_events]
        if starts != sorted(starts) or positions != sorted(positions):
            raise ValueError("speech progress events must preserve engine order")
        if starts[-1] > self.duration_seconds + 0.05:
            raise ValueError("speech progress event starts after its segment audio")
        return self


class NarrationConcatenationReceipt(BaseModel):
    """Deterministic PCM concatenation parameters for normalized segments."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    algorithm: Literal["pcm-s16le-zero-pause-v1"] = "pcm-s16le-zero-pause-v1"
    sample_rate_hz: Literal[48000] = 48000
    channels: Literal[1] = 1
    sample_width_bytes: Literal[2] = 2
    pause_milliseconds: Literal[140] = 140
    pause_frames: Literal[6720] = 6720
    output_frame_count: int = Field(gt=0)
    output_duration_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def duration_matches_frames(self) -> NarrationConcatenationReceipt:
        expected = self.output_frame_count / self.sample_rate_hz
        if abs(self.output_duration_seconds - expected) > 1e-9:
            raise ValueError("concatenation duration does not match its exact PCM frame count")
        return self


class NarrationSynthesisReceipt(BaseModel):
    """Strict provenance record for one registered synthetic narration."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal["1.0.0", "1.1.0"] = "1.0.0"
    synthesis_id: str = Field(pattern=r"^synthesis-[0-9a-f]{16}$")
    provider: Literal["windows-sapi"]
    voice_name: str = Field(min_length=1, max_length=200)
    voice_culture: str = Field(min_length=2, max_length=40)
    voice_gender: str = Field(min_length=1, max_length=40)
    voice_age: str = Field(min_length=1, max_length=40)
    rate: int = Field(ge=-10, le=10)
    volume: int = Field(ge=1, le=100)
    segment_pause_milliseconds: Literal[140] = 140
    script_version_id: str
    script_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_approval_hashes: dict[str, str]
    audio_asset_id: str
    output_path: str
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_duration_seconds: float = Field(gt=0)
    transcript_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    segments: list[NarrationSegmentReceipt] = Field(default_factory=list, max_length=4096)
    concatenation: NarrationConcatenationReceipt | None = None
    rights_status: Literal[
        "original",
        "user-owned",
        "permissively-licensed",
        "citation-only",
        "unknown",
        "restricted",
    ]
    license_name: str | None = None
    required_attribution: str | None = None
    created_at: datetime = Field(default_factory=now_utc)

    @field_validator("output_path")
    @classmethod
    def project_relative_output(cls, value: str) -> str:
        return _project_relative_path(value, "synthesis output")

    @field_validator("segment_approval_hashes")
    @classmethod
    def valid_approval_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("synthesis receipt requires approved script segments")
        if any(
            not key.strip()
            or len(key) > 128
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for key, digest in value.items()
        ):
            raise ValueError("synthesis receipt contains invalid segment approval hashes")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("synthesis receipt timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def identity_matches_content(self) -> NarrationSynthesisReceipt:
        if self.schema_version == "1.0.0":
            if self.segments or self.concatenation is not None:
                raise ValueError("legacy synthesis receipts may not contain segmented audio data")
        else:
            if not self.segments or self.concatenation is None:
                raise ValueError("segmented synthesis receipts require segments and concatenation")
            orders = [segment.order for segment in self.segments]
            segment_ids = [segment.segment_id for segment in self.segments]
            if orders != list(range(len(self.segments))) or len(set(segment_ids)) != len(
                segment_ids
            ):
                raise ValueError("segmented synthesis receipts require unique ordered segments")
            if {
                segment.segment_id: segment.approval_hash for segment in self.segments
            } != self.segment_approval_hashes:
                raise ValueError("segment receipts do not match approved segment hashes")
            expected_frames = (
                sum(segment.frame_count for segment in self.segments)
                + (len(self.segments) - 1) * self.concatenation.pause_frames
            )
            if self.concatenation.output_frame_count != expected_frames:
                raise ValueError("concatenation frame count does not match its ordered segments")
            if (
                abs(self.output_duration_seconds - self.concatenation.output_duration_seconds)
                > 1e-9
            ):
                raise ValueError("synthesis duration does not match concatenation duration")
        if self.synthesis_id != derive_synthesis_id(self.model_dump(mode="json")):
            raise ValueError("synthesis receipt ID does not match its exact content")
        return self


def _project_relative_path(value: str, label: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not value.strip():
        raise ValueError(f"{label} path must be project-relative and traversal-free")
    return str(path)


def derive_synthesis_id(payload: dict[str, object]) -> str:
    schema_version = payload.get("schema_version", "1.0.0")
    identity: dict[str, object] = {
        "segment_pause_milliseconds": 140,
        "license_name": None,
        "required_attribution": None,
    }
    identity.update(
        {
            key: value
            for key, value in payload.items()
            if key not in {"schema_version", "synthesis_id", "created_at"}
            and not (schema_version == "1.0.0" and key in {"segments", "concatenation"})
        }
    )
    return f"synthesis-{stable_hash(identity)[:16]}"


class NarrationProvider(Protocol):
    """A local provider that produces inert media, never executable project data."""

    provider_id: str

    def readiness(self) -> tuple[bool, str]: ...

    def list_voices(self) -> list[NarrationVoice]: ...

    def synthesize(
        self,
        store: ProjectStore,
        *,
        voice_name: str | None = None,
        rate: int = 1,
        volume: int = 100,
        rights_status: str = "unknown",
        license_name: str | None = None,
        required_attribution: str | None = None,
    ) -> SynthesizedNarration: ...
