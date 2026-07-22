from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from techshort.domain.hashing import sha256_bytes, sha256_file
from techshort.domain.models import ReviewStatus
from techshort.domain.storage import ProjectStore
from techshort.experiments import (
    ComparisonStatus,
    ExperimentManifest,
    ExperimentStore,
    ExperimentVariable,
    MetricName,
    ObservationSnapshot,
    OrganicPlatform,
    RecommendationAction,
    Variant,
    VariantRole,
    analyze_experiment,
    append_observations,
    approve_experiment,
    approve_recommendation,
    build_metrics_template,
    build_observation,
    build_variant,
    derive_experiment_id,
    experiment_status,
    import_manual_observations,
    initialize_experiment,
    list_experiment_ids,
    parse_manual_observations,
    write_metrics_template,
)

START = datetime(2026, 7, 1, 12, tzinfo=UTC)
LOCKED_HASH = sha256_bytes(b"locked factual clauses and limitation")
EVIDENCE_HASH = sha256_bytes(b"approved evidence")
CLAIMS_HASH = sha256_bytes(b"approved claims")
LIMITATION_HASH = sha256_bytes(b"approved limitation")
RIGHTS_HASH = sha256_bytes(b"approved rights")


def _project(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "experiment-demo")
    store.initialize("Experiment Demo")
    return store


def _variant(
    store: ProjectStore,
    *,
    role: VariantRole,
    value: str,
    body: bytes,
    variable: ExperimentVariable = ExperimentVariable.HOOK,
    locked_hash: str = LOCKED_HASH,
) -> Variant:
    name = f"{role.value}-{value.replace(' ', '-').casefold()}.mp4"
    path = store.path(f"renders/final/{name}")
    path.write_bytes(body)
    return build_variant(
        label=f"{role.value.title()} {value}",
        role=role,
        variable=variable,
        variable_value=value,
        media_path=f"renders/final/{name}",
        media_hash=sha256_file(path),
        locked_factual_hash=locked_hash,
        evidence_hash=EVIDENCE_HASH,
        claims_hash=CLAIMS_HASH,
        limitation_hash=LIMITATION_HASH,
        rights_hash=RIGHTS_HASH,
    )


def _experiment(
    tmp_path: Path,
    *,
    minimum_views: int = 500,
    primary_metric: MetricName = MetricName.COMPLETION_RATE,
) -> tuple[ProjectStore, ExperimentStore, ExperimentManifest]:
    project = _project(tmp_path)
    control = _variant(
        project,
        role=VariantRole.CONTROL,
        value="question hook",
        body=b"control media",
    )
    treatment = _variant(
        project,
        role=VariantRole.TREATMENT,
        value="visual cold open",
        body=b"treatment media",
    )
    manifest = initialize_experiment(
        project,
        name="Cold-open test",
        hypothesis="A visual cold open improves completed views without changing facts.",
        platform=OrganicPlatform.INSTAGRAM_REELS,
        variable=ExperimentVariable.HOOK,
        variants=[control, treatment],  # type: ignore[list-item]
        primary_metric=primary_metric,
        minimum_views_per_variant=minimum_views,
    )
    experiment_store = ExperimentStore(project, manifest.experiment_id)
    return project, experiment_store, approve_experiment(experiment_store, "local-reviewer")


def _observation(
    manifest: ExperimentManifest,
    variant_index: int,
    *,
    views: int,
    completed: int,
    hours: int = 24,
    end_offset_hours: int = 0,
) -> ObservationSnapshot:
    variant = manifest.variants[variant_index]
    ended = START + timedelta(hours=hours + end_offset_hours)
    return build_observation(
        experiment_id=manifest.experiment_id,
        variant_id=variant.variant_id,
        platform=manifest.platform,
        publication_reference=f"organic-post-{variant_index}",
        window_started_at=START,
        window_ended_at=ended,
        captured_at=ended + timedelta(minutes=5),
        view_count=views,
        completed_view_count=completed,
        skipped_view_count=views - completed,
        like_count=completed // 4,
        comment_count=completed // 20,
        share_count=completed // 10,
        save_count=completed // 8,
        follow_count=completed // 25,
        total_watch_time_seconds=float(views * 28),
    )


def test_initialize_approves_strict_atomic_experiment(tmp_path: Path) -> None:
    project, store, manifest = _experiment(tmp_path)
    assert manifest.review_status is ReviewStatus.APPROVED
    assert all(item.review_status is ReviewStatus.APPROVED for item in manifest.variants)
    assert manifest.approval_hash is not None
    assert store.manifest_path == project.path(
        f"experiments/{manifest.experiment_id}/experiment.json"
    )
    assert store.observations_path.is_file()
    assert store.recommendations_path.is_file()
    assert store.reviews_path.is_file()
    assert len(store.reviews().decisions) == 3
    approve_experiment(store, "local-reviewer")
    assert len(store.reviews().decisions) == 3
    assert list_experiment_ids(project) == [manifest.experiment_id]
    payload = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "2.0.0"
    with pytest.raises(ValidationError, match="schema_version"):
        ExperimentManifest.model_validate(payload)


def test_metrics_templates_are_deterministic_blank_and_aggregate_only(tmp_path: Path) -> None:
    _, store, manifest = _experiment(tmp_path)
    csv_template = build_metrics_template(store, "csv")
    repeated = build_metrics_template(store, "csv")

    assert csv_template == repeated
    assert csv_template.variant_count == len(manifest.variants)
    assert "comparable" in csv_template.guidance
    rows = list(csv.DictReader(io.StringIO(csv_template.content)))
    assert [row["variant_id"] for row in rows] == [
        variant.variant_id for variant in manifest.variants
    ]
    assert {row["platform"] for row in rows} == {manifest.platform.value}
    assert {row["window_started_at"] for row in rows} == {"REQUIRED_COMPARABLE_WINDOW_START_UTC"}
    assert {row["window_ended_at"] for row in rows} == {"REQUIRED_EQUAL_DURATION_WINDOW_END_UTC"}
    aggregate_fields = {
        "view_count",
        "total_watch_time_seconds",
        "completed_view_count",
        "skipped_view_count",
        "like_count",
        "comment_count",
        "share_count",
        "save_count",
        "follow_count",
    }
    assert all(row[field] == "" for row in rows for field in aggregate_fields)
    assert not any(
        forbidden in csv_template.content.casefold()
        for forbidden in ("viewer_id", "user_id", "email", "device_id")
    )

    json_template = build_metrics_template(store, "json")
    json_rows = json.loads(json_template.content)
    assert [row["variant_id"] for row in json_rows] == [
        variant.variant_id for variant in manifest.variants
    ]
    assert all(row[field] is None for row in json_rows for field in aggregate_fields)
    assert all(row["snapshot_id"] is None for row in json_rows)
    with pytest.raises(ValidationError):
        parse_manual_observations(json_template.content, "json")


def test_metrics_template_requires_current_approval_and_variant_bytes(tmp_path: Path) -> None:
    project = _project(tmp_path)
    variants = [
        _variant(project, role=VariantRole.CONTROL, value="control", body=b"control"),
        _variant(project, role=VariantRole.TREATMENT, value="treatment", body=b"treatment"),
    ]
    manifest = initialize_experiment(
        project,
        name="Pending template test",
        hypothesis="Approved variants are required before metrics collection begins.",
        platform=OrganicPlatform.TIKTOK,
        variable=ExperimentVariable.HOOK,
        variants=variants,
    )
    store = ExperimentStore(project, manifest.experiment_id)
    with pytest.raises(ValueError, match="human approval"):
        build_metrics_template(store)

    approve_experiment(store, "template-reviewer")
    reviews = store.reviews()
    reviews.decisions.clear()
    store.save_reviews(reviews)
    with pytest.raises(ValueError, match="approval record"):
        build_metrics_template(store)

    current_project, current_store, current = _experiment(tmp_path / "current")
    current_project.path(current.variants[0].media_path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="variant media is missing or changed"):
        build_metrics_template(current_store)


def test_metrics_template_write_is_scoped_idempotent_and_never_overwrites(
    tmp_path: Path,
) -> None:
    _, store, _ = _experiment(tmp_path)
    template = build_metrics_template(store, "csv")

    written = write_metrics_template(store, template, "blank-aggregate-metrics.csv")
    assert written == store.root / "templates" / "blank-aggregate-metrics.csv"
    assert write_metrics_template(store, template, "blank-aggregate-metrics.csv") == written
    original = written.read_text(encoding="utf-8")
    written.write_text("different existing template\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        write_metrics_template(store, template, "blank-aggregate-metrics.csv")
    assert written.read_text(encoding="utf-8") == "different existing template\n"
    with pytest.raises(ValueError, match="simple safe"):
        write_metrics_template(store, template, "../escape.csv")
    with pytest.raises(ValueError, match="simple safe"):
        write_metrics_template(store, template, "wrong.json")
    assert original.startswith("schema_version,snapshot_id,experiment_id")


def test_experiment_rejects_multiple_variables_and_changed_facts(tmp_path: Path) -> None:
    project = _project(tmp_path)
    control = _variant(
        project,
        role=VariantRole.CONTROL,
        value="control",
        body=b"control",
    )
    other_variable = _variant(
        project,
        role=VariantRole.TREATMENT,
        value="fast",
        body=b"fast",
        variable=ExperimentVariable.PACING,
    )
    experiment_id = derive_experiment_id(
        project.project().project_id,
        "Invalid test",
        ExperimentVariable.HOOK,
        LOCKED_HASH,
    )
    with pytest.raises(ValidationError, match="only the declared experiment variable"):
        ExperimentManifest(
            experiment_id=experiment_id,
            project_id=project.project().project_id,
            name="Invalid test",
            hypothesis="Only one presentation variable may change at a time.",
            platform=OrganicPlatform.TIKTOK,
            variable=ExperimentVariable.HOOK,
            variants=[control, other_variable],  # type: ignore[list-item]
        )
    changed_facts = _variant(
        project,
        role=VariantRole.TREATMENT,
        value="new hook",
        body=b"new hook",
        locked_hash=sha256_bytes(b"different factual content"),
    )
    with pytest.raises(ValidationError, match="locked factual hash"):
        ExperimentManifest(
            experiment_id=experiment_id,
            project_id=project.project().project_id,
            name="Invalid test",
            hypothesis="Presentation tests must preserve approved factual content.",
            platform=OrganicPlatform.TIKTOK,
            variable=ExperimentVariable.HOOK,
            variants=[control, changed_facts],
        )


def test_cover_experiment_reuses_media_and_verifies_distinct_covers(tmp_path: Path) -> None:
    project = _project(tmp_path)
    media = project.path("renders/final/shared.mp4")
    media.write_bytes(b"identical video body")
    variants: list[Variant] = []
    for role, value, content in (
        (VariantRole.CONTROL, "diagram cover", b"diagram cover"),
        (VariantRole.TREATMENT, "question cover", b"question cover"),
    ):
        cover_path = project.path(f"renders/final/{role.value}-cover.png")
        cover_path.write_bytes(content)
        variants.append(
            build_variant(
                label=f"{role.value.title()} cover",
                role=role,
                variable=ExperimentVariable.COVER,
                variable_value=value,
                media_path="renders/final/shared.mp4",
                media_hash=sha256_file(media),
                cover_path=f"renders/final/{role.value}-cover.png",
                cover_hash=sha256_file(cover_path),
                locked_factual_hash=LOCKED_HASH,
                evidence_hash=EVIDENCE_HASH,
                claims_hash=CLAIMS_HASH,
                limitation_hash=LIMITATION_HASH,
                rights_hash=RIGHTS_HASH,
            )
        )
    manifest = initialize_experiment(
        project,
        name="Cover test",
        hypothesis="A question-led cover may improve initial organic viewing.",
        platform=OrganicPlatform.TIKTOK,
        variable=ExperimentVariable.COVER,
        variants=variants,
    )
    store = ExperimentStore(project, manifest.experiment_id)
    approve_experiment(store, "reviewer")
    assert experiment_status(store).blockers == [
        "aggregate observations missing for 2 variant(s)",
        "experiment has not been analyzed",
    ]
    project.path(variants[1].cover_path or "").write_bytes(b"changed cover bytes")
    assert (
        f"variant cover is missing or changed: {variants[1].variant_id}"
        in experiment_status(store).blockers
    )


def test_manual_import_rejects_viewer_data_unknown_fields_and_regressions(
    tmp_path: Path,
) -> None:
    _, store, manifest = _experiment(tmp_path)
    base = {
        "experiment_id": manifest.experiment_id,
        "variant_id": manifest.variants[0].variant_id,
        "platform": manifest.platform.value,
        "publication_reference": "organic-post-0",
        "window_started_at": START.isoformat(),
        "window_ended_at": (START + timedelta(hours=24)).isoformat(),
        "captured_at": (START + timedelta(hours=24, minutes=5)).isoformat(),
        "view_count": 1000,
        "completed_view_count": 400,
    }
    with pytest.raises(ValueError, match="person-level field is forbidden"):
        parse_manual_observations(
            json.dumps({**base, "viewer_id": "person-123"}),
            "json",
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        parse_manual_observations(json.dumps({**base, "impressions": 2000}), "json")
    first = import_manual_observations(store, json.dumps(base), format="json")
    assert len(first) == 1
    regressed = {
        **base,
        "window_ended_at": (START + timedelta(hours=48)).isoformat(),
        "captured_at": (START + timedelta(hours=48, minutes=5)).isoformat(),
        "view_count": 999,
    }
    with pytest.raises(ValueError, match="view_count regressed"):
        import_manual_observations(store, json.dumps(regressed), format="json")


def test_csv_import_derives_stable_snapshot_id(tmp_path: Path) -> None:
    _, store, manifest = _experiment(tmp_path)
    variant = manifest.variants[0]
    header = (
        "experiment_id,variant_id,platform,publication_reference,window_started_at,"
        "window_ended_at,captured_at,view_count,completed_view_count\n"
    )
    row = (
        f"{manifest.experiment_id},{variant.variant_id},{manifest.platform.value},post-a,"
        f"{START.isoformat()},{(START + timedelta(hours=24)).isoformat()},"
        f"{(START + timedelta(hours=24, minutes=1)).isoformat()},800,360\n"
    )
    imported = import_manual_observations(store, header + row, format="csv")
    assert imported[0].snapshot_id.startswith("obs-")
    assert imported[0].view_count == 800


def test_conservative_analysis_and_human_approval_do_not_mutate_facts(
    tmp_path: Path,
) -> None:
    project, store, manifest = _experiment(tmp_path)
    factual_artifact = project.path("script/script.json")
    factual_artifact.write_text('{"approved":"facts"}\n', encoding="utf-8")
    before = sha256_file(factual_artifact)
    append_observations(
        store,
        [
            _observation(manifest, 0, views=2000, completed=700),
            _observation(manifest, 1, views=2000, completed=1300),
        ],  # type: ignore[list-item]
    )
    recommendation = analyze_experiment(store)
    assert recommendation.action is RecommendationAction.ADOPT_VARIANT
    assert recommendation.comparisons[0].status is ComparisonStatus.TREATMENT_LEADING
    assert recommendation.comparisons[0].control_interval is not None
    assert recommendation.comparisons[0].treatment_interval is not None
    assert recommendation.review_status is ReviewStatus.PENDING
    assert experiment_status(store).blockers == [
        "recommendation requires human approval before any production change"
    ]
    approved = approve_recommendation(
        store,
        recommendation.recommendation_id,
        "local-reviewer",
    )
    assert approved.review_status is ReviewStatus.APPROVED
    assert approved.approval_hash is not None
    assert experiment_status(store).blockers == []
    assert sha256_file(factual_artifact) == before


def test_low_sample_and_aggregate_only_metrics_never_authorize_change(
    tmp_path: Path,
) -> None:
    _, low_store, low_manifest = _experiment(tmp_path / "low", minimum_views=500)
    append_observations(
        low_store,
        [
            _observation(low_manifest, 0, views=100, completed=20),
            _observation(low_manifest, 1, views=100, completed=90),
        ],  # type: ignore[list-item]
    )
    low = analyze_experiment(low_store)
    assert low.action is RecommendationAction.COLLECT_MORE_DATA
    assert low.comparisons[0].status is ComparisonStatus.INSUFFICIENT_SAMPLE
    with pytest.raises(ValueError, match="cannot authorize"):
        approve_recommendation(low_store, low.recommendation_id, "reviewer")

    _, views_store, views_manifest = _experiment(
        tmp_path / "views",
        primary_metric=MetricName.VIEWS,
    )
    append_observations(
        views_store,
        [
            _observation(views_manifest, 0, views=1000, completed=500),
            _observation(views_manifest, 1, views=5000, completed=2500),
        ],  # type: ignore[list-item]
    )
    views = analyze_experiment(views_store)
    assert views.action is RecommendationAction.COLLECT_MORE_DATA
    assert views.comparisons[0].status is ComparisonStatus.AGGREGATE_UNCERTAINTY


def test_changed_variant_bytes_block_analysis(tmp_path: Path) -> None:
    project, store, manifest = _experiment(tmp_path)
    append_observations(
        store,
        [
            _observation(manifest, 0, views=2000, completed=700),
            _observation(manifest, 1, views=2000, completed=1300),
        ],
    )
    changed = manifest.variants[1]
    project.path(changed.media_path).write_bytes(b"changed after approval")
    with pytest.raises(ValueError, match="variant media is missing or changed"):
        analyze_experiment(store)


def test_new_snapshot_stales_prior_recommendation_and_preserves_history(
    tmp_path: Path,
) -> None:
    _, store, manifest = _experiment(tmp_path)
    first_control = _observation(manifest, 0, views=2000, completed=700)
    first_treatment = _observation(manifest, 1, views=2000, completed=1300)
    append_observations(store, [first_control, first_treatment])  # type: ignore[list-item]
    recommendation = analyze_experiment(store)
    approve_recommendation(store, recommendation.recommendation_id, "reviewer")
    later_treatment = _observation(
        manifest,
        1,
        views=3000,
        completed=1800,
        hours=48,
    )
    append_observations(store, [later_treatment])  # type: ignore[list-item]
    history = store.recommendations().recommendations
    assert len(history) == 1
    assert history[0].review_status is ReviewStatus.STALE
    assert history[0].invalidation_reason == ("new aggregate observation requires fresh analysis")
    with pytest.raises(ValueError, match="stale"):
        approve_recommendation(store, recommendation.recommendation_id, "reviewer")


def test_experiment_store_rejects_path_shaped_identifier(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="invalid format"):
        ExperimentStore(project, "../../escape")
