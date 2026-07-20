from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from techshort.cli.app import app

runner = CliRunner()


def test_cli_help_is_discoverable() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "doctor",
        "init",
        "ingest",
        "claims",
        "script",
        "storyboard",
        "cover",
        "audio",
        "captions",
        "preview",
        "render",
        "qa",
        "export",
        "status",
    ):
        assert command in result.stdout


def test_script_help_exposes_angle_generation_and_selection() -> None:
    result = runner.invoke(app, ["script", "--help"])
    assert result.exit_code == 0
    assert "angles" in result.stdout
    assert "select-angle" in result.stdout
    assert "generate" in result.stdout


def test_audio_help_exposes_transcript_and_rights_metadata() -> None:
    result = runner.invoke(app, ["audio", "--help"])
    assert result.exit_code == 0
    assert "import-transcript" in result.stdout

    import_help = runner.invoke(app, ["audio", "import", "--help"])
    assert import_help.exit_code == 0
    for option in ("--rights-status", "--creator", "--license", "--source-url"):
        assert option in import_help.stdout


def test_machine_status_lists_actionable_gate_blockers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = tmp_path / "projects"
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    initialized = runner.invoke(app, ["init", "status-test", "--title", "Status test"])
    assert initialized.exit_code == 0

    result = runner.invoke(app, ["status", "status-test", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert not payload["export_ready"]
    assert "claims gate: pending" in payload["export_blockers"]
    assert "preview QA report is missing" in payload["export_blockers"]
