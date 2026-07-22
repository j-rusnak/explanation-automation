from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from techshort.cli.app import app
from techshort.publication import DRAFT_TRANSFER_CONFIRMATION

runner = CliRunner()


class _Record:
    def __init__(self, **payload: Any) -> None:
        self._payload = payload
        for name, value in payload.items():
            setattr(self, name, value)

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return self._payload

    def model_dump_json(self, *, indent: int) -> str:
        return json.dumps(self._payload, indent=indent)


def _credential_environment(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    token = "test-access-token-do-not-print"  # noqa: S105 - inert fixture value
    open_id = "test-open-id-do-not-print"
    monkeypatch.setenv("TECHSHORT_TIKTOK_ACCESS_TOKEN", token)
    monkeypatch.setenv("TECHSHORT_TIKTOK_OPEN_ID", open_id)
    return token, open_id


def _draft_base(package: Path) -> list[str]:
    return [
        "publication",
        "upload-draft",
        "upload-cli",
        str(package),
        "--account-label",
        "Reviewed TikTok account",
        "--reviewer",
        "human-reviewer",
    ]


def _command_prefix(package: Path) -> list[str]:
    return [
        *_draft_base(package),
        "--confirmation",
        DRAFT_TRANSFER_CONFIRMATION,
    ]


def test_tiktok_upload_commands_are_discoverable() -> None:
    result = runner.invoke(app, ["publication", "--help"])

    assert result.exit_code == 0, result.stdout
    for command in (
        "upload-diagnostics",
        "upload-preflight",
        "upload-draft",
        "upload-status",
    ):
        assert command in result.stdout


def test_upload_diagnostics_reads_environment_without_exposing_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, open_id = _credential_environment(monkeypatch)

    result = runner.invoke(app, ["publication", "upload-diagnostics", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready"
    assert payload["credentials_available"] is True
    assert payload["network_checked"] is False
    assert token not in result.stdout
    assert open_id not in result.stdout


def test_upload_diagnostics_reports_missing_credentials_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TECHSHORT_TIKTOK_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TECHSHORT_TIKTOK_OPEN_ID", raising=False)

    result = runner.invoke(app, ["publication", "upload-diagnostics", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "authentication-required"
    assert payload["credentials_available"] is False
    assert payload["network_checked"] is False


def test_upload_preflight_binds_credential_account_and_never_constructs_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, open_id = _credential_environment(monkeypatch)
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(tmp_path / "projects"))
    package = tmp_path / "package-manifest.json"
    observed: dict[str, Any] = {}
    intent = _Record(intent_id="tiktok-upload-intent-1111111111111111")
    preflight = _Record(state="ready", network_attempted=False, checks=[])

    def fake_create(_store: object, path: Path, **options: Any) -> _Record:
        observed["path"] = path
        observed.update(options)
        return intent

    def fake_preflight(
        _store: object,
        path: Path,
        actual_intent: object,
        *,
        credentials_available: bool,
    ) -> _Record:
        observed["preflight"] = (path, actual_intent, credentials_available)
        return preflight

    monkeypatch.setattr("techshort.cli.app.create_tiktok_draft_upload_intent", fake_create)
    monkeypatch.setattr("techshort.cli.app.preflight_tiktok_draft_upload", fake_preflight)
    monkeypatch.setattr(
        "techshort.cli.app.TikTokDraftUploadClient",
        lambda *_args, **_kwargs: pytest.fail("preflight constructed a network client"),
    )

    result = runner.invoke(
        app,
        [
            "publication",
            "upload-preflight",
            "upload-cli",
            str(package),
            "--account-label",
            "Reviewed TikTok account",
            "--reviewer",
            "human-reviewer",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["network_attempted"] is False
    assert payload["preflight"]["network_attempted"] is False
    assert len(observed["target_account_subject_sha256"]) == 64
    assert observed["target_account_label"] == "Reviewed TikTok account"
    assert observed["requested_by"] == "human-reviewer"
    assert observed["preflight"] == (package, intent, True)
    assert token not in result.stdout
    assert open_id not in result.stdout


def test_upload_draft_defaults_to_preflight_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _credential_environment(monkeypatch)
    package = tmp_path / "package-manifest.json"
    intent = _Record(intent_id="tiktok-upload-intent-1111111111111111")
    preflight = _Record(state="ready", network_attempted=False, checks=[])
    monkeypatch.setattr(
        "techshort.cli.app._tiktok_upload_preflight",
        lambda *_args, **_kwargs: (intent, preflight, object()),
    )
    monkeypatch.setattr(
        "techshort.cli.app.grant_tiktok_draft_upload_consent",
        lambda *_args, **_kwargs: pytest.fail("dry run granted API upload consent"),
    )
    monkeypatch.setattr(
        "techshort.cli.app.TikTokDraftUploadClient",
        lambda *_args, **_kwargs: pytest.fail("dry run constructed a network client"),
    )
    monkeypatch.setattr(
        "techshort.cli.app.execute_tiktok_draft_upload",
        lambda *_args, **_kwargs: pytest.fail("dry run attempted an upload"),
    )

    result = runner.invoke(app, [*_draft_base(package), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["executed"] is False
    assert payload["network_attempted"] is False


def test_upload_draft_requires_exact_confirmation_when_executing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = _Record(intent_id="tiktok-upload-intent-1111111111111111")
    preflight = _Record(state="ready", network_attempted=False, checks=[])
    monkeypatch.setattr(
        "techshort.cli.app._tiktok_upload_preflight",
        lambda *_args, **_kwargs: (intent, preflight, object()),
    )
    monkeypatch.setattr(
        "techshort.cli.app.grant_tiktok_draft_upload_consent",
        lambda *_args, **_kwargs: pytest.fail("invalid consent was granted"),
    )
    args = _command_prefix(tmp_path / "package-manifest.json")
    args[args.index(DRAFT_TRANSFER_CONFIRMATION)] = "I approve something else."

    result = runner.invoke(app, [*args, "--execute"])

    assert result.exit_code == 1
    assert "exact DRAFT_TRANSFER_CONFIRMATION" in result.stdout


def test_upload_draft_executes_exactly_one_consent_bound_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, open_id = _credential_environment(monkeypatch)
    package = tmp_path / "package-manifest.json"
    credentials = object()
    intent = _Record(intent_id="tiktok-upload-intent-1111111111111111")
    preflight = _Record(state="ready", network_attempted=False, checks=[])
    consent = _Record(receipt_id="tiktok-upload-consent-1111111111111111")
    receipt = _Record(state="uploaded", receipt_id="tiktok-upload-status-1111111111111111")
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    clients: list[object] = []

    monkeypatch.setattr(
        "techshort.cli.app._tiktok_upload_preflight",
        lambda *_args, **_kwargs: (intent, preflight, credentials),
    )

    def fake_grant(*args: Any, **kwargs: Any) -> _Record:
        calls.append(("grant", args, kwargs))
        return consent

    class FakeClient:
        def __init__(self, actual_credentials: object) -> None:
            assert actual_credentials is credentials
            clients.append(self)
            calls.append(("client", (actual_credentials,), {}))

    def fake_execute(*args: Any, **kwargs: Any) -> _Record:
        calls.append(("execute", args, kwargs))
        return receipt

    monkeypatch.setattr("techshort.cli.app.grant_tiktok_draft_upload_consent", fake_grant)
    monkeypatch.setattr("techshort.cli.app.TikTokDraftUploadClient", FakeClient)
    monkeypatch.setattr("techshort.cli.app.execute_tiktok_draft_upload", fake_execute)

    result = runner.invoke(app, [*_command_prefix(package), "--execute", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["executed"] is True
    assert payload["receipt"]["state"] == "uploaded"
    assert [call[0] for call in calls] == ["grant", "client", "execute"]
    assert calls[0][1] == (intent,)
    assert calls[0][2] == {
        "reviewer_identifier": "human-reviewer",
        "confirmation": DRAFT_TRANSFER_CONFIRMATION,
    }
    assert calls[2][1][1:5] == (package, intent, consent, preflight)
    assert calls[2][1][5] is clients[0]
    assert token not in result.stdout
    assert open_id not in result.stdout


def test_upload_status_requires_network_flag_and_only_polls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_args = [
        "publication",
        "upload-status",
        "upload-cli",
        "exp-1111111111111111",
        "tiktok-upload-intent-1111111111111111",
    ]
    monkeypatch.setattr(
        "techshort.cli.app.TikTokDraftUploadClient",
        lambda *_args, **_kwargs: pytest.fail("status without --network created a client"),
    )
    blocked = runner.invoke(app, package_args)
    assert blocked.exit_code == 1
    assert "requires explicit --network" in blocked.stdout

    token, open_id = _credential_environment(monkeypatch)
    observed: list[tuple[Any, ...]] = []

    class FakeClient:
        def __init__(self, _credentials: object) -> None:
            pass

    receipt = _Record(
        state="pending-user-action",
        receipt_id="tiktok-upload-status-2222222222222222",
    )

    def fake_poll(*args: Any, **_kwargs: Any) -> _Record:
        observed.append(args)
        return receipt

    monkeypatch.setattr("techshort.cli.app.TikTokDraftUploadClient", FakeClient)
    monkeypatch.setattr("techshort.cli.app.poll_tiktok_draft_upload", fake_poll)
    monkeypatch.setattr(
        "techshort.cli.app.execute_tiktok_draft_upload",
        lambda *_args, **_kwargs: pytest.fail("status polling attempted a re-upload"),
    )

    result = runner.invoke(app, [*package_args, "--network", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["state"] == "pending-user-action"
    assert len(observed) == 1
    assert observed[0][1:3] == (
        "exp-1111111111111111",
        "tiktok-upload-intent-1111111111111111",
    )
    assert token not in result.stdout
    assert open_id not in result.stdout
