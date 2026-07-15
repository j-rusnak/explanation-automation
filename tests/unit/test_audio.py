from __future__ import annotations

from pathlib import Path

import pytest

from techshort.audio import active_audio, import_audio
from techshort.domain.models import AssetManifest
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model


def test_audio_import_registers_unknown_rights_and_active_asset(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "audio-test")
    store.initialize("Audio test")
    source = tmp_path / "voice.wav"
    source.write_bytes(b"RIFF fixture bytes")

    imported = import_audio(store, source)

    project = store.project()
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    assert project.active_versions["audio_asset"] == assets.assets[0].asset_id
    assert assets.assets[0].rights_status == "unknown"
    assert not assets.assets[0].embedding_allowed
    assert active_audio(store) == imported
    assert project.approvals.rights == "stale"


def test_audio_import_can_record_explicit_user_owned_status(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "audio-owned")
    store.initialize("Audio owned")
    source = tmp_path / "voice.wav"
    source.write_bytes(b"RIFF fixture bytes")

    import_audio(store, source, rights_status="user-owned")

    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    assert assets.assets[0].rights_status == "user-owned"
    assert assets.assets[0].embedding_allowed
    assert assets.assets[0].review_status == "pending"


def test_identical_audio_reimport_preserves_review_and_content_version(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "audio-idempotent")
    store.initialize("Audio idempotent")
    source = tmp_path / "voice.wav"
    source.write_bytes(b"RIFF fixture bytes")
    import_audio(store, source, rights_status="user-owned")
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    version = assets.version_id
    assets.assets[0].review_status = "approved"
    atomic_write_model(store.path("assets/asset-manifest.json"), assets)

    import_audio(store, source)

    reloaded = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    assert reloaded.version_id == version
    assert reloaded.assets[0].review_status == "approved"


def test_active_audio_rejects_changed_bytes(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "audio-tamper")
    store.initialize("Audio tamper")
    source = tmp_path / "voice.wav"
    source.write_bytes(b"RIFF fixture bytes")
    imported = import_audio(store, source)
    imported.write_bytes(b"changed")

    with pytest.raises(ValueError, match="bytes changed"):
        active_audio(store)


def test_audio_restricted_status_is_recorded_but_never_embeddable(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "audio-rights")
    store.initialize("Audio rights")
    source = tmp_path / "voice.wav"
    source.write_bytes(b"RIFF fixture bytes")

    import_audio(store, source, rights_status="citation-only")
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    assert assets.assets[0].rights_status == "citation-only"
    assert not assets.assets[0].embedding_allowed


def test_audio_rights_status_rejects_unknown_vocabulary(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "audio-invalid-rights")
    store.initialize("Audio invalid rights")
    source = tmp_path / "voice.wav"
    source.write_bytes(b"RIFF fixture bytes")

    with pytest.raises(ValueError, match="rights status"):
        import_audio(store, source, rights_status="public-domain")
