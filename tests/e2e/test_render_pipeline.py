from __future__ import annotations

import os
from pathlib import Path

import pytest

from techshort.alignment import cues_from_script, write_caption_files
from techshort.domain.models import RenderManifest, ScriptManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.export import export_project, generate_evidence_page
from techshort.generation import fixture_claims, fixture_script, fixture_storyboard
from techshort.ingestion import ingest_source
from techshort.qa import run_qa
from techshort.rendering import probe_render_metadata, render_video
from techshort.review import (
    approve_claims,
    approve_final,
    approve_rights,
    approve_script,
    approve_storyboard,
)

pytestmark = pytest.mark.skipif(
    os.getenv("TECHSHORT_RUN_RENDER_E2E") != "1",
    reason="set TECHSHORT_RUN_RENDER_E2E=1 for the real Remotion/FFmpeg smoke test",
)


def test_complete_real_render_and_export(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "rolling-shutter-e2e")
    store.initialize("Rolling-Shutter Distortion")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "e2e-reviewer")
    fixture_script(store)
    approve_script(store, "e2e-reviewer")
    fixture_storyboard(store)
    approve_storyboard(store, "e2e-reviewer")
    approve_rights(store, "e2e-reviewer")
    script = load_model(store.path("script/script.json"), ScriptManifest)
    write_caption_files(store.path("captions"), cues_from_script(script))

    preview = render_video(store, preview=True)
    preview_qa = run_qa(store, preview)
    assert preview_qa.passed, preview_qa.export_blockers
    preview_manifest = load_model(
        store.path("renders/previews/render-manifest.json"), RenderManifest
    )
    assert preview_manifest.watermarked
    preview_metadata = probe_render_metadata(preview)
    assert preview_metadata is not None
    assert (preview_metadata.width, preview_metadata.height) == (360, 640)
    generate_evidence_page(store, store.path("renders/previews/evidence.html"))

    with pytest.raises(ValueError, match="final gate"):
        export_project(store)
    approve_final(store, "e2e-reviewer")

    final = render_video(store, preview=False)
    final_qa = run_qa(store, final, destination="renders/final/qa-report.json")
    assert final_qa.passed, final_qa.export_blockers
    final_manifest = load_model(store.path("renders/final/render-manifest.json"), RenderManifest)
    assert not final_manifest.watermarked
    final_metadata = probe_render_metadata(final)
    assert final_metadata is not None
    assert (final_metadata.width, final_metadata.height) == (1080, 1920)
    assert final_metadata.fps == pytest.approx(30)
    assert 45 <= final_metadata.duration <= 75

    exported = export_project(store)
    assert {path.name for path in exported.iterdir()} == {
        "rolling-shutter-e2e.mp4",
        "rolling-shutter-e2e.srt",
        "rolling-shutter-e2e.vtt",
        "cover.png",
        "transcript.txt",
        "evidence.html",
        "evidence-ledger.json",
        "asset-rights.json",
        "qa-report.json",
        "render-manifest.json",
    }
