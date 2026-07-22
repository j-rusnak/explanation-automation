from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from techshort.domain.hashing import sha256_file
from techshort.domain.models import ReviewStatus
from techshort.domain.storage import ProjectStore, load_model
from techshort.experiments import (
    ExperimentStore,
    ExperimentVariable,
    VariantRole,
    approve_experiment,
    build_variant,
    initialize_experiment,
)
from techshort.experiments import OrganicPlatform as ExperimentPlatform
from techshort.experiments.creative import ExportExperimentContract
from techshort.publication import (
    GRANT_CONFIRMATION,
    OrganicPackageRequest,
    build_organic_publication_package,
    record_publication_consent,
)
from techshort.publication.official.tiktok import (
    TikTokApiError,
    TikTokDraftInitialization,
    TikTokPublishStatus,
    TikTokTransportError,
    TikTokUploadReceipt,
)
from techshort.publication.upload_models import (
    DRAFT_TRANSFER_CONFIRMATION,
    TikTokDraftUploadAttempt,
    TikTokDraftUploadConsent,
    TikTokDraftUploadStatusReceipt,
)
from techshort.publication.upload_service import (
    create_tiktok_draft_upload_intent,
    execute_tiktok_draft_upload,
    grant_tiktok_draft_upload_consent,
    poll_tiktok_draft_upload,
    preflight_tiktok_draft_upload,
)

FIXED_TIME = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
ACCOUNT_HASH = "a" * 64


class FakeTikTokClient:
    def __init__(
        self,
        *,
        before_initialize: Callable[[Path], None] | None = None,
        initialize_error: Exception | None = None,
        status: str = "SEND_TO_USER_INBOX",
        publicly_available: bool = False,
        account_subject_hash: str = ACCOUNT_HASH,
        fetch_error: Exception | None = None,
    ) -> None:
        self.before_initialize = before_initialize
        self.initialize_error = initialize_error
        self.status = status
        self.publicly_available = publicly_available
        self._account_subject_hash = account_subject_hash
        self.fetch_error = fetch_error
        self.initialize_calls = 0
        self.upload_calls = 0
        self.status_calls = 0

    @property
    def account_subject_hash(self) -> str:
        return self._account_subject_hash

    def initialize_draft(self, video_path: str | Path) -> TikTokDraftInitialization:
        self.initialize_calls += 1
        path = Path(video_path)
        if self.before_initialize is not None:
            self.before_initialize(path)
        if self.initialize_error is not None:
            raise self.initialize_error
        return TikTokDraftInitialization(
            publish_id="publish-test-1",
            video_size=path.stat().st_size,
            upload_host="open-upload.tiktokapis.com",
        )

    def upload_video(
        self,
        initialization: TikTokDraftInitialization,
        video_path: str | Path,
    ) -> TikTokUploadReceipt:
        self.upload_calls += 1
        return TikTokUploadReceipt(
            publish_id=initialization.publish_id,
            bytes_uploaded=Path(video_path).stat().st_size,
            http_status=201,
        )

    def fetch_status(self, publish_id: str) -> TikTokPublishStatus:
        self.status_calls += 1
        if self.fetch_error is not None:
            raise self.fetch_error
        return TikTokPublishStatus(
            publish_id=publish_id,
            status=self.status,  # type: ignore[arg-type]
            uploaded_bytes=128,
            publicly_available=self.publicly_available,
            publicly_available_post_count=1 if self.publicly_available else 0,
            fail_reason=None,
        )


def _authorized_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProjectStore, Path, ExportExperimentContract]:
    store = ProjectStore(tmp_path / "projects", "upload-test")
    store.initialize("Upload test")
    final_directory = store.path("renders/final")
    control_video = final_directory / "control.mp4"
    treatment_video = final_directory / "treatment.mp4"
    control_video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"control-video" * 12)
    treatment_video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"treatment-video" * 12)
    cover = store.path("export/cover.png")
    cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"reviewed-cover")
    srt = store.path("captions/reviewed.srt")
    vtt = store.path("captions/reviewed.vtt")
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nA burned-in reviewed caption.\n",
        encoding="utf-8",
    )
    vtt.write_text(
        "WEBVTT\n\n00:00.000 --> 00:02.000\nA burned-in reviewed caption.\n",
        encoding="utf-8",
    )
    locked = {
        "locked_factual_hash": "1" * 64,
        "evidence_hash": "2" * 64,
        "claims_hash": "3" * 64,
        "limitation_hash": "4" * 64,
        "rights_hash": "5" * 64,
    }
    variants = [
        build_variant(
            label="Control cover",
            role=VariantRole.CONTROL,
            variable=ExperimentVariable.HOOK,
            variable_value="Evidence first",
            media_path="renders/final/control.mp4",
            media_hash=sha256_file(control_video),
            cover_path="export/cover.png",
            cover_hash=sha256_file(cover),
            **locked,
        ),
        build_variant(
            label="Treatment cover",
            role=VariantRole.TREATMENT,
            variable=ExperimentVariable.HOOK,
            variable_value="Question first",
            media_path="renders/final/treatment.mp4",
            media_hash=sha256_file(treatment_video),
            cover_path="export/cover.png",
            cover_hash=sha256_file(cover),
            **locked,
        ),
    ]
    manifest = initialize_experiment(
        store,
        name="TikTok upload test",
        hypothesis="A reviewed hook may affect organic completion rate.",
        platform=ExperimentPlatform.TIKTOK,
        variable=ExperimentVariable.HOOK,
        variants=variants,
    )
    manifest = approve_experiment(ExperimentStore(store, manifest.experiment_id), "reviewer")
    selected = manifest.variants[0]
    request = OrganicPackageRequest(
        experiment_id=manifest.experiment_id,
        variant_id=selected.variant_id,
        platform="tiktok",
        final_mp4=selected.media_path,
        expected_media_hash=selected.media_hash,
        cover_png=selected.cover_path or "",
        expected_cover_hash=selected.cover_hash or "",
        captions_srt=str(srt.relative_to(store.root)),
        captions_vtt=str(vtt.relative_to(store.root)),
        title="Why motion bends in a rolling shutter",
        post_copy="A reviewed technical explanation with one meaningful limitation.",
        alt_text="A vertical animation explains rolling-shutter timing row by row.",
        hashtags=["CameraTech"],
    )
    pending = build_organic_publication_package(store, request)
    manual_consent = record_publication_consent(
        pending.manifest,
        state="granted",
        reviewer_identifier="reviewer",
        confirmation=GRANT_CONFIRMATION,
        decided_at=FIXED_TIME,
    )
    package = build_organic_publication_package(store, request, consent=manual_consent)
    project = store.project()
    project.downstream_valid = True
    project.stale_artifacts = []
    project.approvals.claims = ReviewStatus.APPROVED
    project.approvals.script = ReviewStatus.APPROVED
    project.approvals.storyboard = ReviewStatus.APPROVED
    project.approvals.rights = ReviewStatus.APPROVED
    project.approvals.final = ReviewStatus.APPROVED
    store.save_project(project)
    contract = ExportExperimentContract(
        media_path=selected.media_path,
        media_hash=selected.media_hash,
        captions_srt_path=str(srt.relative_to(store.root)).replace("\\", "/"),
        captions_vtt_path=str(vtt.relative_to(store.root)).replace("\\", "/"),
        **locked,
    )
    monkeypatch.setattr(
        "techshort.publication.upload_service._validated_export_contract",
        lambda _store: contract,
    )
    return store, store.path(package.package_directory) / "package-manifest.json", contract


def _intent_consent_preflight(
    store: ProjectStore,
    manifest_path: Path,
):
    intent = create_tiktok_draft_upload_intent(
        store,
        manifest_path,
        target_account_subject_sha256=ACCOUNT_HASH,
        target_account_label="@reviewed-account",
        requested_by="local-reviewer",
        requested_at=FIXED_TIME,
    )
    preflight = preflight_tiktok_draft_upload(
        store,
        manifest_path,
        intent,
        credentials_available=True,
        checked_at=FIXED_TIME,
    )
    consent = grant_tiktok_draft_upload_consent(
        intent,
        reviewer_identifier="local-reviewer",
        confirmation=DRAFT_TRANSFER_CONFIRMATION,
        decided_at=FIXED_TIME,
        recorded_at=FIXED_TIME,
    )
    return intent, consent, preflight


def test_preflight_is_draft_only_and_reports_cover_and_caption_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest_path, _contract = _authorized_package(tmp_path, monkeypatch)
    intent = create_tiktok_draft_upload_intent(
        store,
        manifest_path,
        target_account_subject_sha256=ACCOUNT_HASH,
        target_account_label="@reviewed-account",
        requested_by="reviewer",
        requested_at=FIXED_TIME,
    )

    preflight = preflight_tiktok_draft_upload(
        store,
        manifest_path,
        intent,
        credentials_available=False,
        checked_at=FIXED_TIME,
    )

    checks = {item.code: item for item in preflight.checks}
    assert preflight.state == "blocked"
    assert checks["credentials"].state == "failure"
    assert checks["draft-only"].state == "pass"
    assert checks["separate-cover-unsupported"].state == "warning"
    assert "manually" in checks["separate-cover-unsupported"].detail
    assert checks["burned-captions-retained"].state == "pass"
    assert "not sent" in checks["burned-captions-retained"].detail
    assert not store.path(f"experiments/{intent.experiment_id}/uploads").exists()


def test_attempt_records_are_atomic_before_network_and_no_secret_is_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest_path, _contract = _authorized_package(tmp_path, monkeypatch)
    intent, consent, preflight = _intent_consent_preflight(store, manifest_path)

    def assert_pre_network_records(video: Path) -> None:
        upload = store.path(f"experiments/{intent.experiment_id}/uploads/{intent.intent_id}")
        assert video == upload / "video.mp4"
        assert sha256_file(video) == intent.video_hash
        assert {item.name for item in upload.iterdir()} == {
            "intent.json",
            "consent.json",
            "attempt.json",
            "preflight.json",
            "video.mp4",
            "receipts",
        }
        attempt = load_model(upload / "attempt.json", TikTokDraftUploadAttempt)
        assert not attempt.network_started
        serialized = "".join(path.read_text(encoding="utf-8") for path in upload.rglob("*.json"))
        assert "access-token" not in serialized
        assert "upload_id=test" not in serialized

    client = FakeTikTokClient(before_initialize=assert_pre_network_records)
    receipt = execute_tiktok_draft_upload(
        store,
        manifest_path,
        intent,
        consent,
        preflight,
        client,
        prepared_at=FIXED_TIME,
    )

    assert receipt.state == "uploaded"
    assert receipt.sequence_number == 1
    assert receipt.publish_id == "publish-test-1"
    assert client.initialize_calls == client.upload_calls == 1
    upload = store.path(f"experiments/{intent.experiment_id}/uploads/{intent.intent_id}")
    receipts = sorted((upload / "receipts").iterdir())
    assert len(receipts) == 2
    assert load_model(receipts[0], TikTokDraftUploadStatusReceipt).state == "initialized"


def test_any_attempt_blocks_automatic_retry_even_after_ambiguous_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest_path, _contract = _authorized_package(tmp_path, monkeypatch)
    intent, consent, preflight = _intent_consent_preflight(store, manifest_path)
    first_client = FakeTikTokClient(
        initialize_error=TikTokTransportError("offline test initialization")
    )

    ambiguous = execute_tiktok_draft_upload(
        store,
        manifest_path,
        intent,
        consent,
        preflight,
        first_client,
        prepared_at=FIXED_TIME,
    )

    assert ambiguous.state == "ambiguous"
    assert "do not retry" in (ambiguous.error_message or "")
    second_client = FakeTikTokClient()
    with pytest.raises(ValueError, match="already has an upload attempt"):
        execute_tiktok_draft_upload(
            store,
            manifest_path,
            intent,
            consent,
            preflight,
            second_client,
            prepared_at=FIXED_TIME,
        )
    assert second_client.initialize_calls == 0


def test_api_consent_is_separate_and_exact_account_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest_path, _contract = _authorized_package(tmp_path, monkeypatch)
    intent, _consent, preflight = _intent_consent_preflight(store, manifest_path)
    with pytest.raises(ValidationError, match="exact confirmation"):
        grant_tiktok_draft_upload_consent(
            intent,
            reviewer_identifier="reviewer",
            confirmation=GRANT_CONFIRMATION,
            decided_at=FIXED_TIME,
            recorded_at=FIXED_TIME,
        )
    pending = TikTokDraftUploadConsent.create(
        intent,
        state="pending",
        recorded_at=FIXED_TIME,
    )
    client = FakeTikTokClient()
    with pytest.raises(ValueError, match="separate consent"):
        execute_tiktok_draft_upload(
            store,
            manifest_path,
            intent,
            pending,
            preflight,
            client,
            prepared_at=FIXED_TIME,
        )
    assert client.initialize_calls == 0
    assert not store.path(f"experiments/{intent.experiment_id}/uploads").exists()


def test_authenticated_account_must_match_for_upload_and_poll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest_path, _contract = _authorized_package(tmp_path, monkeypatch)
    intent, consent, preflight = _intent_consent_preflight(store, manifest_path)
    wrong_account = FakeTikTokClient(account_subject_hash="b" * 64)
    with pytest.raises(ValueError, match="authenticated TikTok account"):
        execute_tiktok_draft_upload(
            store,
            manifest_path,
            intent,
            consent,
            preflight,
            wrong_account,
            prepared_at=FIXED_TIME,
        )
    assert wrong_account.initialize_calls == 0
    assert not store.path(f"experiments/{intent.experiment_id}/uploads").exists()

    execute_tiktok_draft_upload(
        store,
        manifest_path,
        intent,
        consent,
        preflight,
        FakeTikTokClient(),
        prepared_at=FIXED_TIME,
    )
    with pytest.raises(ValueError, match="authenticated TikTok account"):
        poll_tiktok_draft_upload(
            store,
            intent.experiment_id,
            intent.intent_id,
            wrong_account,
            recorded_at=FIXED_TIME,
        )
    assert wrong_account.status_calls == 0


def test_package_tamper_and_stale_current_rights_block_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest_path, contract = _authorized_package(tmp_path, monkeypatch)
    intent, consent, preflight = _intent_consent_preflight(store, manifest_path)
    video = manifest_path.parent / "video.mp4"
    video.write_bytes(video.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="artifact is stale"):
        execute_tiktok_draft_upload(
            store,
            manifest_path,
            intent,
            consent,
            preflight,
            FakeTikTokClient(),
        )

    # Restore from the reviewed media, then make the current rights binding stale.
    experiment = ExperimentStore(store, intent.experiment_id).manifest()
    reviewed = store.path(experiment.variants[0].media_path)
    video.write_bytes(reviewed.read_bytes())
    stale_contract = ExportExperimentContract(**{**contract.__dict__, "rights_hash": "9" * 64})
    monkeypatch.setattr(
        "techshort.publication.upload_service._validated_export_contract",
        lambda _store: stale_contract,
    )
    client = FakeTikTokClient()
    with pytest.raises(ValueError, match="stale rights hash"):
        execute_tiktok_draft_upload(
            store,
            manifest_path,
            intent,
            consent,
            preflight,
            client,
        )
    assert client.initialize_calls == 0


def test_poll_appends_status_without_uploading_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest_path, _contract = _authorized_package(tmp_path, monkeypatch)
    intent, consent, preflight = _intent_consent_preflight(store, manifest_path)
    upload_client = FakeTikTokClient()
    execute_tiktok_draft_upload(
        store,
        manifest_path,
        intent,
        consent,
        preflight,
        upload_client,
        prepared_at=FIXED_TIME,
    )
    poll_client = FakeTikTokClient(status="SEND_TO_USER_INBOX")

    receipt = poll_tiktok_draft_upload(
        store,
        intent.experiment_id,
        intent.intent_id,
        poll_client,
        recorded_at=FIXED_TIME,
    )

    assert receipt.state == "pending-user-action"
    assert receipt.sequence_number == 2
    assert poll_client.status_calls == 1
    assert poll_client.initialize_calls == poll_client.upload_calls == 0
    upload = store.path(f"experiments/{intent.experiment_id}/uploads/{intent.intent_id}")
    assert len(list((upload / "receipts").iterdir())) == 3


def test_poll_records_unexpected_public_availability_as_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest_path, _contract = _authorized_package(tmp_path, monkeypatch)
    intent, consent, preflight = _intent_consent_preflight(store, manifest_path)
    execute_tiktok_draft_upload(
        store,
        manifest_path,
        intent,
        consent,
        preflight,
        FakeTikTokClient(),
        prepared_at=FIXED_TIME,
    )

    receipt = poll_tiktok_draft_upload(
        store,
        intent.experiment_id,
        intent.intent_id,
        FakeTikTokClient(status="PUBLISH_COMPLETE", publicly_available=True),
        recorded_at=FIXED_TIME,
    )

    assert receipt.state == "ambiguous"
    assert "unexpected public availability" in (receipt.error_message or "")


def test_rejected_status_fetch_does_not_claim_the_upload_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest_path, _contract = _authorized_package(tmp_path, monkeypatch)
    intent, consent, preflight = _intent_consent_preflight(store, manifest_path)
    execute_tiktok_draft_upload(
        store,
        manifest_path,
        intent,
        consent,
        preflight,
        FakeTikTokClient(),
        prepared_at=FIXED_TIME,
    )
    status_error = TikTokApiError(
        operation="status fetch",
        code="access_denied",
        message="request rejected",
        http_status=403,
    )

    receipt = poll_tiktok_draft_upload(
        store,
        intent.experiment_id,
        intent.intent_id,
        FakeTikTokClient(fetch_error=status_error),
        recorded_at=FIXED_TIME,
    )

    assert receipt.state == "ambiguous"
    assert receipt.error_code == "status-fetch-rejected"
    assert receipt.publish_id == "publish-test-1"


def test_manifest_path_is_project_constrained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _manifest_path, _contract = _authorized_package(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="escapes project root"):
        create_tiktok_draft_upload_intent(
            store,
            "../../outside/package-manifest.json",
            target_account_subject_sha256=ACCOUNT_HASH,
            target_account_label="@reviewed-account",
            requested_by="reviewer",
            requested_at=FIXED_TIME,
        )
