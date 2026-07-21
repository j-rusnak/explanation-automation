from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from techshort.audio import (
    NarrationVoice,
    WindowsSapiNarrationProvider,
    active_synthesis_receipt,
    active_transcript,
    discover_windows_voices,
    local_narration_readiness,
)
from techshort.audio.local_tts import _silence_trim_bounds, _write_synthesis_receipt
from techshort.audio.providers import NarrationSynthesisReceipt, derive_synthesis_id
from techshort.domain.hashing import sha256_file
from techshort.domain.models import AssetManifest, ScriptManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.generation import fixture_claims, fixture_script, generate_angles, select_angle
from techshort.ingestion import ingest_source
from techshort.rendering.service import render_video
from techshort.rendering.tools import media_tool
from techshort.review import approve_claims, approve_script


def _approved_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "local-tts")
    store.initialize("Local TTS")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "local-tts-test")
    generate_angles(store, "fixture").require_artifact()
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "local-tts-test")
    return store


@pytest.fixture
def short_wav(tmp_path: Path) -> Path:
    ffmpeg = media_tool("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for local narration registration tests")
    destination = tmp_path / "short.wav"
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.25",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return destination


def test_voice_discovery_uses_fixed_script_and_argument_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    payload = [
        {"name": "Voice B", "culture": "en-GB", "gender": "Female", "age": "Adult"},
        {"name": "Voice A", "culture": "en-US", "gender": "Male", "age": "Adult"},
    ]

    def fake_run(arguments: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        seen["arguments"] = arguments
        seen["options"] = options
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("techshort.audio.local_tts.platform.system", lambda: "Windows")
    monkeypatch.setattr("techshort.audio.local_tts.shutil.which", lambda _name: "powershell.exe")
    monkeypatch.setattr("techshort.audio.local_tts.subprocess.run", fake_run)

    voices = discover_windows_voices()

    assert [voice.name for voice in voices] == ["Voice B", "Voice A"]
    arguments = seen["arguments"]
    assert isinstance(arguments, list)
    assert arguments[0] == "powershell.exe"
    assert arguments[-2:] == ["-Action", "list"]
    assert "shell" not in seen["options"]
    assert seen["options"]["timeout"] == 20


def test_local_voice_readiness_is_actionable_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("techshort.audio.local_tts.platform.system", lambda: "Linux")

    ready, detail = local_narration_readiness()

    assert not ready
    assert "only on Windows" in detail
    assert "import a recording" in detail


def test_silence_trim_preserves_internal_segment_pauses() -> None:
    log = """
    [silencedetect] silence_start: 0
    [silencedetect] silence_end: 0.4 | silence_duration: 0.4
    [silencedetect] silence_start: 2.0
    [silencedetect] silence_end: 2.14 | silence_duration: 0.14
    [silencedetect] silence_start: 4.7
    [silencedetect] silence_end: 5 | silence_duration: 0.3
    """

    start, end = _silence_trim_bounds(log, 5.0)

    assert start == pytest.approx(0.37)
    assert end == pytest.approx(4.73)


def test_synthesis_receipts_archive_previous_valid_version(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "receipt-archive")
    store.initialize("Receipt archive")
    shared = {
        "provider": "windows-sapi",
        "voice_name": "Fixture Voice",
        "voice_culture": "en-US",
        "voice_gender": "Neutral",
        "voice_age": "Adult",
        "rate": 1,
        "volume": 100,
        "script_version_id": "script-fixture",
        "script_hash": "a" * 64,
        "script_text_hash": "b" * 64,
        "segment_approval_hashes": {"segment-1": "c" * 64},
        "audio_asset_id": "asset-narration-fixture",
        "output_path": "audio/fixture.wav",
        "output_duration_seconds": 45.0,
        "transcript_hash": "d" * 64,
        "rights_status": "unknown",
    }
    first_payload = {"output_hash": "1" * 64, **shared}
    second_payload = {"output_hash": "2" * 64, **shared}
    first = NarrationSynthesisReceipt(
        synthesis_id=derive_synthesis_id(first_payload), **first_payload
    )
    second = NarrationSynthesisReceipt(
        synthesis_id=derive_synthesis_id(second_payload), **second_payload
    )

    _write_synthesis_receipt(store, first)
    current = _write_synthesis_receipt(store, second)

    assert load_model(current, NarrationSynthesisReceipt) == second
    archived = store.path(f"audio/synthesis-versions/{first.synthesis_id}.json")
    assert load_model(archived, NarrationSynthesisReceipt) == first


def test_synthesis_requires_a_current_human_approved_script(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "unapproved-tts")
    store.initialize("Unapproved TTS")

    with pytest.raises(ValueError, match="generate and approve"):
        WindowsSapiNarrationProvider().synthesize(store)


def test_renderer_preflight_blocks_tampered_declared_synthesis_receipt(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "tampered-tts-render")
    store.initialize("Tampered TTS render")
    project = store.project()
    project.active_versions["narration_synthesis"] = "synthesis-1111111111111111"
    project.dependency_hashes["narration_synthesis"] = "a" * 64
    store.save_project(project)

    with pytest.raises(ValueError, match="receipt is missing or changed"):
        render_video(store, preview=True)


def test_synthesis_registers_hash_bound_transcript_and_unresolved_voice_rights(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    short_wav: Path,
) -> None:
    store = _approved_store(tmp_path)
    voice = NarrationVoice(
        provider="windows-sapi",
        name="Fixture Voice",
        culture="en-US",
        gender="Neutral",
        age="Adult",
    )
    provider = WindowsSapiNarrationProvider()
    monkeypatch.setattr(provider, "list_voices", lambda: [voice])

    def fake_sapi(arguments: list[str], *, timeout: int = 120) -> str:
        del timeout
        output = Path(arguments[arguments.index("-OutputWav") + 1])
        shutil.copyfile(short_wav, output)
        return "{}"

    def fake_normalize(_source: Path, destination: Path) -> None:
        shutil.copyfile(short_wav, destination)

    monkeypatch.setattr("techshort.audio.local_tts._run_sapi", fake_sapi)
    monkeypatch.setattr("techshort.audio.local_tts._normalize_audio", fake_normalize)

    result = provider.synthesize(store, voice_name="Fixture Voice")

    script = load_model(store.path("script/script.json"), ScriptManifest)
    transcript = active_transcript(store)
    assert transcript is not None
    assert transcript[0].split() == " ".join(segment.text for segment in script.segments).split()
    assert transcript[1] == result.transcript_path
    assert result.audio_path.is_file()
    receipt = NarrationSynthesisReceipt.model_validate_json(
        result.receipt_path.read_text(encoding="utf-8")
    )
    assert receipt.script_version_id == script.version_id
    assert receipt.script_hash == sha256_file(store.path("script/script.json"))
    assert receipt.output_hash == sha256_file(result.audio_path)
    assert receipt.transcript_hash == sha256_file(result.transcript_path)
    assert receipt.voice_name == "Fixture Voice"
    assert receipt.segment_pause_milliseconds == 140
    assert receipt.rights_status == "unknown"
    assert store.project().active_versions["narration_synthesis"] == receipt.synthesis_id
    assert active_synthesis_receipt(store) == (receipt, result.receipt_path)
    assert result.duration_seconds == pytest.approx(0.25, abs=0.02)
    asset = load_model(store.path("assets/asset-manifest.json"), AssetManifest).assets[0]
    assert asset.origin == "local synthetic narration (windows-sapi)"
    assert asset.creator == "Windows System.Speech voice: Fixture Voice"
    assert asset.rights_status == "unknown"
    assert not asset.embedding_allowed
    assert asset.review_status == "pending"
    assert store.project().approvals.rights == "stale"


def test_synthesis_rejects_uninstalled_voice_before_writing_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _approved_store(tmp_path)
    provider = WindowsSapiNarrationProvider()
    monkeypatch.setattr(
        provider,
        "list_voices",
        lambda: [NarrationVoice("windows-sapi", "Installed", "en-US", "Male", "Adult")],
    )

    with pytest.raises(ValueError, match="not installed"):
        provider.synthesize(store, voice_name="Missing")

    assert not list(store.path("audio").iterdir())


@pytest.mark.parametrize("rate,volume", [(11, 100), (-11, 100), (True, 100), (1, 0), (1, 101)])
def test_synthesis_rejects_unbounded_voice_controls(tmp_path: Path, rate: Any, volume: Any) -> None:
    store = _approved_store(tmp_path)

    with pytest.raises(ValueError, match="rate|volume"):
        WindowsSapiNarrationProvider().synthesize(store, rate=rate, volume=volume)


def test_audio_import_rejects_executable_origin_text(tmp_path: Path, short_wav: Path) -> None:
    from techshort.audio import import_audio

    store = ProjectStore(tmp_path / "projects", "origin-validation")
    store.initialize("Origin validation")
    with pytest.raises(ValueError, match="origin"):
        import_audio(store, short_wav, origin="local\x00command")
