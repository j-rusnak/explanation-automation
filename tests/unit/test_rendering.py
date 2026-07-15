from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import RenderManifest
from techshort.domain.storage import ProjectStore, atomic_write_model
from techshort.generation import (
    fixture_claims,
    fixture_script,
    fixture_storyboard,
    generate_angles,
    select_angle,
)
from techshort.ingestion import ingest_source
from techshort.rendering import renderer_payload
from techshort.rendering.service import (
    _activate_render,
    _archive_active_render,
    _build_render_manifest,
    _generation_prompt_versions,
    _preview_scale,
    _render_manifest_path,
    _require_final_render_approval,
    probe_render_metadata,
)
from techshort.review import approve_claims, approve_script


def fixture_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "render-test")
    store.initialize("Render test")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "renderer-test")
    generate_angles(store, "fixture").require_artifact()
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "renderer-test")
    fixture_storyboard(store)
    return store


def active_render(store: ProjectStore, *, preview: bool, content: bytes) -> RenderManifest:
    directory = store.path("renders/previews" if preview else "renders/final")
    video = directory / ("preview.mp4" if preview else "final.mp4")
    video.write_bytes(content)
    relative = video.relative_to(store.root).as_posix()
    manifest = RenderManifest(
        render_id=f"render-{sha256_file(video)[:16]}",
        width=360 if preview else 1080,
        height=640 if preview else 1920,
        fps=30,
        duration=60,
        codec="h264",
        script_hash="a" * 64,
        storyboard_hash="b" * 64,
        scene_versions={"scene-1": "c" * 64},
        asset_hashes={},
        renderer_version="remotion-test",
        prompt_versions={"claims": "fixture-v1@" + "d" * 64},
        source_hashes={"source-1": "e" * 64},
        output_paths=[relative],
        output_hashes={relative: sha256_file(video)},
        watermarked=preview,
    )
    atomic_write_model(_render_manifest_path(store, preview), manifest)
    return manifest


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
    assert set(versions) == {
        "claims",
        "claims-critique",
        "angles",
        "script",
        "storyboard",
    }
    assert versions["claims-critique"].startswith("deterministic-critique-v1@")
    assert all("@" in value for value in versions.values())
    assert all(len(value.split("@", 1)[1]) == 64 for value in versions.values())


def test_unwatermarked_render_requires_all_current_human_gates(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    with pytest.raises(ValueError, match="storyboard gate"):
        _require_final_render_approval(store, store.project())


def test_render_id_is_bound_to_exact_staged_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = fixture_store(tmp_path)
    staged = tmp_path / "staged-preview.mp4"
    relative = "renders/previews/preview.mp4"
    payload = renderer_payload(store, watermarked=True, preview=True)
    monkeypatch.setattr("techshort.rendering.service.probe_render_metadata", lambda _: None)
    staged.write_bytes(b"first encoded output")
    first = _build_render_manifest(
        store,
        staged,
        payload,
        preview=True,
        expected_duration=60,
        narration=None,
        staged_outputs={relative: staged},
    )
    staged.write_bytes(b"different encoded output")
    second = _build_render_manifest(
        store,
        staged,
        payload,
        preview=True,
        expected_duration=60,
        narration=None,
        staged_outputs={relative: staged},
    )

    assert first.render_id != second.render_id
    assert first.output_hashes[relative] != second.output_hashes[relative]


@pytest.mark.parametrize("preview", [True, False])
def test_render_activation_records_exact_version_and_dependencies(
    tmp_path: Path, preview: bool
) -> None:
    store = ProjectStore(tmp_path / "projects", "render-history")
    store.initialize("Render history")
    manifest = active_render(store, preview=preview, content=b"first render")

    _activate_render(store, preview=preview, manifest=manifest)

    kind = "preview" if preview else "final"
    project = store.project()
    assert project.active_versions[f"{kind}_render"] == manifest.render_id
    assert project.dependency_hashes[f"{kind}_render_output"] == stable_hash(manifest.output_hashes)
    assert len(project.dependency_hashes[f"{kind}_render_dependencies"]) == 64


def test_active_render_is_archived_before_replacement(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "render-history")
    store.initialize("Render history")
    manifest = active_render(store, preview=True, content=b"reviewed preview")
    _activate_render(store, preview=True, manifest=manifest)

    _archive_active_render(store, preview=True)

    archive = store.path(f"renders/previews/versions/{manifest.render_id}")
    assert (archive / "preview.mp4").read_bytes() == b"reviewed preview"
    archived_manifest = (archive / "render-manifest.json").read_bytes()
    assert archived_manifest == _render_manifest_path(store, True).read_bytes()


def test_render_archive_rejects_tampered_active_output(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "render-history")
    store.initialize("Render history")
    manifest = active_render(store, preview=False, content=b"approved final")
    _activate_render(store, preview=False, manifest=manifest)
    store.path("renders/final/final.mp4").write_bytes(b"tampered final")

    with pytest.raises(ValueError, match="does not match its manifest"):
        _archive_active_render(store, preview=False)

    assert not store.path(f"renders/final/versions/{manifest.render_id}").exists()


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
