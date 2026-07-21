from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from techshort.alignment import (
    EngineWordObservation,
    NarrationTimingManifest,
    active_narration_timing,
    align_engine_observations,
    build_narration_timing_manifest,
    canonical_script_text,
    canonical_script_words,
    cues_from_script,
    derive_narration_timing_id,
    register_narration_timing,
)
from techshort.domain.hashing import sha256_bytes
from techshort.domain.models import ReviewStatus, ScriptManifest, ScriptSegment
from techshort.domain.storage import ProjectStore
from techshort.generation import fixture_claims, fixture_script, generate_angles, select_angle
from techshort.ingestion import ingest_source
from techshort.review import approve_claims, approve_script


def _script() -> ScriptManifest:
    return ScriptManifest(
        version_id="script-timing-fixture",
        claims_version_id="claims-fixture",
        angles_version_id="angles-fixture",
        angle_selection_id="selection-fixture",
        angle="everyday-mechanism",
        segments=[
            ScriptSegment(
                segment_id="segment-mechanism",
                text="Alpha beta gamma delta makes the mechanism visible.",
                segment_type="factual",
                claim_ids=["claim-mechanism"],
                approximate_duration=5,
                review_status=ReviewStatus.APPROVED,
                approval_hash="a" * 64,
            ),
            ScriptSegment(
                segment_id="segment-limitation",
                text="This model remains a bounded simplification.",
                segment_type="limitation",
                claim_ids=["claim-limitation"],
                approximate_duration=4,
                review_status=ReviewStatus.APPROVED,
                approval_hash="b" * 64,
            ),
        ],
    )


def _observations(
    script: ScriptManifest,
    *,
    omit: set[int] | None = None,
    insertion_at: int | None = None,
) -> list[EngineWordObservation]:
    omit = omit or set()
    observations: list[EngineWordObservation] = []
    for word in canonical_script_words(script):
        if insertion_at == word.global_word_index:
            observations.append(
                EngineWordObservation(
                    sequence_index=len(observations),
                    text="invented",
                    start_seconds=0.15 + word.global_word_index * 0.55,
                    end_seconds=0.32 + word.global_word_index * 0.55,
                    confidence=0.99,
                )
            )
        if word.global_word_index in omit:
            continue
        start = 0.2 + word.global_word_index * 0.55
        observations.append(
            EngineWordObservation(
                sequence_index=len(observations),
                text=word.display_text,
                start_seconds=start,
                end_seconds=start + 0.24,
                confidence=0.95,
            )
        )
    return observations


def _manifest(
    script: ScriptManifest,
    observations: list[EngineWordObservation],
    *,
    duration: float = 12.0,
) -> NarrationTimingManifest:
    projection = align_engine_observations(
        script,
        observations,
        audio_duration_seconds=duration,
        source="local-whisper",
    )
    payload: dict[str, object] = {
        "source": projection.source,
        "quality": projection.quality,
        "audio_asset_id": "asset-narration-fixture",
        "audio_path": "audio/narration.wav",
        "audio_hash": "c" * 64,
        "audio_duration_seconds": duration,
        "script_version_id": script.version_id,
        "script_hash": "d" * 64,
        "script_text_hash": sha256_bytes(canonical_script_text(script).encode("utf-8")),
        "segment_approval_hashes": {
            segment.segment_id: segment.approval_hash for segment in script.segments
        },
        "segments": list(projection.segments),
        "words": list(projection.words),
        "alignment": projection.alignment,
    }
    return NarrationTimingManifest(
        timing_id=derive_narration_timing_id(payload),
        **payload,
    )


def test_exact_engine_projection_uses_only_approved_tokens_and_stable_ids() -> None:
    script = _script()

    projection = align_engine_observations(
        script,
        _observations(script, insertion_at=3),
        audio_duration_seconds=12,
        source="local-whisper",
    )

    expected = canonical_script_words(script)
    assert [word.display_text for word in projection.words] == [
        word.display_text for word in expected
    ]
    assert "invented" not in {word.display_text for word in projection.words}
    assert projection.alignment.insertion_count == 1
    assert projection.alignment.coverage == 1
    assert [word.word_id for word in projection.words] == [word.word_id for word in expected]
    assert all(
        left.end_seconds <= right.start_seconds
        for left, right in zip(projection.words, projection.words[1:], strict=False)
    )


def test_small_internal_gap_is_interpolated_but_low_coverage_falls_back() -> None:
    script = _script()
    canonical = canonical_script_words(script)

    bounded = align_engine_observations(
        script,
        _observations(script, omit={2}),
        audio_duration_seconds=12,
        source="sapi-speak-progress",
    )
    assert bounded.words[2].display_text == canonical[2].display_text
    assert bounded.words[2].quality == "interpolated"
    assert bounded.words[2].start_origin == "interpolated"
    assert bounded.alignment.interpolated_word_count == 1

    sparse = align_engine_observations(
        script,
        _observations(script, omit=set(range(2, len(canonical)))),
        audio_duration_seconds=12,
        source="local-whisper",
    )
    assert sparse.source == "proportional-fallback"
    assert sparse.quality == "proportional-fallback"
    assert all(word.quality == "proportional-fallback" for word in sparse.words)
    assert sparse.alignment.fallback_reason is not None


def test_manifest_rejects_identity_tampering_traversal_and_overlap() -> None:
    script = _script()
    manifest = _manifest(script, _observations(script))

    changed = manifest.model_dump(mode="json")
    changed["audio_hash"] = "e" * 64
    with pytest.raises(ValidationError, match="ID does not match"):
        NarrationTimingManifest.model_validate(changed)

    traversal = manifest.model_dump(mode="json")
    traversal["audio_path"] = "../../outside.wav"
    traversal["timing_id"] = derive_narration_timing_id(traversal)
    with pytest.raises(ValidationError, match="traversal-free"):
        NarrationTimingManifest.model_validate(traversal)

    overlap = manifest.model_dump(mode="json")
    overlap["words"][1]["start_seconds"] = overlap["words"][0]["start_seconds"]
    overlap["timing_id"] = derive_narration_timing_id(overlap)
    with pytest.raises(ValidationError, match="positive duration|nonoverlapping"):
        NarrationTimingManifest.model_validate(overlap)


def test_timed_captions_preserve_script_text_and_follow_word_boundaries() -> None:
    script = _script()
    manifest = _manifest(script, _observations(script, insertion_at=3))

    cues = cues_from_script(script, timing=manifest)

    assert "invented" not in " ".join(cue.text for cue in cues)
    assert " ".join(cue.text for cue in cues) == " ".join(
        segment.text for segment in script.segments
    )
    assert cues[0].start == pytest.approx(manifest.words[0].start_seconds)
    assert cues[-1].end == pytest.approx(manifest.segments[-1].end_seconds)
    assert all(left.end <= right.start for left, right in zip(cues, cues[1:], strict=False))
    with pytest.raises(ValueError, match="differs"):
        cues_from_script(script, target_duration=20, timing=manifest)


def _approved_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "timing-persistence")
    store.initialize("Timing persistence")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "timing-reviewer")
    generate_angles(store, "fixture").require_artifact()
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "timing-reviewer")
    return store


def test_timing_persistence_binds_current_script_audio_and_synthesis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _approved_store(tmp_path)
    narration = store.path("audio/fixture.wav")
    narration.write_bytes(b"first narration bytes")
    project = store.project()
    project.active_versions["audio_asset"] = "asset-narration-fixture"
    store.save_project(project)
    receipt = store.path("audio/narration-synthesis.json")
    receipt.write_text("fixture receipt", encoding="utf-8")
    active_receipt: tuple[Any, Path] | None = (
        SimpleNamespace(synthesis_id="synthesis-1111111111111111"),
        receipt,
    )
    monkeypatch.setattr("techshort.alignment.service.active_audio", lambda _store: narration)
    monkeypatch.setattr("techshort.alignment.service.probe_duration", lambda _path: 60.0)
    monkeypatch.setattr(
        "techshort.alignment.service.active_synthesis_receipt",
        lambda _store: active_receipt,
    )

    manifest = build_narration_timing_manifest(store)
    path = register_narration_timing(store, manifest)

    assert path.is_file()
    assert active_narration_timing(store) == (manifest, path)
    assert manifest.synthesis_id == "synthesis-1111111111111111"
    assert store.project().active_versions["narration_timing"] == manifest.timing_id

    narration.write_bytes(b"changed narration bytes")
    with pytest.raises(ValueError, match="active narration audio"):
        active_narration_timing(store)


def test_sapi_observations_require_current_synthesis_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _approved_store(tmp_path)
    narration = store.path("audio/fixture.wav")
    narration.write_bytes(b"narration")
    project = store.project()
    project.active_versions["audio_asset"] = "asset-narration-fixture"
    store.save_project(project)
    monkeypatch.setattr("techshort.alignment.service.active_audio", lambda _store: narration)
    monkeypatch.setattr("techshort.alignment.service.probe_duration", lambda _path: 60.0)
    monkeypatch.setattr(
        "techshort.alignment.service.active_synthesis_receipt", lambda _store: None
    )
    script = ScriptManifest.model_validate_json(
        store.path("script/script.json").read_text(encoding="utf-8")
    )
    observations = [
        EngineWordObservation(
            sequence_index=index,
            text=word.display_text,
            start_seconds=0.2 + index * 0.3,
        )
        for index, word in enumerate(canonical_script_words(script))
    ]

    with pytest.raises(ValueError, match="current synthesis receipt"):
        build_narration_timing_manifest(
            store,
            observations=observations,
            source="sapi-speak-progress",
        )
