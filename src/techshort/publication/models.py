from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.domain.hashing import stable_hash
from techshort.domain.models import validate_inert_text

PUBLICATION_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
OrganicPlatform = Literal["tiktok", "instagram-reels"]
ConsentState = Literal["pending", "granted", "declined", "revoked"]
ArtifactRole = Literal[
    "video",
    "cover",
    "captions-srt",
    "captions-vtt",
    "metadata",
    "checklist",
    "consent",
]

GRANT_CONFIRMATION = "I explicitly authorize manual publication of this exact variant package."
_EXPERIMENT_ID = re.compile(r"^exp-[0-9a-f]{16}$")
_VARIANT_ID = re.compile(r"^var-[0-9a-f]{16}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HASHTAG = re.compile(r"^[A-Za-z0-9_]{1,40}$")


class PublicationStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal["1.0.0"] = PUBLICATION_SCHEMA_VERSION


def _content_hash(model: BaseModel, *excluded: str) -> str:
    payload = model.model_dump(mode="json")
    for field in excluded:
        payload.pop(field, None)
    return stable_hash(payload)


class OrganicPackageRequest(PublicationStrictModel):
    experiment_id: str = Field(pattern=r"^exp-[0-9a-f]{16}$")
    variant_id: str = Field(pattern=r"^var-[0-9a-f]{16}$")
    platform: OrganicPlatform
    final_mp4: str = Field(min_length=1, max_length=500)
    expected_media_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cover_png: str = Field(min_length=1, max_length=500)
    expected_cover_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    captions_srt: str = Field(min_length=1, max_length=500)
    captions_vtt: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=120)
    post_copy: str = Field(min_length=1, max_length=1800)
    alt_text: str = Field(min_length=1, max_length=1000)
    hashtags: list[str] = Field(default_factory=list, max_length=8)
    evidence_url: str | None = Field(default=None, max_length=500)

    @field_validator("final_mp4", "cover_png", "captions_srt", "captions_vtt")
    @classmethod
    def paths_are_inert(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("publication artifact paths cannot contain NUL bytes")
        return value

    @field_validator("title", "post_copy", "alt_text")
    @classmethod
    def text_is_inert(cls, value: str) -> str:
        return validate_inert_text(value)

    @field_validator("hashtags")
    @classmethod
    def hashtags_are_bounded_and_unique(cls, value: list[str]) -> list[str]:
        normalized = [item.removeprefix("#") for item in value]
        if any(_HASHTAG.fullmatch(item) is None for item in normalized):
            raise ValueError("hashtags may contain only letters, digits, and underscores")
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("hashtags must be unique")
        return normalized

    @field_validator("evidence_url")
    @classmethod
    def evidence_url_is_public_http(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("evidence URL must be an absolute HTTP or HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("evidence URL cannot contain credentials")
        return value


class HumanPublicationConsent(PublicationStrictModel):
    receipt_id: str = Field(pattern=r"^organic-consent-[0-9a-f]{16}$")
    experiment_id: str = Field(pattern=r"^exp-[0-9a-f]{16}$")
    variant_id: str = Field(pattern=r"^var-[0-9a-f]{16}$")
    platform: OrganicPlatform
    package_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: ConsentState
    reviewer_identifier: str | None = Field(default=None, min_length=1, max_length=120)
    confirmation: str | None = Field(default=None, max_length=500)
    decided_at: datetime | None = None
    supersedes_receipt_id: str | None = Field(
        default=None, pattern=r"^organic-consent-[0-9a-f]{16}$"
    )

    @field_validator("reviewer_identifier", "confirmation")
    @classmethod
    def decision_text_is_inert(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None

    @field_validator("decided_at")
    @classmethod
    def decision_time_is_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("publication consent time must include a timezone")
        return value

    @model_validator(mode="after")
    def state_and_hash_are_consistent(self) -> HumanPublicationConsent:
        if self.state == "pending":
            if any(
                value is not None
                for value in (
                    self.reviewer_identifier,
                    self.confirmation,
                    self.decided_at,
                    self.supersedes_receipt_id,
                )
            ):
                raise ValueError("pending publication consent cannot contain a decision")
        else:
            if self.reviewer_identifier is None or self.decided_at is None:
                raise ValueError("publication consent decisions require a local reviewer and time")
            if self.state == "granted" and self.confirmation != GRANT_CONFIRMATION:
                raise ValueError("granted publication consent requires the exact confirmation")
            if self.state in {"declined", "revoked"} and not self.confirmation:
                raise ValueError("declined or revoked publication consent requires a note")
        expected = f"organic-consent-{_content_hash(self, 'receipt_id')[:16]}"
        if self.receipt_id != expected:
            raise ValueError("publication consent receipt ID does not match its content")
        return self


class PlatformProviderDiagnostic(PublicationStrictModel):
    provider_name: str = Field(min_length=1, max_length=120)
    platform: OrganicPlatform
    status: Literal["manual-ready", "unavailable"]
    local_package_supported: bool
    automated_publication_supported: Literal[False] = False
    credentials_read: Literal[False] = False
    credentials_stored: Literal[False] = False
    reason: str = Field(min_length=1, max_length=800)
    next_steps: list[str] = Field(min_length=1, max_length=8)


class OrganicPostMetadata(PublicationStrictModel):
    metadata_id: str = Field(pattern=r"^organic-metadata-[0-9a-f]{16}$")
    experiment_id: str = Field(pattern=r"^exp-[0-9a-f]{16}$")
    variant_id: str = Field(pattern=r"^var-[0-9a-f]{16}$")
    platform: OrganicPlatform
    title: str
    caption_text: str = Field(min_length=1, max_length=2200)
    alt_text: str = Field(min_length=1, max_length=1000)
    hashtags: list[str] = Field(max_length=8)
    evidence_url: str | None = None
    video_filename: Literal["video.mp4"] = "video.mp4"
    cover_filename: Literal["cover.png"] = "cover.png"
    captions_srt_filename: Literal["captions.srt"] = "captions.srt"
    captions_vtt_filename: Literal["captions.vtt"] = "captions.vtt"
    aspect_ratio: Literal["9:16"] = "9:16"
    expected_dimensions: Literal["1080x1920"] = "1080x1920"
    duration_window_seconds: tuple[Literal[45], Literal[75]] = (45, 75)
    consent_receipt_id: str = Field(pattern=r"^organic-consent-[0-9a-f]{16}$")
    consent_state: ConsentState
    manual_upload_authorized: bool
    automated_upload: Literal[False] = False
    claimed_posted: Literal[False] = False
    metadata_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def authorization_and_hash_are_consistent(self) -> OrganicPostMetadata:
        if self.manual_upload_authorized != (self.consent_state == "granted"):
            raise ValueError("manual upload authorization must match human consent")
        expected = _content_hash(self, "metadata_hash", "metadata_id")
        if self.metadata_hash != expected:
            raise ValueError("organic post metadata hash does not match its content")
        expected_id = f"organic-metadata-{expected[:16]}"
        if self.metadata_id != expected_id:
            raise ValueError("organic post metadata ID does not match its content")
        return self


class PublicationPackageFile(PublicationStrictModel):
    role: ArtifactRole
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)


class OrganicPublicationPackage(PublicationStrictModel):
    package_id: str = Field(pattern=r"^organic-package-[0-9a-f]{16}$")
    experiment_id: str = Field(pattern=r"^exp-[0-9a-f]{16}$")
    variant_id: str = Field(pattern=r"^var-[0-9a-f]{16}$")
    platform: OrganicPlatform
    provider_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    package_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_media_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_cover_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locked_factual_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    limitation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    consent: HumanPublicationConsent
    metadata_id: str = Field(pattern=r"^organic-metadata-[0-9a-f]{16}$")
    metadata_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    files: list[PublicationPackageFile] = Field(min_length=7, max_length=7)
    manual_upload_authorized: bool
    automated_upload: Literal[False] = False
    claimed_posted: Literal[False] = False
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def bindings_and_hashes_are_consistent(self) -> OrganicPublicationPackage:
        if (
            self.consent.experiment_id != self.experiment_id
            or self.consent.variant_id != self.variant_id
            or self.consent.platform != self.platform
            or self.consent.package_input_hash != self.package_input_hash
        ):
            raise ValueError("publication consent does not bind this exact package input")
        if self.manual_upload_authorized != (self.consent.state == "granted"):
            raise ValueError("package authorization must match human consent")
        roles = [item.role for item in self.files]
        if len(set(roles)) != len(roles) or set(roles) != {
            "video",
            "cover",
            "captions-srt",
            "captions-vtt",
            "metadata",
            "checklist",
            "consent",
        }:
            raise ValueError("publication package files must contain only the allowlisted roles")
        expected_filenames: dict[ArtifactRole, str] = {
            "video": "video.mp4",
            "cover": "cover.png",
            "captions-srt": "captions.srt",
            "captions-vtt": "captions.vtt",
            "metadata": "post-metadata.json",
            "checklist": "checklist.md",
            "consent": "consent-receipt.json",
        }
        files_by_role = {item.role: item for item in self.files}
        if any(
            files_by_role[role].filename != filename
            for role, filename in expected_filenames.items()
        ):
            raise ValueError("publication package filenames must use the canonical allowlist")
        if files_by_role["video"].sha256 != self.variant_media_hash:
            raise ValueError("publication video checksum does not match the reviewed variant")
        if files_by_role["cover"].sha256 != self.variant_cover_hash:
            raise ValueError("publication cover checksum does not match the reviewed variant")
        if not _EXPERIMENT_ID.fullmatch(self.experiment_id) or not _VARIANT_ID.fullmatch(
            self.variant_id
        ):
            raise ValueError("publication package IDs are unsafe")
        if not _SHA256.fullmatch(self.metadata_hash):
            raise ValueError("publication metadata hash is invalid")
        expected_package_id = (
            "organic-package-"
            + stable_hash(
                {
                    "schema_version": self.schema_version,
                    "experiment_id": self.experiment_id,
                    "variant_id": self.variant_id,
                    "platform": self.platform,
                    "provider_name": self.provider_name,
                    "package_input_hash": self.package_input_hash,
                    "consent_receipt_id": self.consent.receipt_id,
                }
            )[:16]
        )
        if self.package_id != expected_package_id:
            raise ValueError("organic package ID does not match its immutable inputs")
        expected_hash = _content_hash(self, "package_hash")
        if self.package_hash != expected_hash:
            raise ValueError("organic publication package hash does not match its content")
        return self


class OrganicPackageBuildResult(PublicationStrictModel):
    package_directory: str
    manifest: OrganicPublicationPackage

    @field_validator("package_directory")
    @classmethod
    def package_directory_is_relative(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("package directory must be project-relative")
        return path.as_posix()
