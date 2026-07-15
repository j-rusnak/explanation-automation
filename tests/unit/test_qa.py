from __future__ import annotations

from pathlib import Path

from techshort.alignment import cues_from_script, write_caption_files
from techshort.domain.models import ScriptManifest, SourceIndex, StoryboardManifest
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
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


def _approved_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "qa-test")
    store.initialize("QA test")
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
    write_caption_files(store.path("captions"), cues_from_script(script))
    return store


def test_hard_qa_requires_media_unless_authoring_defer_is_explicit(tmp_path: Path) -> None:
    store = _approved_store(tmp_path)
    hard = run_qa(store)
    assert not hard.passed
    assert any(check.check_id == "renderer-failure" for check in hard.checks)
    authoring = run_qa(store, require_media=False)
    assert authoring.passed, authoring.export_blockers


def test_qa_blocks_stale_angle_artifacts(tmp_path: Path) -> None:
    store = _approved_store(tmp_path)
    project = store.project()
    project.stale_artifacts.append("angles")
    store.save_project(project)

    report = run_qa(store, require_media=False)
    stale = next(check for check in report.checks if check.check_id == "stale-dependencies")
    assert stale.status == "failure"
    assert stale.hard_blocker


def test_qa_detects_changed_extracted_source_after_approval(tmp_path: Path) -> None:
    store = _approved_store(tmp_path)
    sources = load_model(store.path("sources/source-index.json"), SourceIndex)
    source = sources.sources[0]
    store.path(f"sources/extracted/{source.source_id}.txt").write_text(
        "tampered after approval", encoding="utf-8"
    )

    report = run_qa(store, require_media=False)
    assert not report.passed
    failures = {check.check_id for check in report.checks if check.status == "failure"}
    assert "manifest-validation" in failures
    assert "evidence-completeness" in failures


def test_qa_hard_fails_low_scene_background_contrast(tmp_path: Path) -> None:
    store = _approved_store(tmp_path)
    storyboard_path = store.path("storyboard/storyboard.json")
    storyboard = load_model(storyboard_path, StoryboardManifest)
    storyboard.scenes[0].theme_overrides = {
        "background": "#FFFFFF",
        "text": "#FFFFFF",
    }
    atomic_write_model(storyboard_path, storyboard)

    report = run_qa(store, require_media=False)
    contrast = next(check for check in report.checks if check.check_id == "low-text-contrast")
    assert contrast.status == "failure"
    assert contrast.hard_blocker
    assert "title text/background is 1.0:1" in contrast.message


def test_qa_hard_fails_low_scene_panel_contrast(tmp_path: Path) -> None:
    store = _approved_store(tmp_path)
    storyboard_path = store.path("storyboard/storyboard.json")
    storyboard = load_model(storyboard_path, StoryboardManifest)
    scene = next(item for item in storyboard.scenes if item.primitive == "Comparison")
    scene.theme_overrides = {"panel": "#FFFFFF", "text": "#FFFFFF"}
    atomic_write_model(storyboard_path, storyboard)

    report = run_qa(store, require_media=False)
    contrast = next(check for check in report.checks if check.check_id == "low-text-contrast")
    assert contrast.status == "failure"
    assert contrast.hard_blocker
    assert "panel text/background is 1.0:1" in contrast.message
