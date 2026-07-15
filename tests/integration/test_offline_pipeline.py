from __future__ import annotations

from pathlib import Path

import pytest

from techshort.alignment import as_srt, as_vtt, cues_from_script
from techshort.domain.models import ScriptManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.export import export_project, generate_evidence_page
from techshort.generation import fixture_claims, fixture_script, fixture_storyboard
from techshort.ingestion import ingest_source
from techshort.qa import run_qa
from techshort.review import approve_claims, approve_rights, approve_script, approve_storyboard


def test_offline_pipeline_through_pre_render_export_gate(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "rolling-shutter")
    store.initialize("Rolling shutter")
    fixture = Path("examples/rolling-shutter/rolling-shutter.md")
    ingest_source(store, fixture)
    claims = fixture_claims(store)
    assert len(claims.claims) == 5
    approve_claims(store, "test")
    script = fixture_script(store)
    approve_script(store, "test")
    storyboard = fixture_storyboard(store)
    assert len({scene.primitive for scene in storyboard.scenes}) == 7
    approve_storyboard(store, "test")
    approve_rights(store, "test")
    script = load_model(store.path("script/script.json"), ScriptManifest)
    cues = cues_from_script(script)
    store.path("captions/captions.srt").write_text(as_srt(cues), encoding="utf-8")
    store.path("captions/captions.vtt").write_text(as_vtt(cues), encoding="utf-8")
    report = run_qa(store)
    assert report.passed
    generate_evidence_page(store, store.path("renders/previews/evidence.html"))
    assert "<script src" not in store.path("renders/previews/evidence.html").read_text()
    with pytest.raises(ValueError, match="final gate"):
        export_project(store)
