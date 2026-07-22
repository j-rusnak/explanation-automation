from __future__ import annotations

import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import ReviewStatus, now_utc
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    atomic_write_text,
    load_model,
    within,
)
from techshort.experiments.storage import ExperimentStore
from techshort.publication.models import (
    GRANT_CONFIRMATION,
    ArtifactRole,
    HumanPublicationConsent,
    OrganicPackageBuildResult,
    OrganicPackageRequest,
    OrganicPostMetadata,
    OrganicPublicationPackage,
    PublicationPackageFile,
)
from techshort.publication.providers import ManualOrganicProvider, OrganicPlatformProvider

_SOURCE_RULES = {
    "video": ("final_mp4", ".mp4", "video.mp4", 2 * 1024 * 1024 * 1024),
    "cover": ("cover_png", ".png", "cover.png", 20 * 1024 * 1024),
    "captions-srt": ("captions_srt", ".srt", "captions.srt", 10 * 1024 * 1024),
    "captions-vtt": ("captions_vtt", ".vtt", "captions.vtt", 10 * 1024 * 1024),
}
_ALLOWED_SOURCE_ROOTS = {
    "video": {"export", "renders", "experiments"},
    "cover": {"export", "renders", "experiments"},
    "captions-srt": {"export", "captions", "experiments"},
    "captions-vtt": {"export", "captions", "experiments"},
}


def organic_package_input_hash(store: ProjectStore, request: OrganicPackageRequest) -> str:
    """Validate and hash the exact variant inputs without storing or contacting anything."""

    sources, source_files = _validated_source_files(store, request)
    experiment_binding = _validated_experiment_binding(store, request, sources, source_files)
    return _derive_input_hash(request, source_files, experiment_binding)


def build_organic_publication_package(
    store: ProjectStore,
    request: OrganicPackageRequest,
    *,
    consent: HumanPublicationConsent | None = None,
    provider: OrganicPlatformProvider | None = None,
) -> OrganicPackageBuildResult:
    """Create an immutable local handoff package; never upload or claim publication."""

    sources, source_files = _validated_source_files(store, request)
    experiment_binding = _validated_experiment_binding(store, request, sources, source_files)
    package_input_hash = _derive_input_hash(request, source_files, experiment_binding)
    if consent is None:
        consent = _pending_consent(request, package_input_hash)
    _validate_consent_binding(request, package_input_hash, consent)
    selected_provider = provider or ManualOrganicProvider(request.platform)
    if selected_provider.platform != request.platform:
        raise ValueError("publication provider platform does not match the package request")
    prepared = selected_provider.prepare(request, package_input_hash, consent)

    package_id = _derive_package_id(
        request, package_input_hash, consent, selected_provider.provider_name
    )
    package_relative = (
        f"experiments/{request.experiment_id}/publication/{request.variant_id}/"
        f"{request.platform}/{package_id}"
    )
    destination = store.path(package_relative)
    if destination.exists():
        manifest = _expected_existing_manifest(destination, package_id)
        _verify_existing_package(destination, manifest)
        if (
            manifest.package_input_hash != package_input_hash
            or manifest.consent != consent
            or manifest.metadata_hash != prepared.metadata.metadata_hash
            or manifest.provider_name != selected_provider.provider_name
        ):
            raise ValueError("existing organic package ID conflicts with the requested content")
        return OrganicPackageBuildResult(
            package_directory=package_relative,
            manifest=manifest,
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{package_id}.", dir=destination.parent))
    try:
        for role, source in sources.items():
            destination_name = _SOURCE_RULES[role][2]
            copied = stage / destination_name
            atomic_copy_file(source, copied)
            if sha256_file(copied) != source_files[role]["sha256"]:
                raise ValueError(f"{role} changed while the publication package was copied")

        atomic_write_model(stage / "post-metadata.json", prepared.metadata)
        atomic_write_text(stage / "checklist.md", prepared.checklist_markdown)
        atomic_write_model(stage / "consent-receipt.json", consent)
        package_files = _package_files(stage)
        package_payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "package_id": package_id,
            "experiment_id": request.experiment_id,
            "variant_id": request.variant_id,
            "platform": request.platform,
            "provider_name": selected_provider.provider_name,
            "package_input_hash": package_input_hash,
            "variant_media_hash": request.expected_media_hash,
            "variant_cover_hash": request.expected_cover_hash,
            **experiment_binding,
            "consent": consent,
            "metadata_id": prepared.metadata.metadata_id,
            "metadata_hash": prepared.metadata.metadata_hash,
            "files": package_files,
            "manual_upload_authorized": consent.state == "granted",
            "automated_upload": False,
            "claimed_posted": False,
        }
        package_payload["package_hash"] = stable_hash(package_payload)
        manifest = OrganicPublicationPackage.model_validate(package_payload)
        atomic_write_model(stage / "package-manifest.json", manifest)

        try:
            os.replace(stage, destination)
        except FileExistsError:
            existing = _expected_existing_manifest(destination, package_id)
            _verify_existing_package(destination, existing)
            if existing != manifest:
                raise ValueError(
                    "concurrent organic package build produced conflicting content"
                ) from None
            _remove_verified_stage(stage, destination.parent)
            manifest = existing
    except Exception:
        _remove_verified_stage(stage, destination.parent)
        raise
    return OrganicPackageBuildResult(
        package_directory=package_relative,
        manifest=manifest,
    )


def record_publication_consent(
    package: OrganicPublicationPackage,
    *,
    state: Literal["granted", "declined", "revoked"],
    reviewer_identifier: str,
    confirmation: str,
    decided_at: datetime | None = None,
) -> HumanPublicationConsent:
    """Return a new immutable receipt; the prior package and receipt remain unchanged."""

    if state == "revoked" and package.consent.state != "granted":
        raise ValueError("publication consent can be revoked only after it was granted")
    decision_time = (decided_at or now_utc()).astimezone(UTC)
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "experiment_id": package.experiment_id,
        "variant_id": package.variant_id,
        "platform": package.platform,
        "package_input_hash": package.package_input_hash,
        "state": state,
        "reviewer_identifier": reviewer_identifier,
        "confirmation": confirmation,
        "decided_at": decision_time.isoformat().replace("+00:00", "Z"),
        "supersedes_receipt_id": package.consent.receipt_id,
    }
    payload["receipt_id"] = f"organic-consent-{stable_hash(payload)[:16]}"
    return HumanPublicationConsent.model_validate(payload)


def _pending_consent(
    request: OrganicPackageRequest, package_input_hash: str
) -> HumanPublicationConsent:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "experiment_id": request.experiment_id,
        "variant_id": request.variant_id,
        "platform": request.platform,
        "package_input_hash": package_input_hash,
        "state": "pending",
        "reviewer_identifier": None,
        "confirmation": None,
        "decided_at": None,
        "supersedes_receipt_id": None,
    }
    payload["receipt_id"] = f"organic-consent-{stable_hash(payload)[:16]}"
    return HumanPublicationConsent.model_validate(payload)


def _derive_package_id(
    request: OrganicPackageRequest,
    package_input_hash: str,
    consent: HumanPublicationConsent,
    provider_name: str,
) -> str:
    identity = {
        "schema_version": "1.0.0",
        "experiment_id": request.experiment_id,
        "variant_id": request.variant_id,
        "platform": request.platform,
        "provider_name": provider_name,
        "package_input_hash": package_input_hash,
        "consent_receipt_id": consent.receipt_id,
    }
    return f"organic-package-{stable_hash(identity)[:16]}"


def _validate_consent_binding(
    request: OrganicPackageRequest,
    package_input_hash: str,
    consent: HumanPublicationConsent,
) -> None:
    if (
        consent.experiment_id != request.experiment_id
        or consent.variant_id != request.variant_id
        or consent.platform != request.platform
        or consent.package_input_hash != package_input_hash
    ):
        raise ValueError("publication consent is stale or belongs to another variant")


def _validated_source_files(
    store: ProjectStore, request: OrganicPackageRequest
) -> tuple[dict[str, Path], dict[str, dict[str, str | int]]]:
    sources: dict[str, Path] = {}
    snapshots: dict[str, dict[str, str | int]] = {}
    for role, (attribute, suffix, _, maximum_size) in _SOURCE_RULES.items():
        candidate_value = str(getattr(request, attribute))
        candidate = Path(candidate_value)
        unresolved = candidate if candidate.is_absolute() else store.root / candidate
        if unresolved.is_symlink():
            raise ValueError(f"{role} cannot be a symbolic link")
        resolved = within(store.root, unresolved)
        if not resolved.is_file():
            raise ValueError(f"publication {role} file is missing")
        relative = resolved.relative_to(store.root)
        if not relative.parts or relative.parts[0] not in _ALLOWED_SOURCE_ROOTS[role]:
            raise ValueError(f"publication {role} must come from an allowlisted output directory")
        if resolved.suffix.casefold() != suffix:
            raise ValueError(f"publication {role} must use {suffix}")
        size = resolved.stat().st_size
        if size <= 0 or size > maximum_size:
            raise ValueError(f"publication {role} has an invalid file size")
        _validate_file_signature(role, resolved)
        digest = sha256_file(resolved)
        sources[role] = resolved
        snapshots[role] = {"sha256": digest, "size_bytes": size}
    if snapshots["video"]["sha256"] != request.expected_media_hash:
        raise ValueError("variant media hash does not match the final MP4")
    if snapshots["cover"]["sha256"] != request.expected_cover_hash:
        raise ValueError("variant cover hash does not match the final cover")
    return sources, snapshots


def _validated_experiment_binding(
    store: ProjectStore,
    request: OrganicPackageRequest,
    sources: dict[str, Path],
    source_files: dict[str, dict[str, str | int]],
) -> dict[str, str]:
    experiment_store = ExperimentStore(store, request.experiment_id)
    if not experiment_store.manifest_path.is_file():
        raise ValueError("publication requires an existing reviewed experiment manifest")
    manifest = experiment_store.manifest()
    if manifest.project_id != store.project().project_id:
        raise ValueError("publication experiment belongs to a different project")
    if manifest.platform.value != request.platform:
        raise ValueError("publication platform does not match the reviewed experiment")
    if manifest.review_status is not ReviewStatus.APPROVED or manifest.approval_hash is None:
        raise ValueError("publication requires a human-approved experiment")
    variant = next(
        (item for item in manifest.variants if item.variant_id == request.variant_id),
        None,
    )
    if variant is None:
        raise ValueError("publication variant does not exist in the reviewed experiment")
    if variant.review_status is not ReviewStatus.APPROVED or variant.approval_hash is None:
        raise ValueError("publication requires a human-approved variant")
    reviewed_media = store.path(variant.media_path).resolve()
    if sources["video"] != reviewed_media:
        raise ValueError("publication MP4 path does not match the reviewed variant")
    if (
        variant.media_hash != request.expected_media_hash
        or source_files["video"]["sha256"] != variant.media_hash
    ):
        raise ValueError("reviewed variant media is stale")
    if variant.cover_path is None or variant.cover_hash is None:
        raise ValueError("publication requires a reviewed cover artifact")
    reviewed_cover = store.path(variant.cover_path).resolve()
    if sources["cover"] != reviewed_cover:
        raise ValueError("publication cover path does not match the reviewed variant")
    if (
        variant.cover_hash != request.expected_cover_hash
        or source_files["cover"]["sha256"] != variant.cover_hash
    ):
        raise ValueError("reviewed variant cover is stale")
    return {
        "experiment_approval_hash": manifest.approval_hash,
        "variant_approval_hash": variant.approval_hash,
        "locked_factual_hash": variant.locked_factual_hash,
        "evidence_hash": variant.evidence_hash,
        "claims_hash": variant.claims_hash,
        "limitation_hash": variant.limitation_hash,
        "rights_hash": variant.rights_hash,
    }


def _validate_file_signature(role: str, path: Path) -> None:
    if role == "video":
        with path.open("rb") as handle:
            header = handle.read(12)
        if len(header) < 12 or header[4:8] != b"ftyp":
            raise ValueError("publication video is not an identifiable MP4")
    elif role == "cover":
        with path.open("rb") as handle:
            if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError("publication cover is not an identifiable PNG")
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"publication {role} must be UTF-8 text") from exc
        if "\x00" in text:
            raise ValueError(f"publication {role} cannot contain NUL bytes")
        if role == "captions-srt" and "-->" not in text:
            raise ValueError("publication SRT captions contain no timed cue")
        if role == "captions-vtt" and not text.lstrip("\ufeff").startswith("WEBVTT"):
            raise ValueError("publication VTT captions require a WEBVTT header")


def _derive_input_hash(
    request: OrganicPackageRequest,
    source_files: dict[str, dict[str, str | int]],
    experiment_binding: dict[str, str],
) -> str:
    request_identity = request.model_dump(
        mode="json",
        exclude={"final_mp4", "cover_png", "captions_srt", "captions_vtt"},
    )
    return stable_hash(
        {
            "request": request_identity,
            "files": source_files,
            "experiment_binding": experiment_binding,
        }
    )


def _package_files(stage: Path) -> list[PublicationPackageFile]:
    names: dict[ArtifactRole, str] = {
        "video": "video.mp4",
        "cover": "cover.png",
        "captions-srt": "captions.srt",
        "captions-vtt": "captions.vtt",
        "metadata": "post-metadata.json",
        "checklist": "checklist.md",
        "consent": "consent-receipt.json",
    }
    return [
        PublicationPackageFile(
            role=role,
            filename=filename,
            sha256=sha256_file(stage / filename),
            size_bytes=(stage / filename).stat().st_size,
        )
        for role, filename in names.items()
    ]


def _expected_existing_manifest(destination: Path, package_id: str) -> OrganicPublicationPackage:
    manifest_path = destination / "package-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("existing organic package is incomplete and cannot be overwritten")
    manifest = load_model(manifest_path, OrganicPublicationPackage)
    if manifest.package_id != package_id:
        raise ValueError("existing organic package manifest has the wrong package ID")
    return manifest


def _verify_existing_package(destination: Path, manifest: OrganicPublicationPackage) -> None:
    expected_names = {item.filename for item in manifest.files} | {"package-manifest.json"}
    actual_names = {path.name for path in destination.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise ValueError("existing organic package contains missing or unexpected files")
    if any(path.is_dir() for path in destination.iterdir()):
        raise ValueError("existing organic package contains an unexpected directory")
    for item in manifest.files:
        path = destination / item.filename
        if (
            not path.is_file()
            or path.stat().st_size != item.size_bytes
            or sha256_file(path) != item.sha256
        ):
            raise ValueError(f"existing organic package file is stale: {item.filename}")
    metadata = load_model(destination / "post-metadata.json", OrganicPostMetadata)
    consent = load_model(destination / "consent-receipt.json", HumanPublicationConsent)
    if (
        metadata.metadata_id != manifest.metadata_id
        or metadata.metadata_hash != manifest.metadata_hash
        or metadata.experiment_id != manifest.experiment_id
        or metadata.variant_id != manifest.variant_id
        or metadata.platform != manifest.platform
    ):
        raise ValueError("existing organic package metadata does not match its manifest")
    if consent != manifest.consent:
        raise ValueError("existing organic package consent does not match its manifest")


def _remove_verified_stage(stage: Path, expected_parent: Path) -> None:
    if not stage.exists():
        return
    resolved = stage.resolve()
    parent = expected_parent.resolve()
    if resolved.parent != parent or not resolved.name.startswith(".organic-package-"):
        raise ValueError("refusing to remove an unexpected publication staging directory")
    shutil.rmtree(resolved)


__all__ = [
    "GRANT_CONFIRMATION",
    "build_organic_publication_package",
    "organic_package_input_hash",
    "record_publication_consent",
]
