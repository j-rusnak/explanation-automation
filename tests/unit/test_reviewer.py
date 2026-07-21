from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from techshort.audio import NarrationVoice
from techshort.domain.models import (
    AnglesManifest,
    ClaimsManifest,
    CoverManifest,
    CoverSelection,
    StoryboardManifest,
)
from techshort.domain.storage import ProjectStore, load_model
from techshort.generation import (
    fixture_claims,
    fixture_script,
    fixture_storyboard,
    generate_angles,
    select_angle,
)
from techshort.generation.design import generate_fixture_covers, select_cover
from techshort.ingestion import ingest_source
from techshort.review import approve_claims, approve_script


@pytest.fixture(autouse=True)
def _installed_local_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    voice = NarrationVoice(
        provider="windows-sapi",
        name="Fixture Local Voice",
        culture="en-US",
        gender="Neutral",
        age="Adult",
    )
    monkeypatch.setattr("techshort.audio.discover_windows_voices", lambda: [voice])


def _reviewable_project(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    store = ProjectStore(projects, "review-app")
    store.initialize("Reviewer smoke test")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "test-reviewer")
    generate_angles(store, "fixture")
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "test-reviewer")
    fixture_storyboard(store)
    covers = generate_fixture_covers(store)
    select_cover(store, covers.candidates[0].candidate_id)
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
    assert app.selectbox(key="project-theme")
    assert app.button(key="project-theme-apply")
    assert app.selectbox(key="project-pacing")
    assert app.button(key="project-pacing-apply")
    assert app.selectbox(key="project-narration-mode")
    assert app.button(key="project-narration-mode-apply")
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


def test_script_step_shows_all_angles_and_explicit_selection_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    store = ProjectStore(projects, "review-app")
    angles = load_model(store.path("script/angles.json"), AnglesManifest)
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()
    app.sidebar.radio(key="review-step").set_value("4 Script")
    app.run()
    assert not app.exception
    assert any("Editorial critique" in item.value for item in app.subheader)
    assert any("Retention plan" in item.value for item in app.subheader)
    assert any(metric.label == "Narration pace" and "WPM" in metric.value for metric in app.metric)
    assert any(item.label == "Retention event schedule" for item in app.expander)
    for candidate in angles.candidates:
        assert any(candidate.title in item.value for item in app.markdown)
        assert app.button(key=f"angle-select-{candidate.angle}")


def test_storyboard_step_shows_cover_directions_and_scene_art_direction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    store = ProjectStore(projects, "review-app")
    covers = load_model(store.path("storyboard/covers.json"), CoverManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()
    app.sidebar.radio(key="review-step").set_value("5 Storyboard and assets")
    app.run()

    assert not app.exception
    assert app.button(key="covers-generate")
    assert any("Visual critique" in item.value for item in app.subheader)
    for candidate in covers.candidates:
        assert any(candidate.headline in item.value for item in app.markdown)
        assert app.button(key=f"cover-select-{candidate.candidate_id}")
    for scene in storyboard.scenes:
        assert app.text_input(key=f"scene-citation-label-{scene.scene_id}")
        assert app.selectbox(key=f"scene-layout-{scene.scene_id}")
        assert app.selectbox(key=f"scene-motion-{scene.scene_id}")


def test_narration_step_exposes_bounded_local_audio_and_rights_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()
    app.sidebar.radio(key="review-step").set_value("6 Narration and captions")
    app.run()

    assert not app.exception
    assert app.selectbox(key="local-narration-voice").value == "Fixture Local Voice"
    assert app.slider(key="local-narration-rate").value == 1
    assert app.slider(key="local-narration-volume").value == 100
    assert app.selectbox(key="local-narration-rights-status").value == "unknown"
    assert app.button(key="local-narration-synthesize")
    assert app.selectbox(key="sound-design-preset").value == "subtle"
    assert app.button(key="sound-design-generate")
    warnings = " ".join(item.value for item in app.warning)
    assert "does not establish commercial reuse rights" in warnings
    assert "cannot pass export rights review" in warnings


def test_narration_step_passes_reviewed_controls_to_local_audio_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    calls: dict[str, object] = {}

    def fake_synthesis(
        store: ProjectStore,
        **options: object,
    ) -> object:
        calls["synthesis_slug"] = store.slug
        calls["synthesis_options"] = options
        return object()

    def fake_sound_design(store: ProjectStore, preset: str) -> object:
        calls["sound_slug"] = store.slug
        calls["sound_preset"] = preset
        return object()

    monkeypatch.setattr("techshort.audio.synthesize_local_narration", fake_synthesis)
    monkeypatch.setattr(
        "techshort.audio.sound_design.generate_sound_design",
        fake_sound_design,
    )
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()
    app.sidebar.radio(key="review-step").set_value("6 Narration and captions")
    app.run()

    app.slider(key="local-narration-rate").set_value(4)
    app.slider(key="local-narration-volume").set_value(72)
    app.selectbox(key="local-narration-rights-status").set_value("permissively-licensed")
    app.text_input(key="local-narration-license").set_value("Fixture license")
    app.text_input(key="local-narration-attribution").set_value("Fixture attribution")
    app.run()
    app.button(key="local-narration-synthesize").click()
    app.run()

    assert calls["synthesis_slug"] == "review-app"
    assert calls["synthesis_options"] == {
        "voice_name": "Fixture Local Voice",
        "rate": 4,
        "volume": 72,
        "rights_status": "permissively-licensed",
        "license_name": "Fixture license",
        "required_attribution": "Fixture attribution",
    }

    app.selectbox(key="sound-design-preset").set_value("present")
    app.run()
    app.button(key="sound-design-generate").click()
    app.run()
    assert calls["sound_slug"] == "review-app"
    assert calls["sound_preset"] == "present"


def test_qa_step_surfaces_creative_quality_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()
    app.sidebar.radio(key="review-step").set_value("8 QA")
    app.run()

    assert not app.exception
    assert any("Creative quality review" in item.value for item in app.subheader)
    assert any("Retention plan" in item.value for item in app.subheader)
    assert app.checkbox(key="creative-show-passes")


def test_project_preferences_and_cover_selection_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    store = ProjectStore(projects, "review-app")
    covers = load_model(store.path("storyboard/covers.json"), CoverManifest)
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()

    app.selectbox(key="project-theme").set_value("signal-lab")
    app.run()
    app.button(key="project-theme-apply").click()
    app.run()
    assert store.project().theme == "signal-lab"

    app.selectbox(key="project-pacing").set_value("measured")
    app.run()
    app.button(key="project-pacing-apply").click()
    app.run()
    assert store.project().pacing == "measured"

    app.selectbox(key="project-narration-mode").set_value("silent-reviewed")
    app.run()
    app.button(key="project-narration-mode-apply").click()
    app.run()
    assert store.project().narration_mode == "silent-reviewed"

    app.sidebar.radio(key="review-step").set_value("5 Storyboard and assets")
    app.run()
    replacement = covers.candidates[1]
    app.button(key=f"cover-select-{replacement.candidate_id}").click()
    app.run()
    selection = load_model(store.path("storyboard/cover-selection.json"), CoverSelection)
    assert selection.selected_candidate_id == replacement.candidate_id
