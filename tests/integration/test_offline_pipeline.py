from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from techshort.alignment import as_srt, as_vtt, cues_from_script
from techshort.domain.models import ScriptManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.export import export_project, generate_evidence_page
from techshort.generation import fixture_claims, fixture_script, fixture_storyboard
from techshort.ingestion import ingest_source
from techshort.qa import run_qa
from techshort.review import (
    approve_claims,
    approve_rights,
    approve_script,
    approve_storyboard,
    edit_claim,
)


def test_offline_pipeline_through_pre_render_export_gate(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "rolling-shutter")
    store.initialize("Rolling shutter")
    fixture = Path("examples/rolling-shutter/rolling-shutter.md")
    ingest_source(store, fixture)
    claims = fixture_claims(store)
    assert 3 <= len(claims.claims) <= 8
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
    report = run_qa(store, require_media=False)
    assert report.passed
    project = store.project()
    project.title = '<img src=x onerror="alert(1)">'
    store.save_project(project)
    generate_evidence_page(store, store.path("renders/previews/evidence.html"))
    page = store.path("renders/previews/evidence.html").read_text(encoding="utf-8")
    assert "<script src" not in page
    assert '<img src=x onerror="alert(1)">' not in page
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in page
    embedded = re.search(
        r'<script type="application/json" id="techshort-evidence">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert embedded is not None
    assert json.loads(embedded.group(1))["title"] == '<img src=x onerror="alert(1)">'
    with pytest.raises(ValueError, match="final gate"):
        export_project(store)


def test_claim_edit_invalidates_history_and_archives_regeneration(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "rolling-shutter")
    store.initialize("Rolling shutter")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    claims = fixture_claims(store)
    approve_claims(store, "test")
    first = claims.claims[0]
    edit_claim(store, first.claim_id, first.text + " Precisely.", "test")
    assert store.project().approvals.claims == "stale"
    review_log = store.path("reviews/review-log.json").read_text(encoding="utf-8")
    assert "claim claim-row-timing edited" in review_log
    fixture_claims(store)
    assert any(store.path("claims/versions").glob("*.json"))
