from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import techshort.experiments.creative as creative
from techshort.domain.hashing import sha256_file
from techshort.domain.models import ReviewStatus
from techshort.domain.storage import ProjectStore, load_model
from techshort.experiments import (
    ExperimentStore,
    OrganicPlatform,
    RecommendationAction,
    RecommendationApplicationLog,
    analyze_experiment,
    append_observations,
    apply_approved_cover_recommendation,
    approve_experiment,
    approve_recommendation,
    build_observation,
    create_cover_experiment,
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
from techshort.review import approve_claims, approve_script


def _cover_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "cover-experiment")
    store.initialize("Cover experiment")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "experiment-reviewer")
    generate_angles(store, "fixture")
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "experiment-reviewer")
    fixture_storyboard(store)
    generate_fixture_covers(store)
    select_cover(store, "cover-scanline")
    media = store.path(f"export/{store.slug}.mp4")
    media.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"approved-video" * 8)
    return store


def _contract(store: ProjectStore) -> creative.ExportExperimentContract:
    media = store.path(f"export/{store.slug}.mp4")
    return creative.ExportExperimentContract(
        media_path=media.relative_to(store.root).as_posix(),
        media_hash=sha256_file(media),
        captions_srt_path=f"export/{store.slug}.srt",
        captions_vtt_path=f"export/{store.slug}.vtt",
        locked_factual_hash="1" * 64,
        evidence_hash="2" * 64,
        claims_hash="3" * 64,
        limitation_hash="4" * 64,
        rights_hash="5" * 64,
    )


def _fake_cover_renderer(store: ProjectStore, candidate_id: str, output: Path) -> None:
    del store
    output.write_bytes(b"\x89PNG\r\n\x1a\n" + candidate_id.encode("ascii"))


def _create(
    store: ProjectStore, monkeypatch: pytest.MonkeyPatch
) -> tuple[ExperimentStore, creative.ExportExperimentContract]:
    contract = _contract(store)
    monkeypatch.setattr(creative, "_validated_export_contract", lambda _store: contract)
    monkeypatch.setattr(creative, "_render_cover_candidate", _fake_cover_renderer)
    manifest = create_cover_experiment(
        store,
        name="Rolling shutter cover directions",
        hypothesis="A mechanism-led cover will improve organic completion rate.",
        platform=OrganicPlatform.TIKTOK,
        minimum_views_per_variant=500,
    )
    return ExperimentStore(store, manifest.experiment_id), contract


def test_cover_experiment_renders_distinct_covers_around_identical_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _cover_store(tmp_path)
    experiment_store, contract = _create(store, monkeypatch)
    manifest = experiment_store.manifest()

    assert len(manifest.variants) == 3
    assert len({item.media_hash for item in manifest.variants}) == 1
    assert len({item.cover_hash for item in manifest.variants}) == 3
    assert {item.locked_factual_hash for item in manifest.variants} == {
        contract.locked_factual_hash
    }
    control = next(item for item in manifest.variants if item.role.value == "control")
    assert control.variable_value == "cover-scanline"
    assert all(store.path(item.cover_path or "").is_file() for item in manifest.variants)

    repeated = create_cover_experiment(
        store,
        name="Rolling shutter cover directions",
        hypothesis="A mechanism-led cover will improve organic completion rate.",
        platform=OrganicPlatform.TIKTOK,
        minimum_views_per_variant=500,
    )
    assert repeated == manifest


def test_cover_experiment_requires_current_cover_as_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _cover_store(tmp_path)
    contract = _contract(store)
    monkeypatch.setattr(creative, "_validated_export_contract", lambda _store: contract)

    with pytest.raises(ValueError, match="selected cover as control"):
        create_cover_experiment(
            store,
            name="Invalid cover experiment",
            hypothesis="Two treatments without a control are not comparable.",
            platform=OrganicPlatform.INSTAGRAM_REELS,
            candidate_ids=["cover-comparison", "cover-diagram"],
        )


def test_approved_cover_recommendation_uses_normal_invalidation_and_append_only_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _cover_store(tmp_path)
    experiment_store, _ = _create(store, monkeypatch)
    manifest = approve_experiment(experiment_store, "experiment-reviewer")
    started = datetime(2026, 7, 1, 12, tzinfo=UTC)
    ended = started + timedelta(days=1)
    snapshots = []
    for variant in manifest.variants:
        completed = {
            "cover-scanline": 500,
            "cover-comparison": 850,
            "cover-diagram": 200,
        }[variant.variable_value]
        snapshots.append(
            build_observation(
                experiment_id=manifest.experiment_id,
                variant_id=variant.variant_id,
                platform=manifest.platform,
                publication_reference=f"post-{variant.variable_value}",
                window_started_at=started,
                window_ended_at=ended,
                captured_at=ended,
                view_count=1000,
                completed_view_count=completed,
            )
        )
    append_observations(experiment_store, snapshots)
    recommendation = analyze_experiment(experiment_store)
    assert recommendation.action is RecommendationAction.ADOPT_VARIANT
    recommendation = approve_recommendation(
        experiment_store,
        recommendation.recommendation_id,
        "experiment-reviewer",
    )

    project = store.project()
    project.approvals.storyboard = ReviewStatus.APPROVED
    project.approvals.rights = ReviewStatus.APPROVED
    project.approvals.final = ReviewStatus.APPROVED
    store.save_project(project)
    receipt = apply_approved_cover_recommendation(
        experiment_store,
        recommendation.recommendation_id,
        "application-reviewer",
    )

    assert receipt.changed_production_default
    assert receipt.previous_candidate_id == "cover-scanline"
    assert receipt.applied_candidate_id == "cover-comparison"
    assert receipt.invalidated_gates == ["storyboard", "rights", "final"]
    project = store.project()
    assert project.approvals.storyboard is ReviewStatus.STALE
    assert project.approvals.rights is ReviewStatus.STALE
    assert project.approvals.final is ReviewStatus.STALE
    log = load_model(experiment_store.root / "applications.json", RecommendationApplicationLog)
    assert log.applications == [receipt]
    assert (
        apply_approved_cover_recommendation(
            experiment_store,
            recommendation.recommendation_id,
            "application-reviewer",
        )
        == receipt
    )
    persisted = load_model(
        experiment_store.root / "applications.json", RecommendationApplicationLog
    )
    assert len(persisted.applications) == 1


def test_cover_renderer_rejects_path_like_candidate_before_subprocess(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "unsafe-cover")
    store.initialize("Unsafe cover")

    with pytest.raises(ValueError, match="unsafe"):
        creative._render_cover_candidate(store, "../../escape", tmp_path / "escape.png")
