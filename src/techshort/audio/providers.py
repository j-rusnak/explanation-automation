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


class NarrationSynthesisReceipt(BaseModel):
    """Strict provenance record for one registered synthetic narration."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal["1.0.0"] = "1.0.0"
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
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not value.strip():
            raise ValueError("synthesis output path must be project-relative and traversal-free")
        return str(path)

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
        if self.synthesis_id != derive_synthesis_id(self.model_dump(mode="json")):
            raise ValueError("synthesis receipt ID does not match its exact content")
        return self


def derive_synthesis_id(payload: dict[str, object]) -> str:
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
