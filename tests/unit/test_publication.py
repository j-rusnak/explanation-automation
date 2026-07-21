from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from techshort.domain.hashing import sha256_file
from techshort.domain.storage import ProjectStore, load_model
from techshort.experiments import (
    ExperimentStore,
    ExperimentVariable,
    VariantRole,
    approve_experiment,
    build_variant,
    initialize_experiment,
)
from techshort.experiments import (
    OrganicPlatform as ExperimentPlatform,
)
from techshort.publication import (
    GRANT_CONFIRMATION,
    ManualOrganicProvider,
    OrganicPackageRequest,
    OrganicPostMetadata,
    OrganicPublicationPackage,
    PlatformUnavailableError,
    build_organic_publication_package,
    official_api_provider,
    organic_package_input_hash,
    record_publication_consent,
)


def _store_and_request(
    tmp_path: Path, *, platform: str = "tiktok", approve: bool = True
) -> tuple[ProjectStore, OrganicPackageRequest]:
    store = ProjectStore(tmp_path / "projects", "publication-test")
    store.initialize("Publication test")
    artifact_directory = store.path("renders/final")
    control_video = artifact_directory / "control.mp4"
    treatment_video = artifact_directory / "treatment.mp4"
    control_video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"control-video" * 4)
    treatment_video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"treatment-video" * 4)
    cover = store.path("export/cover.png")
    cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"reviewed-cover")
    captions_srt = store.path("captions/reviewed.srt")
    captions_vtt = store.path("captions/reviewed.vtt")
    captions_srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nA reviewed caption.\n",
        encoding="utf-8",
    )
    captions_vtt.write_text(
        "WEBVTT\n\n00:00.000 --> 00:02.000\nA reviewed caption.\n",
        encoding="utf-8",
    )
    locked_hashes = {
        "locked_factual_hash": "1" * 64,
        "evidence_hash": "2" * 64,
        "claims_hash": "3" * 64,
        "limitation_hash": "4" * 64,
        "rights_hash": "5" * 64,
    }
    variants = [
        build_variant(
            label="Control hook",
            role=VariantRole.CONTROL,
            variable=ExperimentVariable.HOOK,
            variable_value="Question hook",
            media_path="renders/final/control.mp4",
            media_hash=sha256_file(control_video),
            cover_path="export/cover.png",
            cover_hash=sha256_file(cover),
            **locked_hashes,
        ),
        build_variant(
            label="Treatment hook",
            role=VariantRole.TREATMENT,
            variable=ExperimentVariable.HOOK,
            variable_value="Visual surprise hook",
            media_path="renders/final/treatment.mp4",
            media_hash=sha256_file(treatment_video),
            cover_path="export/cover.png",
            cover_hash=sha256_file(cover),
            **locked_hashes,
        ),
    ]
    manifest = initialize_experiment(
        store,
        name="Organic hook test",
        hypothesis="A visual surprise hook will improve completion rate.",
        platform=ExperimentPlatform(platform),
        variable=ExperimentVariable.HOOK,
        variants=variants,
    )
    experiment_store = ExperimentStore(store, manifest.experiment_id)
    if approve:
        manifest = approve_experiment(experiment_store, "local-reviewer")
    selected_variant = manifest.variants[0]
    request = OrganicPackageRequest(
        experiment_id=manifest.experiment_id,
        variant_id=selected_variant.variant_id,
        platform=platform,
        final_mp4=selected_variant.media_path,
        expected_media_hash=selected_variant.media_hash,
        cover_png=selected_variant.cover_path or "",
        expected_cover_hash=selected_variant.cover_hash or "",
        captions_srt=str(captions_srt.relative_to(store.root)),
        captions_vtt=str(captions_vtt.relative_to(store.root)),
        title="Why a straight blade can look bent",
        post_copy=(
            "A rolling shutter records image rows at different moments. This explains the "
            "specific timing skew shown here, but it does not prevent every kind of distortion."
        ),
        alt_text=(
            "A vertical technical animation compares a straight rotating blade with its "
            "row-by-row rolling-shutter image."
        ),
        hashtags=["CameraTech", "EngineeringExplained"],
        evidence_url="https://example.test/rolling-shutter-evidence",
    )
    return store, request


@pytest.mark.parametrize(
    ("platform", "platform_label"),
    [("tiktok", "TikTok"), ("instagram-reels", "Instagram Reels")],
)
def test_manual_provider_builds_checksummed_per_variant_packages(
    tmp_path: Path, platform: str, platform_label: str
) -> None:
    store, request = _store_and_request(tmp_path, platform=platform)

    result = build_organic_publication_package(store, request)
    repeated = build_organic_publication_package(store, request)

    assert repeated == result
    package = store.path(result.package_directory)
    assert package.parent.name == platform
    assert {path.name for path in package.iterdir()} == {
        "video.mp4",
        "cover.png",
        "captions.srt",
        "captions.vtt",
        "post-metadata.json",
        "checklist.md",
        "consent-receipt.json",
        "package-manifest.json",
    }
    manifest = load_model(package / "package-manifest.json", OrganicPublicationPackage)
    metadata = load_model(package / "post-metadata.json", OrganicPostMetadata)
    assert manifest == result.manifest
    assert manifest.package_input_hash == organic_package_input_hash(store, request)
    assert manifest.variant_media_hash == request.expected_media_hash
    assert manifest.variant_cover_hash == request.expected_cover_hash
    assert manifest.experiment_approval_hash
    assert manifest.variant_approval_hash
    assert manifest.locked_factual_hash == "1" * 64
    assert manifest.rights_hash == "5" * 64
    assert manifest.consent.state == "pending"
    assert not manifest.manual_upload_authorized
    assert not manifest.automated_upload
    assert not manifest.claimed_posted
    assert metadata.consent_state == "pending"
    assert metadata.caption_text.endswith("#CameraTech #EngineeringExplained")
    checklist = (package / "checklist.md").read_text(encoding="utf-8")
    assert platform_label in checklist
    assert "This package has not been posted" in checklist
    assert "- [ ] Explicit human publication consent" in checklist
    for item in manifest.files:
        assert sha256_file(package / item.filename) == item.sha256
    assert not hasattr(ManualOrganicProvider(request.platform), "upload")
    assert not hasattr(ManualOrganicProvider(request.platform), "publish")


def test_granted_consent_creates_a_new_immutable_authorized_package(tmp_path: Path) -> None:
    store, request = _store_and_request(tmp_path)
    pending = build_organic_publication_package(store, request)
    consent = record_publication_consent(
        pending.manifest,
        state="granted",
        reviewer_identifier="local-reviewer",
        confirmation=GRANT_CONFIRMATION,
        decided_at=datetime(2026, 7, 20, 16, 30, tzinfo=UTC),
    )

    authorized = build_organic_publication_package(store, request, consent=consent)

    assert authorized.package_directory != pending.package_directory
    assert store.path(pending.package_directory).is_dir()
    assert authorized.manifest.consent.state == "granted"
    assert authorized.manifest.manual_upload_authorized
    assert not authorized.manifest.claimed_posted
    package = store.path(authorized.package_directory)
    metadata = load_model(package / "post-metadata.json", OrganicPostMetadata)
    assert metadata.manual_upload_authorized
    assert "- [x] Explicit human publication consent" in (package / "checklist.md").read_text(
        encoding="utf-8"
    )


def test_consent_is_stale_when_exact_package_copy_changes(tmp_path: Path) -> None:
    store, request = _store_and_request(tmp_path)
    pending = build_organic_publication_package(store, request)
    consent = record_publication_consent(
        pending.manifest,
        state="granted",
        reviewer_identifier="local-reviewer",
        confirmation=GRANT_CONFIRMATION,
        decided_at=datetime(2026, 7, 20, 16, 30, tzinfo=UTC),
    )
    changed = request.model_copy(update={"post_copy": request.post_copy + " Updated."})

    with pytest.raises(ValueError, match="consent is stale"):
        build_organic_publication_package(store, changed, consent=consent)


def test_existing_package_tampering_is_detected_without_overwrite(tmp_path: Path) -> None:
    store, request = _store_and_request(tmp_path)
    result = build_organic_publication_package(store, request)
    checklist = store.path(result.package_directory) / "checklist.md"
    checklist.write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="package file is stale"):
        build_organic_publication_package(store, request)

    assert checklist.read_text(encoding="utf-8") == "tampered"


def test_publication_inputs_reject_traversal_wrong_types_and_token_fields(
    tmp_path: Path,
) -> None:
    store, request = _store_and_request(tmp_path)
    payload = request.model_dump(mode="json")
    payload["access_token"] = request.title
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OrganicPackageRequest.model_validate(payload)

    traversal = request.model_copy(update={"final_mp4": "../../private.mp4"})
    with pytest.raises(ValueError, match="escapes project root"):
        build_organic_publication_package(store, traversal)

    svg = store.path(request.cover_png).with_suffix(".svg")
    svg.write_text("<svg onload='steal()'/>", encoding="utf-8")
    wrong_type = request.model_copy(update={"cover_png": str(svg.relative_to(store.root))})
    with pytest.raises(ValueError, match="must use .png"):
        build_organic_publication_package(store, wrong_type)


def test_official_provider_is_clear_unavailable_and_never_reads_credentials(
    tmp_path: Path,
) -> None:
    store, request = _store_and_request(tmp_path)
    provider = official_api_provider("tiktok")

    diagnostic = provider.diagnostics()
    assert diagnostic.status == "unavailable"
    assert not diagnostic.local_package_supported
    assert not diagnostic.automated_publication_supported
    assert not diagnostic.credentials_read
    assert not diagnostic.credentials_stored
    assert "ManualOrganicProvider" in " ".join(diagnostic.next_steps)
    assert vars(provider) == {
        "platform": "tiktok",
        "provider_name": "tiktok-official-content-posting-api",
    }

    with pytest.raises(PlatformUnavailableError, match="did not read or store"):
        build_organic_publication_package(store, request, provider=provider)
    assert not store.path(f"experiments/{request.experiment_id}/publication").exists()


def test_publication_requires_a_current_approved_experiment_variant(tmp_path: Path) -> None:
    store, request = _store_and_request(tmp_path, approve=False)

    with pytest.raises(ValueError, match="human-approved experiment"):
        build_organic_publication_package(store, request)

    approve_experiment(ExperimentStore(store, request.experiment_id), "local-reviewer")
    unknown = request.model_copy(update={"variant_id": "var-0000000000000000"})
    with pytest.raises(ValueError, match="variant does not exist"):
        build_organic_publication_package(store, unknown)


def test_publication_rejects_media_path_and_reviewed_hash_mismatches(tmp_path: Path) -> None:
    store, request = _store_and_request(tmp_path)
    other_video = store.path("renders/final/copy.mp4")
    other_video.write_bytes(store.path(request.final_mp4).read_bytes())
    wrong_path = request.model_copy(update={"final_mp4": str(other_video.relative_to(store.root))})
    with pytest.raises(ValueError, match="MP4 path does not match"):
        build_organic_publication_package(store, wrong_path)

    video = store.path(request.final_mp4)
    video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"changed-video" * 5)
    changed = request.model_copy(update={"expected_media_hash": sha256_file(video)})
    with pytest.raises(ValueError, match="reviewed variant media is stale"):
        build_organic_publication_package(store, changed)


def test_publication_rejects_a_stale_reviewed_cover(tmp_path: Path) -> None:
    store, request = _store_and_request(tmp_path)
    cover = store.path(request.cover_png)
    cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"changed-cover")
    changed = request.model_copy(update={"expected_cover_hash": sha256_file(cover)})

    with pytest.raises(ValueError, match="reviewed variant cover is stale"):
        build_organic_publication_package(store, changed)


def test_manifest_hash_rejects_mutation_and_consent_requires_exact_phrase(
    tmp_path: Path,
) -> None:
    store, request = _store_and_request(tmp_path)
    pending = build_organic_publication_package(store, request)
    payload = pending.manifest.model_dump(mode="json")
    payload["package_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="package hash"):
        OrganicPublicationPackage.model_validate(payload)

    with pytest.raises(ValidationError, match="exact confirmation"):
        record_publication_consent(
            pending.manifest,
            state="granted",
            reviewer_identifier="local-reviewer",
            confirmation="yes",
            decided_at=datetime(2026, 7, 20, 16, 30, tzinfo=UTC),
        )
