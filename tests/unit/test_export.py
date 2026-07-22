from __future__ import annotations

from pathlib import Path

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.storage import ProjectStore
from techshort.export.service import _archive_existing_export


def test_existing_export_is_versioned_before_replacement(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "export-history")
    store.initialize("Export history")
    export = store.path("export")
    video = export / "export-history.mp4"
    evidence = export / "evidence.html"
    video.write_bytes(b"approved video version one")
    evidence.write_text("version one evidence", encoding="utf-8")

    _archive_existing_export(
        store,
        export,
        {"export-history.mp4", "evidence.html"},
    )

    identity = stable_hash({path.name: sha256_file(path) for path in sorted((video, evidence))})
    archive = store.path(f"export-history/{identity[:16]}")
    assert (archive / video.name).read_bytes() == video.read_bytes()
    assert (archive / evidence.name).read_text(encoding="utf-8") == "version one evidence"

    evidence.write_text("replacement bundle", encoding="utf-8")
    _archive_existing_export(
        store,
        export,
        {"export-history.mp4", "evidence.html"},
    )
    replacement_identity = stable_hash(
        {path.name: sha256_file(path) for path in sorted((video, evidence))}
    )
    replacement = store.path(f"export-history/{replacement_identity[:16]}")
    assert (replacement / evidence.name).read_text(encoding="utf-8") == "replacement bundle"
