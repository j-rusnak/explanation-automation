from __future__ import annotations

from pathlib import Path

import pytest

from techshort.alignment import cues_from_script, write_caption_files
from techshort.audio import TranscriptionAttempt
from techshort.domain.models import QACheck, ScriptManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.generation import (
    fixture_claims,
    fixture_script,
    fixture_storyboard,
    generate_angles,
    select_angle,
)
from techshort.ingestion import ingest_source
from techshort.qa import run_qa
from techshort.review import approve_claims, approve_rights, approve_script, approve_storyboard


def _approved_store(tmp_path: Path) -> tuple[ProjectStore, ScriptManifest]:
    store = ProjectStore(tmp_path / "projects", "narration-qa")
    store.initialize("Narration QA")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "qa-reviewer")
    generate_angles(store, "fixture")
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "qa-reviewer")
    fixture_storyboard(store)
    approve_storyboard(store, "qa-reviewer")
    approve_rights(store, "qa-reviewer")
    script = load_model(store.path("script/script.json"), ScriptManifest)
    write_caption_files(store.path("captions"), cues_from_script(script, target_duration=60))
    return store, script


def _patch_audio(monkeypatch: pytest.MonkeyPatch, narration: Path) -> None:
    monkeypatch.setattr("techshort.qa.service.active_audio", lambda _store: narration)
    monkeypatch.setattr("techshort.qa.service.probe_duration", lambda _path: 60.0)


def _comparison_check(store: ProjectStore) -> QACheck:
    report = run_qa(store, require_media=False)
    return next(check for check in report.checks if check.check_id == "narration-script-comparison")


def test_qa_passes_matching_local_narration_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, script = _approved_store(tmp_path)
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"test fixture")
    _patch_audio(monkeypatch, narration)
    transcript = " ".join(segment.text for segment in script.segments)
    monkeypatch.setattr(
        "techshort.qa.service.resolve_narration_transcript",
        lambda _store, _narration: TranscriptionAttempt(transcript, "test sidecar", None),
    )

    check = _comparison_check(store)

    assert check.status == "pass"
    assert "0.0% word error" in check.message


def test_qa_warns_when_local_transcription_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, _script = _approved_store(tmp_path)
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"test fixture")
    _patch_audio(monkeypatch, narration)
    monkeypatch.setattr(
        "techshort.qa.service.resolve_narration_transcript",
        lambda _store, _narration: TranscriptionAttempt(None, None, "no configured local model"),
    )

    check = _comparison_check(store)

    assert check.status == "warning"
    assert "final review" in check.message


def test_qa_hard_fails_material_narration_difference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, _script = _approved_store(tmp_path)
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"test fixture")
    _patch_audio(monkeypatch, narration)
    monkeypatch.setattr(
        "techshort.qa.service.resolve_narration_transcript",
        lambda _store, _narration: TranscriptionAttempt(
            "This recording discusses a completely unrelated subject.",
            "test sidecar",
            None,
        ),
    )

    check = _comparison_check(store)

    assert check.status == "failure"
    assert check.hard_blocker
