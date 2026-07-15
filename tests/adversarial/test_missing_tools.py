from __future__ import annotations

import json

import pytest
import typer

from techshort.cli.app import doctor


def test_doctor_fails_actionably_when_ffmpeg_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("techshort.cli.app.media_tool", lambda _: None)
    with pytest.raises(typer.Exit) as exc:
        doctor(json_output=True)
    assert exc.value.exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert not payload["ok"]
    assert payload["dependencies"]["ffmpeg"] == {
        "required": True,
        "ok": False,
        "value": "not found",
    }
    assert payload["dependencies"]["ffprobe"]["ok"] is False
