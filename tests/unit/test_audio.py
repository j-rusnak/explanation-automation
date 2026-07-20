from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from techshort.audio import (
    active_audio,
    active_transcript,
    import_audio,
    import_transcript,
    probe_duration,
    set_narration_mode,
)
from techshort.domain.hashing import sha256_file
from techshort.domain.models import AssetManifest
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.rendering.tools import media_tool


@pytest.fixture
def generated_audio(tmp_path: Path) -> Path:
    ffmpeg = media_tool("ffmpeg")
    ffprobe = media_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are required for audio import tests")
    source = tmp_path / "voice.wav"
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
            "sine=frequency=440:sample_rate=8000:duration=0.25",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return source


def _store(tmp_path: Path, slug: str) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", slug)
    store.initialize(slug)
    return store


def test_audio_import_registers_unknown_rights_and_active_asset(
    tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-test")

    imported = import_audio(store, generated_audio)

    project = store.project()
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    assert project.active_versions["audio_asset"] == assets.assets[0].asset_id
    assert assets.assets[0].rights_status == "unknown"
    assert not assets.assets[0].embedding_allowed
    assert active_audio(store) == imported
    assert project.approvals.rights == "stale"
    assert probe_duration(imported) == pytest.approx(0.25, abs=0.02)


def test_silent_mode_is_explicit_and_audio_import_restores_narrated_mode(
    tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-mode")
    set_narration_mode(store, "silent-reviewed")
    assert store.project().narration_mode == "silent-reviewed"

    import_audio(store, generated_audio, rights_status="user-owned")
    assert store.project().narration_mode == "narrated"

    with pytest.raises(ValueError, match="while narration audio is active"):
        set_narration_mode(store, "silent-reviewed")


def test_audio_import_can_record_explicit_user_owned_status(
    tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-owned")

    import_audio(store, generated_audio, rights_status="user-owned", creator="Local narrator")

    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    assert assets.assets[0].rights_status == "user-owned"
    assert assets.assets[0].creator == "Local narrator"
    assert assets.assets[0].embedding_allowed
    assert assets.assets[0].review_status == "pending"


def test_identical_audio_reimport_preserves_review_and_content_version(
    tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-idempotent")
    import_audio(store, generated_audio, rights_status="user-owned")
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    version = assets.version_id
    assets.assets[0].review_status = "approved"
    atomic_write_model(store.path("assets/asset-manifest.json"), assets)

    import_audio(store, generated_audio)

    reloaded = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    assert reloaded.version_id == version
    assert reloaded.assets[0].review_status == "approved"


def test_active_audio_rejects_changed_bytes(tmp_path: Path, generated_audio: Path) -> None:
    store = _store(tmp_path, "audio-tamper")
    imported = import_audio(store, generated_audio)
    imported.write_bytes(b"changed")

    with pytest.raises(ValueError, match="bytes changed"):
        active_audio(store)


def test_audio_restricted_status_is_recorded_but_never_embeddable(
    tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-rights")

    import_audio(store, generated_audio, rights_status="citation-only")
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    assert assets.assets[0].rights_status == "citation-only"
    assert not assets.assets[0].embedding_allowed


def test_audio_rights_status_rejects_unknown_vocabulary(
    tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-invalid-rights")

    with pytest.raises(ValueError, match="rights status"):
        import_audio(store, generated_audio, rights_status="public-domain")


def test_audio_import_rejects_fake_file_with_allowed_extension(tmp_path: Path) -> None:
    if not media_tool("ffprobe"):
        pytest.skip("FFprobe is required for audio import tests")
    store = _store(tmp_path, "audio-fake")
    source = tmp_path / "fake.wav"
    source.write_text("not audio", encoding="utf-8")

    with pytest.raises(ValueError, match="FFprobe rejected"):
        import_audio(store, source)

    assert not list(store.path("audio").iterdir())


def test_audio_import_requires_ffprobe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-no-ffprobe")
    monkeypatch.setattr("techshort.rendering.tools.media_tool", lambda _name: None)

    with pytest.raises(ValueError, match="FFprobe is required"):
        import_audio(store, generated_audio)


def test_permissive_audio_requires_concrete_rights_metadata(
    tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-license-missing")

    with pytest.raises(ValueError, match="explicit creator and license_name"):
        import_audio(store, generated_audio, rights_status="permissively-licensed")


def test_permissive_audio_persists_concrete_rights_metadata(
    tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-license")

    import_audio(
        store,
        generated_audio,
        rights_status="permissively-licensed",
        creator="Example Audio Lab",
        license_name="CC BY 4.0",
        source_url="https://example.test/audio",
        required_attribution="Example Audio Lab, CC BY 4.0",
    )

    asset = load_model(store.path("assets/asset-manifest.json"), AssetManifest).assets[0]
    assert asset.creator == "Example Audio Lab"
    assert asset.license == "CC BY 4.0"
    assert asset.source_url == "https://example.test/audio"
    assert asset.required_attribution == "Example Audio Lab, CC BY 4.0"
    assert asset.embedding_allowed


def test_transcript_sidecar_is_bound_to_active_audio_hash(
    tmp_path: Path, generated_audio: Path
) -> None:
    store = _store(tmp_path, "audio-transcript")
    imported_audio = import_audio(store, generated_audio, rights_status="user-owned")
    source = tmp_path / "narration.txt"
    source.write_text("This is the reviewed narration transcript.", encoding="utf-8")

    sidecar = import_transcript(store, source)

    loaded = active_transcript(store)
    assert loaded is not None
    text, path = loaded
    assert text == "This is the reviewed narration transcript."
    assert path == sidecar
    assert sidecar.name == f"{sha256_file(imported_audio)[:12]}-transcript.txt"
    assert store.project().approvals.final == "stale"


def test_transcript_sidecar_rejects_changed_bytes(tmp_path: Path, generated_audio: Path) -> None:
    store = _store(tmp_path, "audio-transcript-tamper")
    import_audio(store, generated_audio, rights_status="user-owned")
    source = tmp_path / "narration.txt"
    source.write_text("Original transcript.", encoding="utf-8")
    sidecar = import_transcript(store, source)
    sidecar.write_text("Changed after registration.", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after import"):
        active_transcript(store)
