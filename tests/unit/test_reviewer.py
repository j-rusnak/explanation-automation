from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from techshort.domain.models import ClaimsManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.generation import fixture_claims, fixture_script, fixture_storyboard
from techshort.ingestion import ingest_source
from techshort.review import approve_claims, approve_script


def _reviewable_project(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    store = ProjectStore(projects, "review-app")
    store.initialize("Reviewer smoke test")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "test-reviewer")
    fixture_script(store)
    approve_script(store, "test-reviewer")
    fixture_storyboard(store)
    return projects


def test_reviewer_constructs_every_step_without_duplicate_widget_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    # AppTest executes the script afresh on every run and therefore exercises the
    # same top-level import and widget registration path as `streamlit run`.
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    steps = [
        "1 Project",
        "2 Sources",
        "3 Claims and evidence",
        "4 Script",
        "5 Storyboard and assets",
        "6 Narration and captions",
        "7 Preview",
        "8 QA",
        "9 Export",
    ]
    for step in steps:
        app.sidebar.radio(key="review-step").set_value(step)
        app.run()
        assert not app.exception, f"reviewer failed while constructing {step}"

    source = Path("reviewer/streamlit_app.py").read_text(encoding="utf-8")
    assert "unsafe_allow_html" not in source


def test_claim_step_exposes_individual_review_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    store = ProjectStore(projects, "review-app")
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()
    app.sidebar.radio(key="review-step").set_value("3 Claims and evidence")
    app.run()
    assert not app.exception
    assert any("Independent critique" in item.value for item in app.subheader)
    for claim_id in (claim.claim_id for claim in claims.claims):
        assert app.button(key=f"claim-approve-{claim_id}")
        assert app.button(key=f"claim-edit-{claim_id}")
        assert app.button(key=f"claim-reject-{claim_id}")
        assert app.button(key=f"claim-add-note-{claim_id}")
