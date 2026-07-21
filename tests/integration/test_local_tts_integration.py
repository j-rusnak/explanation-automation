from __future__ import annotations

import json
import os
import platform
import tempfile
from pathlib import Path

import pytest

from techshort.audio.local_tts import (
    LocalNarrationUnavailable,
    WindowsSapiNarrationProvider,
    _run_sapi,
    active_synthesis_receipt,
    discover_windows_voices,
)
from techshort.audio.providers import NarrationSynthesisReceipt
from techshort.audio.service import probe_duration
from techshort.domain.storage import ProjectStore
from techshort.generation import fixture_claims, fixture_script, generate_angles, select_angle
from techshort.ingestion import ingest_source
from techshort.review import approve_claims, approve_script


def test_repository_sapi_helper_produces_real_local_wav() -> None:
    if platform.system() != "Windows":
        pytest.skip("Windows System.Speech integration is Windows-only")
    try:
        voice = discover_windows_voices()[0]
    except LocalNarrationUnavailable as exc:
        pytest.skip(str(exc))

    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        text = directory / "narration.txt"
        output = directory / "narration.wav"
        text.write_text(
            "This is an offline narration test.\nThe second segment follows a safe pause.\n",
            encoding="utf-8",
        )
        metadata = json.loads(
            _run_sapi(
            [
                "-Action",
                "synthesize",
                "-InputText",
                str(text),
                "-OutputWav",
                str(output),
                "-Voice",
                voice.name,
                "-Rate",
                "1",
                "-Volume",
                "100",
            ],
            timeout=30,
            )
        )

        assert output.is_file()
        assert output.stat().st_size > 44
        assert probe_duration(output) == pytest.approx(3.0, abs=2.5)
        assert metadata["voice"] == voice.name
        assert metadata["progressTruncated"] is False
        assert isinstance(metadata["progress"], list)
        assert metadata["progress"]
        assert all(
            set(event)
            == {
                "spokenText",
                "audioPositionSeconds",
                "characterPosition",
                "characterCount",
            }
            for event in metadata["progress"]
        )


@pytest.mark.skipif(
    os.environ.get("TECHSHORT_RUN_LOCAL_TTS") != "1",
    reason="set TECHSHORT_RUN_LOCAL_TTS=1 for the real full-script synthesis smoke test",
)
def test_full_approved_script_synthesis_registers_media_and_receipt(tmp_path: Path) -> None:
    if platform.system() != "Windows":
        pytest.skip("Windows System.Speech integration is Windows-only")
    store = ProjectStore(tmp_path / "projects", "real-local-tts")
    store.initialize("Real local TTS")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "local-tts-smoke")
    generate_angles(store, "fixture").require_artifact()
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "local-tts-smoke")

    result = WindowsSapiNarrationProvider().synthesize(store, rate=2)

    assert result.audio_path.is_file()
    assert result.transcript_path.is_file()
    assert result.duration_seconds > 10
    receipt = NarrationSynthesisReceipt.model_validate_json(
        result.receipt_path.read_text(encoding="utf-8")
    )
    assert receipt.output_duration_seconds == pytest.approx(result.duration_seconds, abs=0.01)
    assert receipt.rights_status == "unknown"
    assert active_synthesis_receipt(store) == (receipt, result.receipt_path)
