from __future__ import annotations

import json
import shutil
import subprocess
import wave
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
from techshort.audio.local_tts import (
    SEGMENT_PAUSE_FRAMES,
    _concatenate_pcm,
    _parse_sapi_synthesis_output,
    _silence_trim_bounds,
    _verify_engine_event_text,
    _write_synthesis_receipt,
)
from techshort.audio.providers import (
    NarrationConcatenationReceipt,
    NarrationEngineEvent,
    NarrationSegmentReceipt,
    NarrationSynthesisReceipt,
    derive_synthesis_id,
)
from techshort.domain.hashing import sha256_bytes, sha256_file
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


def _write_test_pcm(path: Path, sample: int, frame_count: int) -> None:
    frame = sample.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(frame * frame_count)


def test_pcm_concatenation_is_exact_and_repeatable(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "output.wav"
    repeated = tmp_path / "repeated.wav"
    _write_test_pcm(first, 101, 11)
    _write_test_pcm(second, -202, 7)

    info = _concatenate_pcm([first, second], output)
    repeated_info = _concatenate_pcm([first, second], repeated)

    assert info == repeated_info
    assert info.frame_count == 11 + SEGMENT_PAUSE_FRAMES + 7
    assert sha256_file(output) == sha256_file(repeated)
    with wave.open(str(output), "rb") as audio:
        assert audio.readframes(11) == (101).to_bytes(2, "little", signed=True) * 11
        assert audio.readframes(SEGMENT_PAUSE_FRAMES) == b"\x00\x00" * SEGMENT_PAUSE_FRAMES
        assert audio.readframes(7) == (-202).to_bytes(2, "little", signed=True) * 7
        assert not audio.readframes(1)


def test_sapi_progress_parser_uses_raw_utf16_ranges_and_rejects_truncation() -> None:
    text = "Lens 📷 scan"
    camera_position = len("Lens ".encode("utf-16-le")) // 2
    payload = {
        "voice": "Fixture Voice",
        "rate": 1,
        "volume": 100,
        "output": "segment.wav",
        "progress": [
            {
                "spokenText": "📷",
                "audioPositionSeconds": 0.125,
                "characterPosition": camera_position,
                "characterCount": 2,
            }
        ],
        "progressTruncated": False,
    }

    events = _parse_sapi_synthesis_output(
        json.dumps(payload),
        expected_voice="Fixture Voice",
        expected_rate=1,
        expected_volume=100,
        expected_output_name="segment.wav",
        approved_text=text,
    )

    assert events[0].spoken_text == "📷"
    payload["progressTruncated"] = True
    with pytest.raises(RuntimeError, match="exceeded its safety bound"):
        _parse_sapi_synthesis_output(
            json.dumps(payload),
            expected_voice="Fixture Voice",
            expected_rate=1,
            expected_volume=100,
            expected_output_name="segment.wav",
            approved_text=text,
        )


def test_segment_receipt_rejects_traversal_and_event_text_mismatch() -> None:
    event = NarrationEngineEvent(
        spoken_text="scan",
        normalized_start_seconds=0.0,
        raw_character_position=0,
        raw_character_count=4,
    )
    with pytest.raises(ValueError, match="traversal-free"):
        NarrationSegmentReceipt(
            segment_id="segment-1",
            order=0,
            text_hash="a" * 64,
            approval_hash="b" * 64,
            output_path="../../outside.wav",
            output_hash="c" * 64,
            frame_count=48_000,
            duration_seconds=1.0,
            engine_events=[event],
        )
    with pytest.raises(ValueError, match="does not match"):
        _verify_engine_event_text("roll", [event])


def test_v11_receipt_binds_ordered_segments_to_approval_hashes() -> None:
    event = NarrationEngineEvent(
        spoken_text="scan",
        normalized_start_seconds=0.0,
        raw_character_position=0,
        raw_character_count=4,
    )
    segment = NarrationSegmentReceipt(
        segment_id="segment-1",
        order=0,
        text_hash=sha256_bytes(b"scan"),
        approval_hash="b" * 64,
        output_path=f"audio/narration-segments/{'c' * 64}.wav",
        output_hash="c" * 64,
        frame_count=48_000,
        duration_seconds=1.0,
        engine_events=[event],
    )
    concatenation = NarrationConcatenationReceipt(
        output_frame_count=48_000,
        output_duration_seconds=1.0,
    )
    payload: dict[str, object] = {
        "schema_version": "1.1.0",
        "provider": "windows-sapi",
        "voice_name": "Fixture Voice",
        "voice_culture": "en-US",
        "voice_gender": "Neutral",
        "voice_age": "Adult",
        "rate": 1,
        "volume": 100,
        "segment_pause_milliseconds": 140,
        "script_version_id": "script-fixture",
        "script_hash": "a" * 64,
        "script_text_hash": "d" * 64,
        "segment_approval_hashes": {"segment-1": "e" * 64},
        "audio_asset_id": "asset-narration-fixture",
        "output_path": "audio/narration.wav",
        "output_hash": "f" * 64,
        "output_duration_seconds": 1.0,
        "transcript_hash": "1" * 64,
        "segments": [segment.model_dump(mode="json")],
        "concatenation": concatenation.model_dump(mode="json"),
        "rights_status": "unknown",
    }
    with pytest.raises(ValueError, match="approved segment hashes"):
        NarrationSynthesisReceipt(
            synthesis_id=derive_synthesis_id(payload),
            **payload,
        )

    payload["segment_approval_hashes"] = {"segment-1": "b" * 64}
    receipt = NarrationSynthesisReceipt(
        synthesis_id=derive_synthesis_id(payload),
        **payload,
    )
    assert receipt.schema_version == "1.1.0"
    assert receipt.segments == [segment]


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
    assert first.schema_version == "1.0.0"
    assert first.segments == []
    assert first.concatenation is None
    assert NarrationSynthesisReceipt.model_validate_json(first.model_dump_json()) == first

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

    calls: list[str] = []

    def fake_sapi(arguments: list[str], *, timeout: int = 120) -> str:
        del timeout
        input_path = Path(arguments[arguments.index("-InputText") + 1])
        output = Path(arguments[arguments.index("-OutputWav") + 1])
        text = input_path.read_text(encoding="utf-8").strip()
        calls.append(text)
        shutil.copyfile(short_wav, output)
        return json.dumps(
            {
                "voice": "Fixture Voice",
                "rate": 1,
                "volume": 100,
                "output": output.name,
                "progress": [
                    {
                        "spokenText": text,
                        "audioPositionSeconds": 0.0,
                        "characterPosition": 0,
                        "characterCount": len(text.encode("utf-16-le")) // 2,
                    }
                ],
                "progressTruncated": False,
            }
        )

    def fake_normalize(_source: Path, destination: Path) -> float:
        shutil.copyfile(short_wav, destination)
        return 0.0

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
    assert receipt.schema_version == "1.1.0"
    assert receipt.segment_pause_milliseconds == 140
    assert len(receipt.segments) == len(script.segments)
    assert calls == [" ".join(segment.text.split()) for segment in script.segments]
    assert [segment.segment_id for segment in receipt.segments] == [
        segment.segment_id for segment in script.segments
    ]
    assert all(segment.engine_events for segment in receipt.segments)
    assert receipt.concatenation is not None
    expected_frames = (
        sum(segment.frame_count for segment in receipt.segments)
        + (len(receipt.segments) - 1) * SEGMENT_PAUSE_FRAMES
    )
    assert receipt.concatenation.output_frame_count == expected_frames
    assert receipt.rights_status == "unknown"
    assert store.project().active_versions["narration_synthesis"] == receipt.synthesis_id
    assert active_synthesis_receipt(store) == (receipt, result.receipt_path)
    assert result.duration_seconds == pytest.approx(expected_frames / 48_000, abs=1e-9)
    asset = load_model(store.path("assets/asset-manifest.json"), AssetManifest).assets[0]
    assert asset.origin == "local synthetic narration (windows-sapi)"
    assert asset.creator == "Windows System.Speech voice: Fixture Voice"
    assert asset.rights_status == "unknown"
    assert not asset.embedding_allowed
    assert asset.review_status == "pending"
    assert store.project().approvals.rights == "stale"

    segment_path = store.path(receipt.segments[0].output_path)
    segment_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="segment audio is missing or changed"):
        active_synthesis_receipt(store)


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
