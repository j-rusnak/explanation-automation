from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.domain.hashing import stable_hash
from techshort.domain.models import validate_inert_text

UPLOAD_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
TIKTOK_UPLOAD_PROVIDER: Literal["tiktok-content-posting-api"] = "tiktok-content-posting-api"
DRAFT_TRANSFER_OPERATION: Literal["draft-transfer"] = "draft-transfer"
DRAFT_TRANSFER_CONFIRMATION = (
    "I explicitly authorize transfer of this exact package to the identified "
    "TikTok account as a draft."
)

TikTokUploadConsentState = Literal["pending", "granted", "declined", "revoked"]
TikTokUploadState = Literal[
    "initialized",
    "uploaded",
    "pending-user-action",
    "complete",
    "failed",
    "ambiguous",
    "cancelled",
]
TikTokPreflightCheckState = Literal["pass", "warning", "failure"]

_INERT_CODE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


class TikTokUploadStrictModel(BaseModel):
    """Immutable, versioned base for persisted TikTok upload records."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )
    schema_version: Literal["1.0.0"] = UPLOAD_SCHEMA_VERSION


def _content_hash(model: BaseModel, *excluded: str) -> str:
    payload = model.model_dump(mode="json")
    for field_name in excluded:
        payload.pop(field_name, None)
    return stable_hash(payload)


def _validate_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return value


def _validate_optional_aware(value: datetime | None, label: str) -> datetime | None:
    return _validate_aware(value, label) if value is not None else None


def _validate_inert_nonempty(value: str, label: str) -> str:
    validated = validate_inert_text(value)
    if not validated.strip():
        raise ValueError(f"{label} cannot be blank")
    return validated


class TikTokDraftUploadIntent(TikTokUploadStrictModel):
    """Human-readable request bound to one package, video, and TikTok subject."""

    intent_id: str = Field(pattern=r"^tiktok-upload-intent-[0-9a-f]{16}$")
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_id: str = Field(pattern=r"^organic-package-[0-9a-f]{16}$")
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_id: str = Field(pattern=r"^exp-[0-9a-f]{16}$")
    variant_id: str = Field(pattern=r"^var-[0-9a-f]{16}$")
    video_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: Literal["tiktok-content-posting-api"] = TIKTOK_UPLOAD_PROVIDER
    operation: Literal["draft-transfer"] = DRAFT_TRANSFER_OPERATION
    target_account_subject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_account_label: str = Field(min_length=1, max_length=160)
    requested_by: str = Field(min_length=1, max_length=120)
    requested_at: datetime

    @field_validator("target_account_label", "requested_by")
    @classmethod
    def human_text_is_inert(cls, value: str) -> str:
        return _validate_inert_nonempty(value, "upload intent text")

    @field_validator("requested_at")
    @classmethod
    def request_time_is_aware(cls, value: datetime) -> datetime:
        return _validate_aware(value, "upload request time")

    @model_validator(mode="after")
    def identity_matches_content(self) -> TikTokDraftUploadIntent:
        expected_hash = _content_hash(self, "intent_id", "intent_hash")
        if self.intent_hash != expected_hash:
            raise ValueError("TikTok draft upload intent hash does not match its content")
        if self.intent_id != f"tiktok-upload-intent-{expected_hash[:16]}":
            raise ValueError("TikTok draft upload intent ID does not match its content")
        return self

    @classmethod
    def create(
        cls,
        *,
        package_id: str,
        package_hash: str,
        experiment_id: str,
        variant_id: str,
        video_hash: str,
        target_account_subject_sha256: str,
        target_account_label: str,
        requested_by: str,
        requested_at: datetime,
    ) -> Self:
        provisional = cls.model_construct(
            intent_id="tiktok-upload-intent-0000000000000000",
            intent_hash="0" * 64,
            package_id=package_id,
            package_hash=package_hash,
            experiment_id=experiment_id,
            variant_id=variant_id,
            video_hash=video_hash,
            provider=TIKTOK_UPLOAD_PROVIDER,
            operation=DRAFT_TRANSFER_OPERATION,
            target_account_subject_sha256=target_account_subject_sha256,
            target_account_label=target_account_label,
            requested_by=requested_by,
            requested_at=requested_at,
        )
        intent_hash = _content_hash(provisional, "intent_id", "intent_hash")
        payload = provisional.model_dump(mode="python")
        payload["intent_hash"] = intent_hash
        payload["intent_id"] = f"tiktok-upload-intent-{intent_hash[:16]}"
        return cls.model_validate(payload)


class TikTokDraftUploadConsent(TikTokUploadStrictModel):
    """Append-only human decision bound to one exact upload intent."""

    receipt_id: str = Field(pattern=r"^tiktok-upload-consent-[0-9a-f]{16}$")
    intent_id: str = Field(pattern=r"^tiktok-upload-intent-[0-9a-f]{16}$")
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_id: str = Field(pattern=r"^organic-package-[0-9a-f]{16}$")
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_account_subject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: TikTokUploadConsentState
    reviewer_identifier: str | None = Field(default=None, min_length=1, max_length=120)
    confirmation: str | None = Field(default=None, min_length=1, max_length=500)
    recorded_at: datetime
    decided_at: datetime | None = None
    supersedes_receipt_id: str | None = Field(
        default=None,
        pattern=r"^tiktok-upload-consent-[0-9a-f]{16}$",
    )

    @field_validator("reviewer_identifier", "confirmation")
    @classmethod
    def decision_text_is_inert(cls, value: str | None) -> str | None:
        return _validate_inert_nonempty(value, "upload consent text") if value is not None else None

    @field_validator("recorded_at")
    @classmethod
    def record_time_is_aware(cls, value: datetime) -> datetime:
        return _validate_aware(value, "upload consent record time")

    @field_validator("decided_at")
    @classmethod
    def decision_time_is_aware(cls, value: datetime | None) -> datetime | None:
        return _validate_optional_aware(value, "upload consent decision time")

    @model_validator(mode="after")
    def state_and_identity_are_consistent(self) -> TikTokDraftUploadConsent:
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
                raise ValueError("pending upload consent cannot contain a decision")
        else:
            if self.reviewer_identifier is None or self.decided_at is None:
                raise ValueError("upload consent decisions require a reviewer and decision time")
            if self.decided_at > self.recorded_at:
                raise ValueError("upload consent cannot be recorded before it was decided")
            if self.state == "granted" and self.confirmation != DRAFT_TRANSFER_CONFIRMATION:
                raise ValueError("granted upload consent requires the exact confirmation")
            if self.state in {"declined", "revoked"} and self.confirmation is None:
                raise ValueError("declined or revoked upload consent requires a note")
            if self.state == "revoked" and self.supersedes_receipt_id is None:
                raise ValueError("revoked upload consent must supersede an earlier receipt")
        if self.supersedes_receipt_id == self.receipt_id:
            raise ValueError("upload consent cannot supersede itself")
        expected_hash = _content_hash(self, "receipt_id")
        if self.receipt_id != f"tiktok-upload-consent-{expected_hash[:16]}":
            raise ValueError("TikTok upload consent receipt ID does not match its content")
        return self

    @classmethod
    def create(
        cls,
        intent: TikTokDraftUploadIntent,
        *,
        state: TikTokUploadConsentState,
        recorded_at: datetime,
        reviewer_identifier: str | None = None,
        confirmation: str | None = None,
        decided_at: datetime | None = None,
        supersedes_receipt_id: str | None = None,
    ) -> Self:
        provisional = cls.model_construct(
            receipt_id="tiktok-upload-consent-0000000000000000",
            intent_id=intent.intent_id,
            intent_hash=intent.intent_hash,
            package_id=intent.package_id,
            package_hash=intent.package_hash,
            target_account_subject_sha256=intent.target_account_subject_sha256,
            state=state,
            reviewer_identifier=reviewer_identifier,
            confirmation=confirmation,
            recorded_at=recorded_at,
            decided_at=decided_at,
            supersedes_receipt_id=supersedes_receipt_id,
        )
        receipt_hash = _content_hash(provisional, "receipt_id")
        payload = provisional.model_dump(mode="python")
        payload["receipt_id"] = f"tiktok-upload-consent-{receipt_hash[:16]}"
        return cls.model_validate(payload)


class TikTokDraftUploadAttempt(TikTokUploadStrictModel):
    """Pre-network attempt snapshot; subsequent facts belong in status receipts."""

    attempt_id: str = Field(pattern=r"^tiktok-upload-attempt-[0-9a-f]{16}$")
    attempt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intent: TikTokDraftUploadIntent
    consent: TikTokDraftUploadConsent
    provider: Literal["tiktok-content-posting-api"] = TIKTOK_UPLOAD_PROVIDER
    operation: Literal["draft-transfer"] = DRAFT_TRANSFER_OPERATION
    prepared_at: datetime
    network_started: Literal[False] = False

    @field_validator("prepared_at")
    @classmethod
    def prepared_time_is_aware(cls, value: datetime) -> datetime:
        return _validate_aware(value, "upload attempt preparation time")

    @model_validator(mode="after")
    def consent_and_identity_are_consistent(self) -> TikTokDraftUploadAttempt:
        if self.consent.state != "granted":
            raise ValueError("TikTok upload attempt requires granted human consent")
        if (
            self.consent.intent_id != self.intent.intent_id
            or self.consent.intent_hash != self.intent.intent_hash
            or self.consent.package_id != self.intent.package_id
            or self.consent.package_hash != self.intent.package_hash
            or self.consent.target_account_subject_sha256
            != self.intent.target_account_subject_sha256
        ):
            raise ValueError("TikTok upload consent does not bind this exact intent")
        expected_hash = _content_hash(self, "attempt_id", "attempt_hash")
        if self.attempt_hash != expected_hash:
            raise ValueError("TikTok upload attempt hash does not match its content")
        if self.attempt_id != f"tiktok-upload-attempt-{expected_hash[:16]}":
            raise ValueError("TikTok upload attempt ID does not match its content")
        return self

    @classmethod
    def create(
        cls,
        intent: TikTokDraftUploadIntent,
        consent: TikTokDraftUploadConsent,
        *,
        prepared_at: datetime,
    ) -> Self:
        provisional = cls.model_construct(
            attempt_id="tiktok-upload-attempt-0000000000000000",
            attempt_hash="0" * 64,
            intent=intent,
            consent=consent,
            provider=TIKTOK_UPLOAD_PROVIDER,
            operation=DRAFT_TRANSFER_OPERATION,
            prepared_at=prepared_at,
            network_started=False,
        )
        attempt_hash = _content_hash(provisional, "attempt_id", "attempt_hash")
        payload = provisional.model_dump(mode="python")
        payload["attempt_hash"] = attempt_hash
        payload["attempt_id"] = f"tiktok-upload-attempt-{attempt_hash[:16]}"
        return cls.model_validate(payload)


class TikTokDraftUploadStatusReceipt(TikTokUploadStrictModel):
    """One append-only observation about an immutable upload attempt."""

    receipt_id: str = Field(pattern=r"^tiktok-upload-status-[0-9a-f]{16}$")
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt_id: str = Field(pattern=r"^tiktok-upload-attempt-[0-9a-f]{16}$")
    attempt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intent_id: str = Field(pattern=r"^tiktok-upload-intent-[0-9a-f]{16}$")
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: Literal["tiktok-content-posting-api"] = TIKTOK_UPLOAD_PROVIDER
    operation: Literal["draft-transfer"] = DRAFT_TRANSFER_OPERATION
    sequence_number: int = Field(ge=0)
    state: TikTokUploadState
    previous_receipt_id: str | None = Field(
        default=None,
        pattern=r"^tiktok-upload-status-[0-9a-f]{16}$",
    )
    previous_state: TikTokUploadState | None = None
    publish_id: str | None = Field(default=None, min_length=1, max_length=240)
    error_code: str | None = Field(default=None, min_length=1, max_length=120)
    error_message: str | None = Field(default=None, min_length=1, max_length=1000)
    recorded_at: datetime
    provider_updated_at: datetime | None = None

    @field_validator("publish_id", "error_code", "error_message")
    @classmethod
    def provider_text_is_inert(cls, value: str | None) -> str | None:
        return (
            _validate_inert_nonempty(value, "TikTok upload status text")
            if value is not None
            else None
        )

    @field_validator("recorded_at")
    @classmethod
    def receipt_time_is_aware(cls, value: datetime) -> datetime:
        return _validate_aware(value, "upload status receipt time")

    @field_validator("provider_updated_at")
    @classmethod
    def provider_time_is_aware(cls, value: datetime | None) -> datetime | None:
        return _validate_optional_aware(value, "provider status time")

    @model_validator(mode="after")
    def status_and_identity_are_consistent(self) -> TikTokDraftUploadStatusReceipt:
        if self.sequence_number == 0:
            if self.state != "initialized":
                raise ValueError("the first upload status must be initialized")
            if self.previous_receipt_id is not None or self.previous_state is not None:
                raise ValueError("the first upload status cannot supersede another receipt")
        elif self.previous_receipt_id is None or self.previous_state is None:
            raise ValueError("later upload statuses must bind the previous receipt and state")
        if self.previous_receipt_id == self.receipt_id:
            raise ValueError("an upload status receipt cannot supersede itself")
        if self.state == "initialized":
            if any(
                value is not None
                for value in (
                    self.publish_id,
                    self.error_code,
                    self.error_message,
                    self.provider_updated_at,
                )
            ):
                raise ValueError("initialized upload status cannot contain a network result")
        elif self.state in {"uploaded", "pending-user-action", "complete"}:
            if self.publish_id is None:
                raise ValueError(f"{self.state} upload status requires a publish ID")
            if self.error_code is not None or self.error_message is not None:
                raise ValueError(f"{self.state} upload status cannot contain an error")
        elif self.state == "failed":
            if self.error_code is None and self.error_message is None:
                raise ValueError("failed upload status requires an error code or message")
        elif self.state == "ambiguous" and self.error_message is None:
            raise ValueError("ambiguous upload status must explain the uncertainty")
        elif self.state == "cancelled" and self.error_message is None:
            raise ValueError("cancelled upload status requires a reason")
        expected_hash = _content_hash(self, "receipt_id", "receipt_hash")
        if self.receipt_hash != expected_hash:
            raise ValueError("TikTok upload status receipt hash does not match its content")
        if self.receipt_id != f"tiktok-upload-status-{expected_hash[:16]}":
            raise ValueError("TikTok upload status receipt ID does not match its content")
        return self

    @classmethod
    def create(
        cls,
        attempt: TikTokDraftUploadAttempt,
        *,
        state: TikTokUploadState,
        recorded_at: datetime,
        previous: TikTokDraftUploadStatusReceipt | None = None,
        publish_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        provider_updated_at: datetime | None = None,
    ) -> Self:
        if previous is not None and (
            previous.attempt_id != attempt.attempt_id
            or previous.attempt_hash != attempt.attempt_hash
            or previous.intent_id != attempt.intent.intent_id
            or previous.intent_hash != attempt.intent.intent_hash
        ):
            raise ValueError("previous upload status belongs to another attempt")
        provisional = cls.model_construct(
            receipt_id="tiktok-upload-status-0000000000000000",
            receipt_hash="0" * 64,
            attempt_id=attempt.attempt_id,
            attempt_hash=attempt.attempt_hash,
            intent_id=attempt.intent.intent_id,
            intent_hash=attempt.intent.intent_hash,
            provider=TIKTOK_UPLOAD_PROVIDER,
            operation=DRAFT_TRANSFER_OPERATION,
            sequence_number=0 if previous is None else previous.sequence_number + 1,
            state=state,
            previous_receipt_id=previous.receipt_id if previous is not None else None,
            previous_state=previous.state if previous is not None else None,
            publish_id=publish_id,
            error_code=error_code,
            error_message=error_message,
            recorded_at=recorded_at,
            provider_updated_at=provider_updated_at,
        )
        receipt_hash = _content_hash(provisional, "receipt_id", "receipt_hash")
        payload = provisional.model_dump(mode="python")
        payload["receipt_hash"] = receipt_hash
        payload["receipt_id"] = f"tiktok-upload-status-{receipt_hash[:16]}"
        return cls.model_validate(payload)


class TikTokUploadPreflightCheck(TikTokUploadStrictModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    state: TikTokPreflightCheckState
    detail: str = Field(min_length=1, max_length=800)

    @field_validator("detail")
    @classmethod
    def detail_is_inert(cls, value: str) -> str:
        return _validate_inert_nonempty(value, "upload preflight detail")

    @field_validator("code")
    @classmethod
    def code_is_allowlisted_text(cls, value: str) -> str:
        if _INERT_CODE.fullmatch(value) is None:
            raise ValueError("upload preflight code is invalid")
        return value


class TikTokDraftUploadPreflight(TikTokUploadStrictModel):
    """Credential-safe local checks completed before an attempt is persisted."""

    preflight_id: str = Field(pattern=r"^tiktok-upload-preflight-[0-9a-f]{16}$")
    preflight_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intent_id: str = Field(pattern=r"^tiktok-upload-intent-[0-9a-f]{16}$")
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: Literal["tiktok-content-posting-api"] = TIKTOK_UPLOAD_PROVIDER
    state: Literal["ready", "blocked"]
    credentials_available: bool
    network_attempted: Literal[False] = False
    checks: tuple[TikTokUploadPreflightCheck, ...] = Field(min_length=1, max_length=16)
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def check_time_is_aware(cls, value: datetime) -> datetime:
        return _validate_aware(value, "upload preflight time")

    @model_validator(mode="after")
    def checks_and_identity_are_consistent(self) -> TikTokDraftUploadPreflight:
        codes = [check.code for check in self.checks]
        if len(codes) != len(set(codes)):
            raise ValueError("upload preflight check codes must be unique")
        expected_state = (
            "ready"
            if self.credentials_available and all(check.state != "failure" for check in self.checks)
            else "blocked"
        )
        if self.state != expected_state:
            raise ValueError("upload preflight state does not match its checks")
        expected_hash = _content_hash(self, "preflight_id", "preflight_hash")
        if self.preflight_hash != expected_hash:
            raise ValueError("TikTok upload preflight hash does not match its content")
        if self.preflight_id != f"tiktok-upload-preflight-{expected_hash[:16]}":
            raise ValueError("TikTok upload preflight ID does not match its content")
        return self

    @classmethod
    def create(
        cls,
        intent: TikTokDraftUploadIntent,
        *,
        credentials_available: bool,
        checks: tuple[TikTokUploadPreflightCheck, ...],
        checked_at: datetime,
    ) -> Self:
        state: Literal["ready", "blocked"] = (
            "ready"
            if credentials_available and all(check.state != "failure" for check in checks)
            else "blocked"
        )
        provisional = cls.model_construct(
            preflight_id="tiktok-upload-preflight-0000000000000000",
            preflight_hash="0" * 64,
            intent_id=intent.intent_id,
            intent_hash=intent.intent_hash,
            provider=TIKTOK_UPLOAD_PROVIDER,
            state=state,
            credentials_available=credentials_available,
            network_attempted=False,
            checks=checks,
            checked_at=checked_at,
        )
        preflight_hash = _content_hash(provisional, "preflight_id", "preflight_hash")
        payload = provisional.model_dump(mode="python")
        payload["preflight_hash"] = preflight_hash
        payload["preflight_id"] = f"tiktok-upload-preflight-{preflight_hash[:16]}"
        return cls.model_validate(payload)


class TikTokUploadDiagnostic(TikTokUploadStrictModel):
    provider: Literal["tiktok-content-posting-api"] = TIKTOK_UPLOAD_PROVIDER
    status: Literal["ready", "authentication-required", "unavailable", "error"]
    credentials_available: bool
    network_checked: bool
    checked_at: datetime
    reason: str = Field(min_length=1, max_length=800)
    next_steps: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("checked_at")
    @classmethod
    def diagnostic_time_is_aware(cls, value: datetime) -> datetime:
        return _validate_aware(value, "TikTok upload diagnostic time")

    @field_validator("reason")
    @classmethod
    def reason_is_inert(cls, value: str) -> str:
        return _validate_inert_nonempty(value, "TikTok upload diagnostic reason")

    @field_validator("next_steps")
    @classmethod
    def next_steps_are_inert(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            _validate_inert_nonempty(item, "TikTok upload diagnostic next step") for item in value
        )

    @model_validator(mode="after")
    def readiness_matches_credentials(self) -> TikTokUploadDiagnostic:
        if self.status == "ready" and not self.credentials_available:
            raise ValueError("ready TikTok diagnostics require available credentials")
        if self.status == "authentication-required" and self.credentials_available:
            raise ValueError("authentication-required diagnostics cannot claim credentials")
        return self
