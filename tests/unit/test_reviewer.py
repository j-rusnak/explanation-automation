from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from techshort.audio import NarrationVoice
from techshort.domain.hashing import sha256_file
from techshort.domain.models import (
    AnglesManifest,
    ClaimsManifest,
    CoverManifest,
    CoverSelection,
    StoryboardManifest,
)
from techshort.domain.storage import ProjectStore, load_model
from techshort.experiments import (
    ExperimentStore,
    ExperimentVariable,
    OrganicPlatform,
    VariantRole,
    analyze_experiment,
    append_observations,
    approve_experiment,
    build_observation,
    build_variant,
    derive_experiment_id,
    initialize_experiment,
)
from techshort.generation import (
    fixture_claims,
    fixture_script,
    fixture_storyboard,
    generate_angles,
    select_angle,
)
from techshort.generation.design import generate_fixture_covers, select_cover
from techshort.ingestion import ingest_source
from techshort.publication import GRANT_CONFIRMATION, OrganicPublicationPackage
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


def _approved_cover_experiment(projects: Path) -> tuple[ProjectStore, ExperimentStore]:
    store = ProjectStore(projects, "review-app")
    covers = load_model(store.path("storyboard/covers.json"), CoverManifest)
    selection = load_model(store.path("storyboard/cover-selection.json"), CoverSelection)
    locked_hash = "1" * 64
    name = "Reviewer cover test"
    experiment_id = derive_experiment_id(
        store.project().project_id,
        name,
        ExperimentVariable.COVER,
        locked_hash,
    )
    media = store.path("export/review-app.mp4")
    media.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"reviewed-video" * 4)
    store.path("export/review-app.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nReviewed caption.\n",
        encoding="utf-8",
    )
    store.path("export/review-app.vtt").write_text(
        "WEBVTT\n\n00:00.000 --> 00:02.000\nReviewed caption.\n",
        encoding="utf-8",
    )
    candidates = covers.candidates[:2]
    variants = []
    for index, candidate in enumerate(candidates):
        cover_path = store.path(
            f"experiments/{experiment_id}/variants/{candidate.candidate_id}.png"
        )
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (108, 192), (25 + index * 80, 60, 100)).save(cover_path)
        variants.append(
            build_variant(
                label=candidate.headline,
                role=(
                    VariantRole.CONTROL
                    if candidate.candidate_id == selection.selected_candidate_id
                    else VariantRole.TREATMENT
                ),
                variable=ExperimentVariable.COVER,
                variable_value=candidate.candidate_id,
                media_path="export/review-app.mp4",
                media_hash=sha256_file(media),
                cover_path=cover_path.relative_to(store.root).as_posix(),
                cover_hash=sha256_file(cover_path),
                locked_factual_hash=locked_hash,
                evidence_hash="2" * 64,
                claims_hash="3" * 64,
                limitation_hash="4" * 64,
                rights_hash="5" * 64,
            )
        )
    manifest = initialize_experiment(
        store,
        name=name,
        hypothesis="A reviewed alternative cover will improve completion rate.",
        platform=OrganicPlatform.TIKTOK,
        variable=ExperimentVariable.COVER,
        variants=variants,
        minimum_views_per_variant=100,
    )
    experiment_store = ExperimentStore(store, manifest.experiment_id)
    approve_experiment(experiment_store, "test-reviewer")
    return store, experiment_store


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
        "10 Organic experiments",
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


def test_organic_experiment_step_builds_pending_and_explicit_consent_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    store, experiment_store = _approved_cover_experiment(projects)
    manifest = experiment_store.manifest()
    control = next(item for item in manifest.variants if item.role is VariantRole.CONTROL)
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()
    app.sidebar.radio(key="review-step").set_value("10 Organic experiments")
    app.run()

    assert not app.exception
    assert app.button(key="experiment-create")
    assert app.selectbox(key="organic-experiment-selector").value == manifest.experiment_id
    assert app.button(key=f"experiment-approve-{manifest.experiment_id}").disabled
    assert app.selectbox(key=f"publication-variant-{manifest.experiment_id}")
    assert app.download_button(
        key=f"experiment-template-download-{manifest.experiment_id}"
    )
    warnings = " ".join(item.value for item in app.warning)
    assert "does not log into an account" in warnings
    assert "claim that publication occurred" in warnings

    app.text_area(key=f"publication-copy-{manifest.experiment_id}").set_value(
        "A reviewed cover test for the approved technical explainer."
    )
    app.text_area(key=f"publication-alt-{manifest.experiment_id}").set_value(
        "A reviewed vertical explainer cover."
    )
    app.run()
    app.button(key=f"publication-request-prepare-{manifest.experiment_id}").click()
    app.run()
    build_key = f"publication-package-build-{manifest.experiment_id}-{control.variant_id}"
    assert app.button(key=build_key)
    app.button(key=build_key).click()
    app.run()

    grant_key = f"publication-consent-grant-{manifest.experiment_id}-{control.variant_id}"
    consent_key = f"publication-consent-{manifest.experiment_id}-{control.variant_id}"
    assert app.button(key=grant_key).disabled
    app.text_input(key=consent_key).set_value(GRANT_CONFIRMATION)
    app.run()
    assert not app.button(key=grant_key).disabled
    app.button(key=grant_key).click()
    app.run()

    package_manifests = sorted(
        store.path(
            f"experiments/{manifest.experiment_id}/publication/{control.variant_id}/tiktok"
        ).glob("organic-package-*/package-manifest.json")
    )
    packages = [load_model(path, OrganicPublicationPackage) for path in package_manifests]
    assert {item.consent.state for item in packages} == {"pending", "granted"}
    granted = next(item for item in packages if item.consent.state == "granted")
    assert granted.manual_upload_authorized
    assert not granted.automated_upload
    assert not granted.claimed_posted
    assert not app.exception


def test_organic_experiment_step_analyzes_approves_and_routes_cover_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = _reviewable_project(tmp_path)
    _, experiment_store = _approved_cover_experiment(projects)
    manifest = experiment_store.manifest()
    control = next(item for item in manifest.variants if item.role is VariantRole.CONTROL)
    treatment = next(item for item in manifest.variants if item.role is VariantRole.TREATMENT)
    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = datetime(2026, 7, 8, tzinfo=UTC)
    captured = datetime(2026, 7, 9, tzinfo=UTC)
    append_observations(
        experiment_store,
        [
            build_observation(
                experiment_id=manifest.experiment_id,
                variant_id=control.variant_id,
                platform=manifest.platform,
                publication_reference="control-post",
                window_started_at=start,
                window_ended_at=end,
                captured_at=captured,
                view_count=1000,
                completed_view_count=400,
            ),
            build_observation(
                experiment_id=manifest.experiment_id,
                variant_id=treatment.variant_id,
                platform=manifest.platform,
                publication_reference="treatment-post",
                window_started_at=start,
                window_ended_at=end,
                captured_at=captured,
                view_count=1000,
                completed_view_count=800,
            ),
        ],
    )
    recommendation = analyze_experiment(experiment_store)
    assert recommendation.action.value == "adopt-variant"
    applied: dict[str, str] = {}

    def fake_apply(
        selected_store: ExperimentStore,
        recommendation_id: str,
        reviewer_identifier: str,
    ) -> object:
        applied.update(
            experiment_id=selected_store.experiment_id,
            recommendation_id=recommendation_id,
            reviewer=reviewer_identifier,
        )
        return object()

    monkeypatch.setattr(
        "techshort.experiments.apply_approved_cover_recommendation",
        fake_apply,
    )
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(projects))
    app = AppTest.from_file("reviewer/streamlit_app.py", default_timeout=30).run()
    app.sidebar.radio(key="review-step").set_value("10 Organic experiments")
    app.run()

    approve_key = f"experiment-recommendation-approve-{recommendation.recommendation_id}"
    assert not app.button(key=approve_key).disabled
    assert any("Wilson intervals" in item.value for item in app.warning)
    app.button(key=approve_key).click()
    app.run()
    apply_key = f"experiment-recommendation-apply-{recommendation.recommendation_id}"
    assert not app.button(key=apply_key).disabled
    app.button(key=apply_key).click()
    app.run()

    assert applied == {
        "experiment_id": manifest.experiment_id,
        "recommendation_id": recommendation.recommendation_id,
        "reviewer": "local-reviewer",
    }
    assert any(
        "invalidate storyboard, rights, and final approval" in item.value for item in app.warning
    )
    assert not app.exception


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
