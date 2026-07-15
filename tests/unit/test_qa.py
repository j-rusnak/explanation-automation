from __future__ import annotations

from pathlib import Path

from techshort.alignment import cues_from_script, write_caption_files
from techshort.domain.models import ScriptManifest, SourceIndex
from techshort.domain.storage import ProjectStore, load_model
from techshort.generation import fixture_claims, fixture_script, fixture_storyboard
from techshort.ingestion import ingest_source
from techshort.qa import run_qa
from techshort.review import approve_claims, approve_rights, approve_script, approve_storyboard


def _approved_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "qa-test")
    store.initialize("QA test")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "qa-reviewer")
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
