from __future__ import annotations

import json
from pathlib import Path

import pytest

from techshort.domain.hashing import sha256_file
from techshort.domain.models import (
    ProjectManifest,
    QAReport,
    ReviewLog,
    ReviewStatus,
    SourceDocument,
    SourceIndex,
)
from techshort.domain.storage import (
    ProjectStore,
    atomic_write_json,
    atomic_write_text,
    load_model,
)
from techshort.ingestion import (
    get_active_source,
    ingest_source,
    verify_source_integrity,
)


def _approved_project(store: ProjectStore) -> None:
    project = store.project()
    for gate in ("claims", "script", "storyboard", "rights", "final"):
        setattr(project.approvals, gate, ReviewStatus.APPROVED)
    project.stale_artifacts = []
    project.downstream_valid = True
    store.save_project(project)


def test_schema_100_artifacts_load_without_new_provenance_fields() -> None:
    project = ProjectManifest.model_validate(
        {"schema_version": "1.0.0", "project_id": "project-x", "slug": "x", "title": "X"}
    )
    source = SourceDocument.model_validate(
        {
            "schema_version": "1.0.0",
            "source_id": "source-x",
            "source_type": "text",
            "original_filename": "x.txt",
            "content_hash": "a" * 64,
            "local_path": "sources/originals/x.txt",
            "page_or_section_count": 1,
            "title": "X",
        }
    )
    index = SourceIndex.model_validate(
        {"schema_version": "1.0.0", "sources": [source.model_dump(mode="json")]}
    )
    qa = QAReport.model_validate(
        {
            "schema_version": "1.0.0",
            "project_id": "project-x",
            "checks": [],
            "export_blockers": [],
        }
    )
    assert project.active_source_id is None
    assert source.extracted_text_hash is None
    assert index.active_source_id is None
    assert qa.artifact_hashes == {}
    assert qa.media_hash is None


def test_initialize_repairs_missing_directories_and_review_log(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "repair")
    original = store.initialize("Original title")
    store.path("reviews/review-log.json").unlink()
    store.path("captions").rmdir()

    repaired = store.initialize("Replacement title")

    assert repaired.project_id == original.project_id
    assert repaired.title == "Original title"
    assert store.path("captions").is_dir()
    assert load_model(store.path("reviews/review-log.json"), ReviewLog).reviews == []


def test_atomic_text_and_json_helpers_replace_complete_values(tmp_path: Path) -> None:
    text_path = tmp_path / "nested" / "value.txt"
    json_path = tmp_path / "nested" / "value.json"
    atomic_write_text(text_path, "first\n")
    atomic_write_text(text_path, "second\n")
    atomic_write_json(json_path, {"z": 2, "a": [1]})
    assert text_path.read_text(encoding="utf-8") == "second\n"
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"a": [1], "z": 2}
    assert not list(text_path.parent.glob("*.tmp"))


def test_ingestion_selects_active_source_and_records_exact_hashes(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "sources")
    store.initialize("Sources")
    first = tmp_path / "first.txt"
    second = tmp_path / "second.md"
    first.write_text("First source text.", encoding="utf-8")
    second.write_text("# Second\nSecond source text.", encoding="utf-8")

    first_document = ingest_source(store, first)
    second_document = ingest_source(store, second)
    index = load_model(store.path("sources/source-index.json"), SourceIndex)
    project = store.project()

    assert index.active_source_id == second_document.source_id
    assert project.active_source_id == second_document.source_id
    assert get_active_source(store).source_id == second_document.source_id
    assert first_document.extracted_text_hash
    assert second_document.extracted_text_hash == sha256_file(
        store.path(f"sources/extracted/{second_document.source_id}.txt")
    )
    assert (
        project.dependency_hashes["active-source-extracted"] == second_document.extracted_text_hash
    )


def test_unchanged_reingestion_is_idempotent_but_new_source_invalidates(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "idempotent")
    store.initialize("Idempotent")
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("Stable source text.", encoding="utf-8")
    second.write_text("Different source text.", encoding="utf-8")
    ingest_source(store, first)
    _approved_project(store)

    ingest_source(store, first)
    unchanged = store.project()
    assert unchanged.approvals.claims == ReviewStatus.APPROVED
    assert unchanged.stale_artifacts == []

    ingest_source(store, second)
    changed = store.project()
    assert changed.approvals.claims == ReviewStatus.STALE
    assert changed.approvals.final == ReviewStatus.STALE
    assert "claims" in changed.stale_artifacts


def test_source_integrity_detects_original_and_extracted_tampering(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "integrity")
    store.initialize("Integrity")
    source = tmp_path / "source.txt"
    source.write_text("Evidence that must stay exact.", encoding="utf-8")
    document = ingest_source(store, source)
    verify_source_integrity(store, document)

    extracted = store.path(f"sources/extracted/{document.source_id}.txt")
    extracted.write_text("tampered extraction", encoding="utf-8")
    with pytest.raises(ValueError, match="extracted text.*hash"):
        verify_source_integrity(store, document)

    ingest_source(store, source)
    original = store.path(document.local_path)
    original.write_text("tampered original", encoding="utf-8")
    with pytest.raises(ValueError, match="content hash"):
        verify_source_integrity(store, document)
