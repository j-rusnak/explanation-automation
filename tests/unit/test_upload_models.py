from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from techshort.publication.upload_models import (
    DRAFT_TRANSFER_CONFIRMATION,
    TikTokDraftUploadAttempt,
    TikTokDraftUploadConsent,
    TikTokDraftUploadIntent,
    TikTokDraftUploadPreflight,
    TikTokDraftUploadStatusReceipt,
    TikTokUploadDiagnostic,
    TikTokUploadPreflightCheck,
)

NOW = datetime(2026, 7, 22, 14, 30, tzinfo=UTC)


def _intent() -> TikTokDraftUploadIntent:
    return TikTokDraftUploadIntent.create(
        package_id="organic-package-0123456789abcdef",
        package_hash="1" * 64,
        experiment_id="exp-0123456789abcdef",
        variant_id="var-fedcba9876543210",
        video_hash="2" * 64,
        target_account_subject_sha256="3" * 64,
        target_account_label="@techshort-lab",
        requested_by="local-reviewer",
        requested_at=NOW,
    )


def _granted_consent(intent: TikTokDraftUploadIntent) -> TikTokDraftUploadConsent:
    return TikTokDraftUploadConsent.create(
        intent,
        state="granted",
        reviewer_identifier="local-reviewer",
        confirmation=DRAFT_TRANSFER_CONFIRMATION,
        decided_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1),
    )


def _attempt() -> TikTokDraftUploadAttempt:
    intent = _intent()
    return TikTokDraftUploadAttempt.create(
        intent,
        _granted_consent(intent),
        prepared_at=NOW + timedelta(minutes=2),
    )


def test_intent_is_content_addressed_strict_frozen_and_json_round_trippable() -> None:
    intent = _intent()
    repeated = _intent()

    assert repeated == intent
    assert intent.intent_id == f"tiktok-upload-intent-{intent.intent_hash[:16]}"
    assert intent.provider == "tiktok-content-posting-api"
    assert intent.operation == "draft-transfer"
    assert TikTokDraftUploadIntent.model_validate_json(intent.model_dump_json()) == intent

    tampered = intent.model_dump(mode="python")
    tampered["video_hash"] = "4" * 64
    with pytest.raises(ValidationError, match="intent hash"):
        TikTokDraftUploadIntent.model_validate(tampered)
    with pytest.raises(ValidationError, match="frozen"):
        intent.target_account_label = "changed"  # type: ignore[misc]


def test_intent_rejects_naive_time_active_text_and_token_fields() -> None:
    values = {
        "package_id": "organic-package-0123456789abcdef",
        "package_hash": "1" * 64,
        "experiment_id": "exp-0123456789abcdef",
        "variant_id": "var-fedcba9876543210",
        "video_hash": "2" * 64,
        "target_account_subject_sha256": "3" * 64,
        "target_account_label": "@techshort-lab",
        "requested_by": "local-reviewer",
        "requested_at": NOW.replace(tzinfo=None),
    }
    with pytest.raises(ValidationError, match="must include a timezone"):
        TikTokDraftUploadIntent.create(**values)

    values["requested_at"] = NOW
    values["target_account_label"] = "<script>steal()</script>"
    with pytest.raises(ValidationError, match="active content"):
        TikTokDraftUploadIntent.create(**values)

    payload = _intent().model_dump(mode="python")
    payload["access_token"] = payload["intent_id"]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TikTokDraftUploadIntent.model_validate(payload)


def test_consent_states_are_append_only_and_require_exact_grant_phrase() -> None:
    intent = _intent()
    pending = TikTokDraftUploadConsent.create(intent, state="pending", recorded_at=NOW)
    granted = _granted_consent(intent)
    repeated = _granted_consent(intent)

    assert pending.state == "pending"
    assert repeated == granted
    assert granted.receipt_id.startswith("tiktok-upload-consent-")

    with pytest.raises(ValidationError, match="exact confirmation"):
        TikTokDraftUploadConsent.create(
            intent,
            state="granted",
            reviewer_identifier="local-reviewer",
            confirmation="Yes, upload it.",
            decided_at=NOW,
            recorded_at=NOW,
        )
    with pytest.raises(ValidationError, match="pending upload consent"):
        TikTokDraftUploadConsent.create(
            intent,
            state="pending",
            reviewer_identifier="local-reviewer",
            recorded_at=NOW,
        )

    revoked = TikTokDraftUploadConsent.create(
        intent,
        state="revoked",
        reviewer_identifier="local-reviewer",
        confirmation="Do not transfer this package.",
        decided_at=NOW + timedelta(minutes=3),
        recorded_at=NOW + timedelta(minutes=3),
        supersedes_receipt_id=granted.receipt_id,
    )
    assert revoked.state == "revoked"
    assert revoked.receipt_id != granted.receipt_id


def test_consent_receipt_rejects_tampering_and_naive_decision_time() -> None:
    intent = _intent()
    granted = _granted_consent(intent)
    tampered = granted.model_dump(mode="python")
    tampered["package_hash"] = "a" * 64
    with pytest.raises(ValidationError, match="receipt ID"):
        TikTokDraftUploadConsent.model_validate(tampered)

    with pytest.raises(ValidationError, match="must include a timezone"):
        TikTokDraftUploadConsent.create(
            intent,
            state="declined",
            reviewer_identifier="local-reviewer",
            confirmation="Wrong account.",
            decided_at=NOW.replace(tzinfo=None),
            recorded_at=NOW,
        )


def test_attempt_is_a_granted_pre_network_snapshot() -> None:
    attempt = _attempt()

    assert not attempt.network_started
    assert attempt.consent.state == "granted"
    assert attempt.attempt_id == f"tiktok-upload-attempt-{attempt.attempt_hash[:16]}"

    pending = TikTokDraftUploadConsent.create(
        attempt.intent,
        state="pending",
        recorded_at=NOW,
    )
    with pytest.raises(ValidationError, match="requires granted human consent"):
        TikTokDraftUploadAttempt.create(
            attempt.intent,
            pending,
            prepared_at=NOW + timedelta(minutes=2),
        )

    payload = attempt.model_dump(mode="python")
    payload["network_started"] = True
    with pytest.raises(ValidationError):
        TikTokDraftUploadAttempt.model_validate(payload)


def test_status_receipts_form_a_content_addressed_append_only_chain() -> None:
    attempt = _attempt()
    initialized = TikTokDraftUploadStatusReceipt.create(
        attempt,
        state="initialized",
        recorded_at=NOW + timedelta(minutes=2),
    )
    uploaded = TikTokDraftUploadStatusReceipt.create(
        attempt,
        previous=initialized,
        state="uploaded",
        publish_id="v_pub_url~reviewed-draft-123",
        provider_updated_at=NOW + timedelta(minutes=3),
        recorded_at=NOW + timedelta(minutes=3),
    )
    pending = TikTokDraftUploadStatusReceipt.create(
        attempt,
        previous=uploaded,
        state="pending-user-action",
        publish_id="v_pub_url~reviewed-draft-123",
        provider_updated_at=NOW + timedelta(minutes=4),
        recorded_at=NOW + timedelta(minutes=4),
    )

    assert initialized.sequence_number == 0
    assert uploaded.sequence_number == 1
    assert uploaded.previous_receipt_id == initialized.receipt_id
    assert pending.sequence_number == 2
    assert pending.previous_state == "uploaded"
    assert pending.receipt_id == f"tiktok-upload-status-{pending.receipt_hash[:16]}"

    tampered = pending.model_dump(mode="python")
    tampered["publish_id"] = "different-publish-id"
    with pytest.raises(ValidationError, match="receipt hash"):
        TikTokDraftUploadStatusReceipt.model_validate(tampered)


@pytest.mark.parametrize("state", ["uploaded", "pending-user-action", "complete"])
def test_success_statuses_require_publish_id(state: str) -> None:
    attempt = _attempt()
    initialized = TikTokDraftUploadStatusReceipt.create(
        attempt,
        state="initialized",
        recorded_at=NOW,
    )

    with pytest.raises(ValidationError, match="requires a publish ID"):
        TikTokDraftUploadStatusReceipt.create(
            attempt,
            previous=initialized,
            state=state,  # type: ignore[arg-type]
            recorded_at=NOW,
        )


def test_failure_ambiguity_and_cancellation_require_explanations() -> None:
    attempt = _attempt()
    initialized = TikTokDraftUploadStatusReceipt.create(
        attempt,
        state="initialized",
        recorded_at=NOW,
    )

    for state, expected in (
        ("failed", "requires an error"),
        ("ambiguous", "explain the uncertainty"),
        ("cancelled", "requires a reason"),
    ):
        with pytest.raises(ValidationError, match=expected):
            TikTokDraftUploadStatusReceipt.create(
                attempt,
                previous=initialized,
                state=state,  # type: ignore[arg-type]
                recorded_at=NOW,
            )

    ambiguous = TikTokDraftUploadStatusReceipt.create(
        attempt,
        previous=initialized,
        state="ambiguous",
        publish_id="v_pub_url~maybe-created",
        error_message="The request timed out after the provider accepted the body.",
        recorded_at=NOW,
    )
    assert ambiguous.state == "ambiguous"


def test_preflight_and_diagnostics_never_contain_credentials() -> None:
    intent = _intent()
    checks = (
        TikTokUploadPreflightCheck(
            code="package-hash",
            state="pass",
            detail="The immutable package checksum matches.",
        ),
        TikTokUploadPreflightCheck(
            code="account-binding",
            state="warning",
            detail="Account ownership must still be confirmed by OAuth.",
        ),
    )
    preflight = TikTokDraftUploadPreflight.create(
        intent,
        credentials_available=True,
        checks=checks,
        checked_at=NOW,
    )
    diagnostic = TikTokUploadDiagnostic(
        status="ready",
        credentials_available=True,
        network_checked=False,
        checked_at=NOW,
        reason="A credential reference is available in the operating-system store.",
        next_steps=("Run an explicit draft transfer after consent.",),
    )

    assert preflight.state == "ready"
    assert not preflight.network_attempted
    assert "token" not in " ".join(preflight.model_dump().keys())
    assert diagnostic.status == "ready"

    blocked = TikTokDraftUploadPreflight.create(
        intent,
        credentials_available=False,
        checks=checks,
        checked_at=NOW,
    )
    assert blocked.state == "blocked"
    with pytest.raises(ValidationError, match="ready TikTok diagnostics"):
        TikTokUploadDiagnostic(
            status="ready",
            credentials_available=False,
            network_checked=False,
            checked_at=NOW,
            reason="No credential reference exists.",
        )
