from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from techshort.domain.storage import ProjectStore
from techshort.generation import fixture_claims, fixture_script, fixture_storyboard
from techshort.ingestion import ingest_source
from techshort.rendering import renderer_payload
from techshort.rendering.service import (
    _generation_prompt_versions,
    _preview_scale,
    probe_render_metadata,
)
from techshort.review import approve_claims, approve_script


def fixture_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "render-test")
    store.initialize("Render test")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "renderer-test")
    fixture_script(store)
    approve_script(store, "renderer-test")
    fixture_storyboard(store)
    return store


def test_preview_payload_keeps_full_layout_and_scales_all_timing(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)

    payload = renderer_payload(
        store,
        watermarked=True,
        preview=True,
        audio_public_path="techshort-stage/narration.wav",
        target_duration=51.25,
    )

    assert payload["width"] == 1080
    assert payload["height"] == 1920
    assert payload["audioPath"] == "techshort-stage/narration.wav"
    scenes = payload["scenes"]
    captions = payload["captions"]
    assert isinstance(scenes, list) and isinstance(scenes[-1], dict)
    assert isinstance(captions, list) and isinstance(captions[-1], dict)
    assert scenes[-1]["start_time"] + scenes[-1]["duration"] == pytest.approx(51.25)
    assert captions[-1]["end"] == 51.25
    assert all(len(str(cue["text"])) <= 42 for cue in captions)


def test_preview_scale_requires_vertical_project_ratio() -> None:
    assert _preview_scale(1080, 1920) == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="9:16"):
        _preview_scale(1080, 1080)


def test_render_manifest_prompt_versions_come_from_generation_receipts(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    versions = _generation_prompt_versions(store)
    assert set(versions) == {"claims", "script", "storyboard"}
    assert all(value.startswith("fixture-v1@") for value in versions.values())
    assert all(len(value.split("@", 1)[1]) == 64 for value in versions.values())


def test_render_probe_uses_actual_ffprobe_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    response = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 360,
                "height": 640,
                "avg_frame_rate": "30000/1000",
            }
        ],
        "format": {"duration": "51.267"},
    }
    monkeypatch.setattr("techshort.rendering.service.media_tool", lambda _: "ffprobe")
    monkeypatch.setattr(
        "techshort.rendering.service.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout=json.dumps(response), stderr=""
        ),
    )

    metadata = probe_render_metadata(tmp_path / "render.mp4")

    assert metadata is not None
    assert (metadata.width, metadata.height) == (360, 640)
    assert metadata.fps == 30
    assert metadata.duration == 51.267
    assert metadata.codec == "h264"
