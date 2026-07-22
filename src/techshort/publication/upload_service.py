from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from techshort.domain.hashing import sha256_file
from techshort.domain.models import ReviewStatus, now_utc
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    load_model,
    within,
)
from techshort.experiments.creative import ExportExperimentContract, _validated_export_contract
from techshort.experiments.models import experiment_review_hash, variant_review_hash
from techshort.experiments.storage import ExperimentStore
from techshort.publication.models import (
    HumanPublicationConsent,
    OrganicPostMetadata,
    OrganicPublicationPackage,
)
from techshort.publication.official.tiktok import (
    TikTokApiError,
    TikTokConfigurationError,
    TikTokDraftInitialization,
    TikTokDraftUploadApi,
    TikTokPublishStatus,
    TikTokUploadReceipt,
)
from techshort.publication.upload_models import (
    DRAFT_TRANSFER_CONFIRMATION,
    TikTokDraftUploadAttempt,
    TikTokDraftUploadConsent,
    TikTokDraftUploadIntent,
    TikTokDraftUploadPreflight,
    TikTokDraftUploadStatusReceipt,
    TikTokUploadPreflightCheck,
    TikTokUploadState,
)

_INTENT_ID = re.compile(r"^tiktok-upload-intent-[0-9a-f]{16}$")
_EXPERIMENT_ID = re.compile(r"^exp-[0-9a-f]{16}$")
_CANONICAL_PACKAGE_FILENAME = "package-manifest.json"
_RECORD_FILENAMES = {
    "intent.json",
    "consent.json",
    "attempt.json",
    "preflight.json",
    "video.mp4",
}


def create_tiktok_draft_upload_intent(
    store: ProjectStore,
    package_manifest_path: str | Path,
    *,
    target_account_subject_sha256: str,
    target_account_label: str,
    requested_by: str,
    requested_at: datetime | None = None,
) -> TikTokDraftUploadIntent:
    """Create a draft-only intent after validating the exact reviewed package."""

    package, _package_directory, _video, _contract = _validated_upload_package(
        store, package_manifest_path
    )
    return TikTokDraftUploadIntent.create(
        package_id=package.package_id,
        package_hash=package.package_hash,
        experiment_id=package.experiment_id,
        variant_id=package.variant_id,
        video_hash=package.variant_media_hash,
        target_account_subject_sha256=target_account_subject_sha256,
        target_account_label=target_account_label,
        requested_by=requested_by,
        requested_at=requested_at or now_utc(),
    )


def preflight_tiktok_draft_upload(
    store: ProjectStore,
    package_manifest_path: str | Path,
    intent: TikTokDraftUploadIntent,
    *,
    credentials_available: bool,
    checked_at: datetime | None = None,
) -> TikTokDraftUploadPreflight:
    """Run credential-safe local checks without reading a token or using the network."""

    package, _package_directory, _video, _contract = _validated_upload_package(
        store, package_manifest_path
    )
    _validate_intent_binding(intent, package)
    credential_state: Literal["pass", "failure"] = (
        "pass" if credentials_available else "failure"
    )
    credential_detail = (
        "TikTok credentials were reported available; no token value was read or persisted."
        if credentials_available
        else "TikTok credentials are unavailable; no network attempt is permitted."
    )
    checks = (
        TikTokUploadPreflightCheck(
            code="reviewed-package",
            state="pass",
            detail="Every immutable package file matches its reviewed SHA-256 digest.",
        ),
        TikTokUploadPreflightCheck(
            code="current-final",
            state="pass",
            detail=(
                "The package still matches the current approved experiment, variant, final "
                "export, evidence, claims, limitation, and rights state."
            ),
        ),
        TikTokUploadPreflightCheck(
            code="draft-only",
            state="pass",
            detail=(
                "The allowlisted operation transfers a draft for completion in TikTok; it "
                "does not directly publish a public post."
            ),
        ),
        TikTokUploadPreflightCheck(
            code="separate-cover-unsupported",
            state="warning",
            detail=(
                "TikTok draft upload does not transfer the package's separate cover PNG; "
                "select the reviewed cover manually in TikTok."
            ),
        ),
        TikTokUploadPreflightCheck(
            code="burned-captions-retained",
            state="pass",
            detail=(
                "The reviewed MP4 retains its burned-in captions; standalone SRT and VTT "
                "files remain local and are not sent by this draft transfer."
            ),
        ),
        TikTokUploadPreflightCheck(
            code="credentials",
            state=credential_state,
            detail=credential_detail,
        ),
    )
    return TikTokDraftUploadPreflight.create(
        intent,
        credentials_available=credentials_available,
        checks=checks,
        checked_at=checked_at or now_utc(),
    )


def grant_tiktok_draft_upload_consent(
    intent: TikTokDraftUploadIntent,
    *,
    reviewer_identifier: str,
    confirmation: str,
    decided_at: datetime | None = None,
    recorded_at: datetime | None = None,
) -> TikTokDraftUploadConsent:
    """Create the separate, exact-account consent required for API transfer."""

    decision_time = decided_at or now_utc()
    record_time = recorded_at or decision_time
    return TikTokDraftUploadConsent.create(
        intent,
        state="granted",
        reviewer_identifier=reviewer_identifier,
        confirmation=confirmation,
        decided_at=decision_time,
        recorded_at=record_time,
    )


def execute_tiktok_draft_upload(
    store: ProjectStore,
    package_manifest_path: str | Path,
    intent: TikTokDraftUploadIntent,
    consent: TikTokDraftUploadConsent,
    preflight: TikTokDraftUploadPreflight,
    client: TikTokDraftUploadApi,
    *,
    prepared_at: datetime | None = None,
) -> TikTokDraftUploadStatusReceipt:
    """Persist the exact attempt, then perform one non-retriable draft transfer."""

    package, _package_directory, video, _contract = _validated_upload_package(
        store, package_manifest_path
    )
    _validate_intent_binding(intent, package)
    _validate_consent_and_preflight(intent, consent, preflight)
    _validate_client_account(intent, client)
    attempt = TikTokDraftUploadAttempt.create(
        intent,
        consent,
        prepared_at=prepared_at or now_utc(),
    )
    initial = TikTokDraftUploadStatusReceipt.create(
        attempt,
        state="initialized",
        recorded_at=now_utc(),
    )
    upload_directory = _persist_pre_network_attempt(
        store,
        package,
        intent,
        consent,
        attempt,
        preflight,
        initial,
        video,
    )

    # Detect local mutation after the durable attempt boundary. No second attempt is allowed.
    try:
        _validated_upload_package(store, package_manifest_path)
    except (OSError, ValueError):
        cancelled = TikTokDraftUploadStatusReceipt.create(
            attempt,
            state="cancelled",
            error_message=(
                "The reviewed package changed after attempt preparation; no network request "
                "was made."
            ),
            previous=initial,
            recorded_at=now_utc(),
        )
        return _append_status_receipt(upload_directory, attempt, cancelled)
    upload_video = upload_directory / "video.mp4"
    if sha256_file(upload_video) != intent.video_hash:
        cancelled = TikTokDraftUploadStatusReceipt.create(
            attempt,
            state="cancelled",
            error_message="The durable video snapshot failed its approved SHA-256 check.",
            previous=initial,
            recorded_at=now_utc(),
        )
        return _append_status_receipt(upload_directory, attempt, cancelled)
    initialization: TikTokDraftInitialization | None = None
    try:
        initialization = client.initialize_draft(upload_video)
        if sha256_file(upload_video) != intent.video_hash:
            raise RuntimeError("durable upload snapshot changed after initialization")
        provider_receipt = client.upload_video(initialization, upload_video)
        publish_id = _safe_publish_id(provider_receipt, initialization)
        if (
            provider_receipt.bytes_uploaded != upload_video.stat().st_size
            or sha256_file(upload_video) != intent.video_hash
        ):
            raise RuntimeError("provider did not confirm the complete reviewed video")
        receipt = TikTokDraftUploadStatusReceipt.create(
            attempt,
            state="uploaded",
            publish_id=publish_id,
            previous=initial,
            recorded_at=now_utc(),
        )
    except Exception as exc:  # The attempt is durable; unknown outcomes must be conservative.
        definite = isinstance(exc, (TikTokApiError, TikTokConfigurationError))
        provider_publish_id = _optional_publish_id(initialization)
        receipt = TikTokDraftUploadStatusReceipt.create(
            attempt,
            state="failed" if definite else "ambiguous",
            publish_id=provider_publish_id,
            error_code="provider-rejected" if definite else None,
            error_message=(
                "TikTok rejected the draft transfer before it could complete."
                if definite
                else "The TikTok draft transfer outcome is unknown; do not retry automatically."
            ),
            previous=initial,
            recorded_at=now_utc(),
        )
    return _append_status_receipt(upload_directory, attempt, receipt)


def poll_tiktok_draft_upload(
    store: ProjectStore,
    experiment_id: str,
    intent_id: str,
    client: TikTokDraftUploadApi,
    *,
    recorded_at: datetime | None = None,
) -> TikTokDraftUploadStatusReceipt:
    """Poll one existing transfer and append a new receipt without re-uploading."""

    upload_directory = _upload_directory(store, experiment_id, intent_id)
    attempt = _validated_attempt_records(upload_directory, experiment_id, intent_id)
    _validate_client_account(attempt.intent, client)
    previous = _latest_status_receipt(upload_directory, attempt)
    if previous.state in {"complete", "failed", "cancelled"}:
        raise ValueError("terminal TikTok draft uploads cannot be polled again")
    if previous.publish_id is None:
        raise ValueError("TikTok draft upload has no provider publish ID to poll")
    try:
        provider_status = client.fetch_status(previous.publish_id)
        state, error_code, error_message = _map_provider_status(provider_status)
        publish_id = _safe_provider_status_publish_id(provider_status, previous.publish_id)
        receipt = TikTokDraftUploadStatusReceipt.create(
            attempt,
            state=state,
            publish_id=publish_id,
            error_code=error_code,
            error_message=error_message,
            previous=previous,
            recorded_at=recorded_at or now_utc(),
        )
    except Exception as exc:
        if isinstance(exc, TikTokApiError):
            receipt = TikTokDraftUploadStatusReceipt.create(
                attempt,
                state="ambiguous",
                publish_id=previous.publish_id,
                error_code="status-fetch-rejected",
                error_message=(
                    "TikTok rejected the status request; the existing draft outcome remains "
                    "unknown and no upload retry was attempted."
                ),
                previous=previous,
                recorded_at=recorded_at or now_utc(),
            )
        else:
            receipt = TikTokDraftUploadStatusReceipt.create(
                attempt,
                state="ambiguous",
                publish_id=previous.publish_id,
                error_message=(
                    "TikTok draft status could not be confirmed; no upload retry was attempted."
                ),
                previous=previous,
                recorded_at=recorded_at or now_utc(),
            )
    return _append_status_receipt(upload_directory, attempt, receipt)


def _validated_upload_package(
    store: ProjectStore,
    package_manifest_path: str | Path,
) -> tuple[OrganicPublicationPackage, Path, Path, ExportExperimentContract]:
    unresolved = Path(package_manifest_path)
    candidate = unresolved if unresolved.is_absolute() else store.root / unresolved
    if candidate.is_symlink():
        raise ValueError("upload package manifest cannot be a symbolic link")
    manifest_path = within(store.root, candidate)
    if not manifest_path.is_file() or manifest_path.name != _CANONICAL_PACKAGE_FILENAME:
        raise ValueError("upload requires an existing canonical package manifest")
    package = load_model(manifest_path, OrganicPublicationPackage)
    package_directory = manifest_path.parent
    expected = store.path(
        f"experiments/{package.experiment_id}/publication/{package.variant_id}/"
        f"{package.platform}/{package.package_id}/{_CANONICAL_PACKAGE_FILENAME}"
    )
    if manifest_path != expected:
        raise ValueError("upload package manifest is outside its canonical project location")
    if package.platform != "tiktok":
        raise ValueError("TikTok draft transfer requires a TikTok publication package")
    if package.consent.state != "granted" or not package.manual_upload_authorized:
        raise ValueError("upload requires an immutable package with granted manual consent")
    _verify_package_files(package_directory, package)
    contract = _validated_export_contract(store)
    _validate_current_binding(store, package, contract)
    video = package_directory / "video.mp4"
    return package, package_directory, video, contract


def _verify_package_files(
    package_directory: Path,
    package: OrganicPublicationPackage,
) -> None:
    if package_directory.is_symlink():
        raise ValueError("upload package directory cannot be a symbolic link")
    expected_names = {item.filename for item in package.files} | {
        _CANONICAL_PACKAGE_FILENAME
    }
    actual_names = {item.name for item in package_directory.iterdir() if item.is_file()}
    if actual_names != expected_names or any(item.is_dir() for item in package_directory.iterdir()):
        raise ValueError("upload package contains missing or unexpected artifacts")
    for item in package.files:
        path = package_directory / item.filename
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != item.size_bytes
            or sha256_file(path) != item.sha256
        ):
            raise ValueError(f"upload package artifact is stale: {item.filename}")
    metadata = load_model(package_directory / "post-metadata.json", OrganicPostMetadata)
    manual_consent = load_model(
        package_directory / "consent-receipt.json", HumanPublicationConsent
    )
    if (
        metadata.metadata_id != package.metadata_id
        or metadata.metadata_hash != package.metadata_hash
        or metadata.experiment_id != package.experiment_id
        or metadata.variant_id != package.variant_id
        or metadata.platform != package.platform
    ):
        raise ValueError("upload package metadata does not match its manifest")
    if manual_consent != package.consent:
        raise ValueError("upload package manual consent does not match its manifest")


def _validate_current_binding(
    store: ProjectStore,
    package: OrganicPublicationPackage,
    contract: ExportExperimentContract,
) -> None:
    project = store.project()
    if not project.downstream_valid or project.stale_artifacts:
        raise ValueError("upload requires a current, non-stale approved project")
    experiment_store = ExperimentStore(store, package.experiment_id)
    manifest = experiment_store.manifest()
    if (
        manifest.project_id != project.project_id
        or manifest.review_status is not ReviewStatus.APPROVED
        or manifest.approval_hash is None
        or manifest.approval_hash != experiment_review_hash(manifest)
        or manifest.approval_hash != package.experiment_approval_hash
    ):
        raise ValueError("upload experiment approval is missing or stale")
    variant = next(
        (item for item in manifest.variants if item.variant_id == package.variant_id), None
    )
    if (
        variant is None
        or variant.review_status is not ReviewStatus.APPROVED
        or variant.approval_hash is None
        or variant.approval_hash != variant_review_hash(variant)
        or variant.approval_hash != package.variant_approval_hash
    ):
        raise ValueError("upload variant approval is missing or stale")
    package_bindings = {
        "media_hash": package.variant_media_hash,
        "locked_factual_hash": package.locked_factual_hash,
        "evidence_hash": package.evidence_hash,
        "claims_hash": package.claims_hash,
        "limitation_hash": package.limitation_hash,
        "rights_hash": package.rights_hash,
    }
    for field_name, expected in package_bindings.items():
        if getattr(variant, field_name) != expected or getattr(contract, field_name) != expected:
            raise ValueError(f"upload package has stale {field_name.replace('_', ' ')}")
    reviewed_media = store.path(variant.media_path)
    if (
        contract.media_path != variant.media_path
        or not reviewed_media.is_file()
        or sha256_file(reviewed_media) != package.variant_media_hash
    ):
        raise ValueError("upload package media no longer matches the current final export")
    if variant.cover_path is None or variant.cover_hash != package.variant_cover_hash:
        raise ValueError("upload package cover no longer matches the reviewed variant")
    reviewed_cover = store.path(variant.cover_path)
    if not reviewed_cover.is_file() or sha256_file(reviewed_cover) != package.variant_cover_hash:
        raise ValueError("upload package cover is stale")


def _validate_intent_binding(
    intent: TikTokDraftUploadIntent,
    package: OrganicPublicationPackage,
) -> None:
    expected = (
        intent.package_id == package.package_id
        and intent.package_hash == package.package_hash
        and intent.experiment_id == package.experiment_id
        and intent.variant_id == package.variant_id
        and intent.video_hash == package.variant_media_hash
    )
    if not expected:
        raise ValueError("TikTok upload intent does not bind this exact package")


def _validate_consent_and_preflight(
    intent: TikTokDraftUploadIntent,
    consent: TikTokDraftUploadConsent,
    preflight: TikTokDraftUploadPreflight,
) -> None:
    if (
        consent.state != "granted"
        or consent.confirmation != DRAFT_TRANSFER_CONFIRMATION
        or consent.intent_id != intent.intent_id
        or consent.intent_hash != intent.intent_hash
    ):
        raise ValueError("TikTok API upload requires separate consent for this exact intent")
    if (
        preflight.intent_id != intent.intent_id
        or preflight.intent_hash != intent.intent_hash
        or preflight.state != "ready"
        or not preflight.credentials_available
    ):
        raise ValueError("TikTok API upload preflight is blocked or belongs to another intent")


def _persist_pre_network_attempt(
    store: ProjectStore,
    package: OrganicPublicationPackage,
    intent: TikTokDraftUploadIntent,
    consent: TikTokDraftUploadConsent,
    attempt: TikTokDraftUploadAttempt,
    preflight: TikTokDraftUploadPreflight,
    initial: TikTokDraftUploadStatusReceipt,
    video: Path,
) -> Path:
    upload_root = store.path(f"experiments/{package.experiment_id}/uploads")
    upload_root.mkdir(parents=True, exist_ok=True)
    _reject_previous_attempt(upload_root, package)
    destination = upload_root / intent.intent_id
    stage = Path(tempfile.mkdtemp(prefix=f".{intent.intent_id}.", dir=upload_root))
    try:
        atomic_write_model(stage / "intent.json", intent)
        atomic_write_model(stage / "consent.json", consent)
        atomic_write_model(stage / "attempt.json", attempt)
        atomic_write_model(stage / "preflight.json", preflight)
        atomic_copy_file(video, stage / "video.mp4")
        if sha256_file(stage / "video.mp4") != intent.video_hash:
            raise ValueError("reviewed video changed while preparing the upload snapshot")
        receipts = stage / "receipts"
        receipts.mkdir()
        atomic_write_model(receipts / _receipt_filename(initial), initial)
        try:
            os.replace(stage, destination)
        except FileExistsError as exc:
            raise ValueError("TikTok draft upload intent already has an attempt") from exc
    finally:
        _remove_upload_stage(stage, upload_root)
    return destination


def _reject_previous_attempt(upload_root: Path, package: OrganicPublicationPackage) -> None:
    for directory in upload_root.iterdir():
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        if directory.is_symlink() or not _INTENT_ID.fullmatch(directory.name):
            raise ValueError("uploads directory contains an unsafe or unknown record")
        intent_path = directory / "intent.json"
        attempt_path = directory / "attempt.json"
        if not intent_path.is_file() or not attempt_path.is_file():
            raise ValueError("existing TikTok upload record is incomplete; retry is unsafe")
        recorded_intent = load_model(intent_path, TikTokDraftUploadIntent)
        recorded_attempt = load_model(attempt_path, TikTokDraftUploadAttempt)
        if recorded_attempt.intent != recorded_intent:
            raise ValueError("existing TikTok upload intent and attempt records disagree")
        if (
            recorded_intent.package_id == package.package_id
            or recorded_intent.package_hash == package.package_hash
        ):
            raise ValueError(
                "this immutable package already has an upload attempt; automatic retry is blocked"
            )


def _upload_directory(store: ProjectStore, experiment_id: str, intent_id: str) -> Path:
    if not _EXPERIMENT_ID.fullmatch(experiment_id):
        raise ValueError("TikTok upload experiment ID has an invalid format")
    if not _INTENT_ID.fullmatch(intent_id):
        raise ValueError("TikTok upload intent ID has an invalid format")
    directory = store.path(f"experiments/{experiment_id}/uploads/{intent_id}")
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("TikTok draft upload attempt does not exist")
    expected_names = _RECORD_FILENAMES | {"receipts"}
    if {item.name for item in directory.iterdir()} != expected_names:
        raise ValueError("TikTok draft upload record is incomplete or contains unknown files")
    return directory


def _validated_attempt_records(
    upload_directory: Path,
    experiment_id: str,
    intent_id: str,
) -> TikTokDraftUploadAttempt:
    intent = load_model(upload_directory / "intent.json", TikTokDraftUploadIntent)
    consent = load_model(upload_directory / "consent.json", TikTokDraftUploadConsent)
    attempt = load_model(upload_directory / "attempt.json", TikTokDraftUploadAttempt)
    preflight = load_model(upload_directory / "preflight.json", TikTokDraftUploadPreflight)
    if (
        intent.experiment_id != experiment_id
        or intent.intent_id != intent_id
        or attempt.intent != intent
        or attempt.consent != consent
        or preflight.intent_id != intent.intent_id
        or preflight.intent_hash != intent.intent_hash
        or sha256_file(upload_directory / "video.mp4") != intent.video_hash
    ):
        raise ValueError("TikTok draft upload records are stale or disagree")
    return attempt


def _latest_status_receipt(
    upload_directory: Path,
    attempt: TikTokDraftUploadAttempt,
) -> TikTokDraftUploadStatusReceipt:
    receipt_directory = upload_directory / "receipts"
    if receipt_directory.is_symlink() or not receipt_directory.is_dir():
        raise ValueError("TikTok upload status receipt directory is missing")
    paths = sorted(receipt_directory.iterdir())
    if not paths or any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("TikTok upload status receipt chain is invalid")
    previous: TikTokDraftUploadStatusReceipt | None = None
    for expected_sequence, path in enumerate(paths):
        receipt = load_model(path, TikTokDraftUploadStatusReceipt)
        if path.name != _receipt_filename(receipt) or receipt.sequence_number != expected_sequence:
            raise ValueError("TikTok upload status receipt chain is out of order")
        if (
            receipt.attempt_id != attempt.attempt_id
            or receipt.attempt_hash != attempt.attempt_hash
            or receipt.previous_receipt_id
            != (previous.receipt_id if previous is not None else None)
            or receipt.previous_state != (previous.state if previous is not None else None)
            or receipt.intent_id != attempt.intent.intent_id
            or receipt.intent_hash != attempt.intent.intent_hash
        ):
            raise ValueError("TikTok upload status receipt chain has stale bindings")
        previous = receipt
    if previous is None:  # pragma: no cover - guarded by the nonempty check above
        raise ValueError("TikTok upload status receipt chain is empty")
    return previous


def _append_status_receipt(
    upload_directory: Path,
    attempt: TikTokDraftUploadAttempt,
    receipt: TikTokDraftUploadStatusReceipt,
) -> TikTokDraftUploadStatusReceipt:
    previous = _latest_status_receipt(upload_directory, attempt)
    if (
        receipt.sequence_number != previous.sequence_number + 1
        or receipt.previous_receipt_id != previous.receipt_id
    ):
        raise ValueError("new TikTok upload status does not extend the append-only chain")
    destination = upload_directory / "receipts" / _receipt_filename(receipt)
    if destination.exists():
        existing = load_model(destination, TikTokDraftUploadStatusReceipt)
        if existing != receipt:
            raise ValueError("conflicting TikTok upload status receipt cannot be overwritten")
        return existing
    atomic_write_model(destination, receipt)
    return receipt


def _receipt_filename(receipt: TikTokDraftUploadStatusReceipt) -> str:
    return f"{receipt.sequence_number:04d}-{receipt.receipt_id}.json"


def _safe_publish_id(
    provider_receipt: TikTokUploadReceipt,
    initialization: TikTokDraftInitialization,
) -> str:
    initialized_id = _optional_publish_id(initialization)
    receipt_id = _optional_publish_id(provider_receipt)
    if initialized_id is None or receipt_id is None or receipt_id != initialized_id:
        raise RuntimeError("TikTok upload response did not preserve its publish ID")
    return receipt_id


def _optional_publish_id(
    value: TikTokDraftInitialization | TikTokUploadReceipt | TikTokPublishStatus | None,
) -> str | None:
    if value is None:
        return None
    publish_id = getattr(value, "publish_id", None)
    return publish_id if isinstance(publish_id, str) and publish_id.strip() else None


def _safe_provider_status_publish_id(
    provider_status: TikTokPublishStatus,
    expected: str,
) -> str:
    publish_id = _optional_publish_id(provider_status)
    if publish_id != expected:
        raise RuntimeError("TikTok status response changed its publish ID")
    return expected


def _map_provider_status(
    provider_status: TikTokPublishStatus,
) -> tuple[TikTokUploadState, str | None, str | None]:
    raw_status = provider_status.status.upper()
    if provider_status.publicly_available:
        return (
            "ambiguous",
            None,
            "TikTok reported unexpected public availability for a draft-only transfer.",
        )
    if raw_status in {
        "PROCESSING_UPLOAD",
        "PROCESSING_DOWNLOAD",
        "PROCESSING",
        "UPLOADED",
    }:
        return "uploaded", None, None
    if raw_status in {"SEND_TO_USER_INBOX", "PENDING_USER_ACTION", "PENDING-USER-ACTION"}:
        return "pending-user-action", None, None
    if raw_status in {"PUBLISH_COMPLETE", "COMPLETE"}:
        return "complete", None, None
    if raw_status in {"FAILED", "PUBLISH_FAILED", "ERROR"}:
        return (
            "failed",
            "provider-reported-failure",
            "TikTok reported that the draft transfer failed.",
        )
    return (
        "ambiguous",
        None,
        "TikTok returned an unrecognized draft status; no upload retry was attempted.",
    )


def _remove_upload_stage(stage: Path, upload_root: Path) -> None:
    if not stage.exists():
        return
    resolved = stage.resolve()
    root = upload_root.resolve()
    if resolved.parent != root or not resolved.name.startswith(".tiktok-upload-intent-"):
        raise ValueError("refusing to remove an unexpected upload staging directory")
    shutil.rmtree(resolved)


def _validate_client_account(
    intent: TikTokDraftUploadIntent,
    client: TikTokDraftUploadApi,
) -> None:
    if client.account_subject_hash != intent.target_account_subject_sha256:
        raise ValueError("authenticated TikTok account does not match the approved upload intent")


__all__ = [
    "DRAFT_TRANSFER_CONFIRMATION",
    "create_tiktok_draft_upload_intent",
    "execute_tiktok_draft_upload",
    "grant_tiktok_draft_upload_consent",
    "poll_tiktok_draft_upload",
    "preflight_tiktok_draft_upload",
]
