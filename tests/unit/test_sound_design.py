from __future__ import annotations

import wave
from pathlib import Path

import pytest

from techshort.audio.sound_design import active_sound_design, generate_sound_design
from techshort.domain.models import AssetManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.generation import (
    fixture_claims,
    fixture_script,
    generate_angles,
    select_angle,
)
from techshort.ingestion import ingest_source
from techshort.review import approve_claims, approve_script


def _approved_script(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "sound-design")
    store.initialize("Sound design")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "reviewer")
    generate_angles(store, "fixture")
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "reviewer")
    return store


def test_procedural_sound_design_is_deterministic_and_rights_tracked(
    tmp_path: Path,
) -> None:
    store = _approved_script(tmp_path)
    receipt = generate_sound_design(store, "subtle")
    output = active_sound_design(store)

    assert output is not None
    assert receipt.output_path == output.relative_to(store.root).as_posix()
    assert 1 <= len(receipt.events) <= 15
    assert {event.cue for event in receipt.events} >= {
        "soft-hit",
        "source-click",
        "resolve-tone",
    }
    with wave.open(str(output), "rb") as audio:
        assert audio.getframerate() == 48_000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getnframes() / audio.getframerate() == pytest.approx(
            receipt.duration_seconds, abs=0.001
        )

    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    asset = next(item for item in assets.assets if item.asset_type == "sound-design")
    assert asset.rights_status == "original"
    assert asset.embedding_allowed
    assert asset.review_status == "pending"

    repeated = generate_sound_design(store, "subtle")
    assert repeated == receipt
    assert store.project().approvals.rights == "stale"


def test_sound_design_rejects_stale_retention_dependencies(tmp_path: Path) -> None:
    store = _approved_script(tmp_path)
    generate_sound_design(store)
    project = store.project()
    project.active_versions["retention_plan"] = "retention-0000000000000000"
    store.save_project(project)

    with pytest.raises(ValueError, match="active plan"):
        active_sound_design(store)


def test_sound_design_detects_changed_audio_bytes(tmp_path: Path) -> None:
    store = _approved_script(tmp_path)
    receipt = generate_sound_design(store)
    output = store.path(receipt.output_path)
    output.write_bytes(output.read_bytes() + b"changed")

    with pytest.raises(ValueError, match="bytes changed"):
        active_sound_design(store)
