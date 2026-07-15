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
        "audio",
        "captions",
        "preview",
        "render",
        "qa",
        "export",
        "status",
    ):
        assert command in result.stdout


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
