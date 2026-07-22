from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from techshort.audio import NarrationVoice, SynthesizedNarration
from techshort.cli.app import app
from techshort.domain.storage import ProjectStore

runner = CliRunner()


class _FixtureKokoroProvider:
    provider_id = "kokoro-local"

    def __init__(self, cache_directory: Path | None = None) -> None:
        self.cache_directory = cache_directory

    def readiness(self) -> tuple[bool, str]:
        return False, "run explicit setup"

    def list_voices(self) -> list[NarrationVoice]:
        return [NarrationVoice("kokoro-local", "af_heart", "en-US", "Female", "Adult")]


def _timing() -> SimpleNamespace:
    return SimpleNamespace(
        timing_id="timing-1111111111111111",
        quality="proportional-fallback",
        alignment=SimpleNamespace(
            coverage=0.0,
            fallback_reason="provider does not emit word events",
        ),
    )


def test_kokoro_voices_are_listed_before_explicit_model_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("techshort.cli.app.KokoroLocalNarrationProvider", _FixtureKokoroProvider)

    result = runner.invoke(app, ["audio", "voices", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["provider"] == "kokoro-local"
    assert payload["ready"] is False
    assert payload["voices"][0]["name"] == "af_heart"
    assert payload["message"] == "run explicit setup"


def test_kokoro_setup_requires_explicit_download_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def unexpected_setup(**_options: Any) -> object:
        nonlocal called
        called = True
        raise AssertionError("setup must not run without --yes")

    monkeypatch.setattr("techshort.cli.app.setup_kokoro_model", unexpected_setup)

    result = runner.invoke(app, ["audio", "setup"])

    assert result.exit_code == 1
    assert "rerun with --yes" in result.stdout
    assert called is False


def test_default_synthesis_uses_offline_kokoro_and_registers_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(root))
    project = ProjectStore(root, "neural-cli")
    project.initialize("Neural CLI")
    voice = NarrationVoice("kokoro-local", "af_heart", "en-US", "Female", "Adult")
    observed: dict[str, object] = {}

    def fake_synthesize(store: ProjectStore, **options: object) -> SynthesizedNarration:
        observed["slug"] = store.slug
        observed.update(options)
        return SynthesizedNarration(
            provider="kokoro-local",
            voice=voice,
            audio_path=store.path("audio/narration.wav"),
            transcript_path=store.path("audio/narration.txt"),
            receipt_path=store.path("audio/narration-synthesis.json"),
            duration_seconds=48.25,
            rate=0,
            volume=100,
            speed=1.1,
        )

    monkeypatch.setattr("techshort.cli.app.synthesize_kokoro_narration", fake_synthesize)
    monkeypatch.setattr(
        "techshort.cli.app.register_active_synthesis_timing", lambda _store: _timing()
    )

    result = runner.invoke(
        app,
        [
            "audio",
            "synthesize",
            "neural-cli",
            "--voice",
            "af_heart",
            "--speed",
            "1.1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["provider"] == "kokoro-local"
    assert payload["speed"] == 1.1
    assert payload["timing_quality"] == "proportional-fallback"
    assert payload["timing_fallback_reason"] == "provider does not emit word events"
    assert observed == {
        "slug": "neural-cli",
        "cache_directory": None,
        "voice_name": "af_heart",
        "speed": 1.1,
        "rights_status": "unknown",
        "license_name": None,
        "required_attribution": None,
    }
