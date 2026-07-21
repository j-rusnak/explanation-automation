from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from techshort.domain.hashing import sha256_file
from techshort.domain.models import ReviewStatus, now_utc
from techshort.domain.storage import ProjectStore, atomic_write_text
from techshort.experiments.models import (
    ComparisonStatus,
    ConfidenceInterval,
    ExperimentManifest,
    ExperimentReviewDecision,
    ExperimentStatus,
    ExperimentVariable,
    MetricDefinition,
    MetricDirection,
    MetricName,
    MetricStatistic,
    ObservationSnapshot,
    OrganicPlatform,
    Recommendation,
    RecommendationAction,
    Variant,
    VariantComparison,
    VariantRole,
    derive_comparison_id,
    derive_experiment_id,
    derive_experiment_review_id,
    derive_recommendation_id,
    derive_snapshot_id,
    derive_variant_id,
    experiment_review_hash,
    recommendation_review_hash,
    variant_review_hash,
)
from techshort.experiments.storage import ExperimentStore

MAX_IMPORT_BYTES = 256 * 1024
MAX_IMPORT_ROWS = 100
METRICS_TEMPLATE_GUIDANCE = (
    "Use one cumulative aggregate row per approved variant. Replace every REQUIRED_ placeholder "
    "and enter only aggregate metrics. Use the same start time and equal observation-window "
    "duration for every variant whenever possible; analysis rejects materially noncomparable "
    "windows. Never enter person-level data."
)
_SAFE_TEMPLATE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COUNT_FIELDS = (
    "view_count",
    "completed_view_count",
    "skipped_view_count",
    "like_count",
    "comment_count",
    "share_count",
    "save_count",
    "follow_count",
)
_CUMULATIVE_FIELDS = (*_COUNT_FIELDS, "total_watch_time_seconds")
_PERSON_LEVEL_FIELD_TOKENS = {
    "viewer",
    "viewer_id",
    "user",
    "user_id",
    "username",
    "handle",
    "email",
    "phone",
    "ip",
    "device_id",
    "audience_member",
}


class ObservationDraft(BaseModel):
    """Accepted manual aggregate input; stable snapshot IDs are optional on import."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    snapshot_id: str | None = None
    experiment_id: str
    variant_id: str
    platform: OrganicPlatform
    source: Literal["manual-organic"] = "manual-organic"
    publication_reference: str
    window_started_at: datetime
    window_ended_at: datetime
    captured_at: datetime
    view_count: int = Field(ge=0)
    total_watch_time_seconds: float | None = Field(default=None, ge=0)
    completed_view_count: int | None = Field(default=None, ge=0)
    skipped_view_count: int | None = Field(default=None, ge=0)
    like_count: int | None = Field(default=None, ge=0)
    comment_count: int | None = Field(default=None, ge=0)
    share_count: int | None = Field(default=None, ge=0)
    save_count: int | None = Field(default=None, ge=0)
    follow_count: int | None = Field(default=None, ge=0)


@dataclass(frozen=True)
class AggregateMetricsTemplate:
    format: Literal["json", "csv"]
    content: str
    variant_count: int
    guidance: str = METRICS_TEMPLATE_GUIDANCE


def _approved_template_manifest(experiment_store: ExperimentStore) -> ExperimentManifest:
    manifest = experiment_store.manifest()
    if manifest.review_status is not ReviewStatus.APPROVED:
        raise ValueError("experiment and variants require human approval before template export")
    if any(variant.review_status is not ReviewStatus.APPROVED for variant in manifest.variants):
        raise ValueError("every template variant requires current human approval")
    blockers = _variant_integrity_blockers(experiment_store, manifest)
    if blockers:
        raise ValueError(blockers[0])
    reviews = experiment_store.reviews().decisions
    expected = {
        ("experiment", manifest.experiment_id, manifest.approval_hash),
        *{("variant", variant.variant_id, variant.approval_hash) for variant in manifest.variants},
    }
    approved = {
        (decision.object_type, decision.object_id, decision.object_hash)
        for decision in reviews
        if decision.decision == "approve"
    }
    if not expected.issubset(approved):
        raise ValueError("experiment or variant approval record is missing or stale")
    return manifest


def build_metrics_template(
    experiment_store: ExperimentStore,
    format: Literal["json", "csv"] = "csv",
) -> AggregateMetricsTemplate:
    """Build blank aggregate-only rows for current approved experiment variants."""

    if format not in {"json", "csv"}:
        raise ValueError("metrics template format must be json or csv")
    manifest = _approved_template_manifest(experiment_store)
    fields = tuple(ObservationDraft.model_fields)
    rows: list[dict[str, object | None]] = []
    for variant in manifest.variants:
        row: dict[str, object | None] = dict.fromkeys(fields)
        row.update(
            {
                "schema_version": "1.0.0",
                "experiment_id": manifest.experiment_id,
                "variant_id": variant.variant_id,
                "platform": manifest.platform.value,
                "source": "manual-organic",
                "publication_reference": (
                    f"<REQUIRED_PUBLIC_POST_REFERENCE_FOR_{variant.variant_id}>"
                ),
                "window_started_at": "REQUIRED_COMPARABLE_WINDOW_START_UTC",
                "window_ended_at": "REQUIRED_EQUAL_DURATION_WINDOW_END_UTC",
                "captured_at": "REQUIRED_CAPTURE_TIME_UTC",
            }
        )
        rows.append(row)
    if format == "json":
        content = json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    else:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        content = output.getvalue()
    return AggregateMetricsTemplate(
        format=format,
        content=content,
        variant_count=len(rows),
    )


def write_metrics_template(
    experiment_store: ExperimentStore,
    template: AggregateMetricsTemplate,
    filename: str,
) -> Path:
    """Atomically persist a template inside the experiment without replacing differences."""

    if template.format not in {"json", "csv"}:
        raise ValueError("metrics template format must be json or csv")
    candidate = Path(filename)
    expected_suffix = f".{template.format}"
    if (
        candidate.name != filename
        or _SAFE_TEMPLATE_FILENAME.fullmatch(filename) is None
        or candidate.suffix.casefold() != expected_suffix
    ):
        raise ValueError(
            f"metrics template output must be a simple safe {expected_suffix} filename"
        )
    directory = experiment_store.root / "templates"
    if directory.is_symlink():
        raise ValueError("metrics template directory cannot be a symbolic link")
    destination = directory / filename
    if destination.is_symlink():
        raise ValueError("metrics template output cannot be a symbolic link")
    if destination.is_file():
        if destination.read_text(encoding="utf-8") != template.content:
            raise ValueError("existing metrics template differs; choose a new output filename")
        return destination
    atomic_write_text(destination, template.content)
    return destination


def build_variant(
    *,
    label: str,
    role: VariantRole,
    variable: ExperimentVariable,
    variable_value: str,
    media_path: str,
    media_hash: str,
    cover_path: str | None = None,
    cover_hash: str | None = None,
    locked_factual_hash: str,
    evidence_hash: str,
    claims_hash: str,
    limitation_hash: str,
    rights_hash: str,
) -> Variant:
    return Variant(
        variant_id=derive_variant_id(
            role,
            variable,
            variable_value,
            media_hash,
            cover_hash,
        ),
        label=label,
        role=role,
        variable=variable,
        variable_value=variable_value,
        media_path=media_path,
        media_hash=media_hash,
        cover_path=cover_path,
        cover_hash=cover_hash,
        locked_factual_hash=locked_factual_hash,
        evidence_hash=evidence_hash,
        claims_hash=claims_hash,
        limitation_hash=limitation_hash,
        rights_hash=rights_hash,
    )


def initialize_experiment(
    project_store: ProjectStore,
    *,
    name: str,
    hypothesis: str,
    platform: OrganicPlatform,
    variable: ExperimentVariable,
    variants: list[Variant],
    primary_metric: MetricName = MetricName.COMPLETION_RATE,
    minimum_views_per_variant: int = 500,
    confidence_level: float = 0.95,
) -> ExperimentManifest:
    if not project_store.manifest_path.is_file():
        raise ValueError("project must be initialized before creating an experiment")
    if not variants:
        raise ValueError("experiment requires controlled variants")
    project = project_store.project()
    for variant in variants:
        media = project_store.path(variant.media_path)
        if not media.is_file():
            raise ValueError(f"variant media is missing: {variant.media_path}")
        if sha256_file(media) != variant.media_hash:
            raise ValueError(f"variant media hash is stale: {variant.variant_id}")
        if variant.cover_path is not None:
            cover = project_store.path(variant.cover_path)
            if not cover.is_file():
                raise ValueError(f"variant cover is missing: {variant.cover_path}")
            if sha256_file(cover) != variant.cover_hash:
                raise ValueError(f"variant cover hash is stale: {variant.variant_id}")
    experiment_id = derive_experiment_id(
        project.project_id,
        name,
        variable,
        variants[0].locked_factual_hash,
    )
    manifest = ExperimentManifest(
        experiment_id=experiment_id,
        project_id=project.project_id,
        name=name,
        hypothesis=hypothesis,
        platform=platform,
        variable=variable,
        variants=variants,
        primary_metric=primary_metric,
        minimum_views_per_variant=minimum_views_per_variant,
        confidence_level=confidence_level,
    )
    return ExperimentStore(project_store, experiment_id).initialize(manifest)


def approve_experiment(
    experiment_store: ExperimentStore,
    reviewer_identifier: str,
) -> ExperimentManifest:
    manifest = experiment_store.manifest()
    integrity_blockers = _variant_integrity_blockers(experiment_store, manifest)
    if integrity_blockers:
        raise ValueError(integrity_blockers[0])
    if manifest.review_status is ReviewStatus.APPROVED:
        return manifest
    approved_at = now_utc()
    approved_variants: list[Variant] = []
    for variant in manifest.variants:
        data = variant.model_dump()
        data.update(
            review_status=ReviewStatus.APPROVED,
            approval_hash=variant_review_hash(variant),
            approved_at=approved_at,
            reviewer_identifier=reviewer_identifier,
        )
        approved_variants.append(Variant.model_validate(data))
    manifest_data = manifest.model_dump()
    manifest_data["variants"] = approved_variants
    manifest_data.update(
        review_status=ReviewStatus.APPROVED,
        approval_hash=experiment_review_hash(manifest),
        approved_at=approved_at,
        reviewer_identifier=reviewer_identifier,
    )
    approved = ExperimentManifest.model_validate(manifest_data)
    reviews = experiment_store.reviews()
    decisions = [
        ExperimentReviewDecision(
            review_id=derive_experiment_review_id(
                manifest.experiment_id,
                "variant",
                variant.variant_id,
                variant.approval_hash or "",
                "approve",
                reviewer_identifier,
            ),
            experiment_id=manifest.experiment_id,
            object_type="variant",
            object_id=variant.variant_id,
            object_hash=variant.approval_hash or "",
            decision="approve",
            reviewer_identifier=reviewer_identifier,
            timestamp=approved_at,
        )
        for variant in approved_variants
    ]
    decisions.append(
        ExperimentReviewDecision(
            review_id=derive_experiment_review_id(
                manifest.experiment_id,
                "experiment",
                manifest.experiment_id,
                approved.approval_hash or "",
                "approve",
                reviewer_identifier,
            ),
            experiment_id=manifest.experiment_id,
            object_type="experiment",
            object_id=manifest.experiment_id,
            object_hash=approved.approval_hash or "",
            decision="approve",
            reviewer_identifier=reviewer_identifier,
            timestamp=approved_at,
        )
    )
    known_review_ids = {item.review_id for item in reviews.decisions}
    reviews.decisions.extend(item for item in decisions if item.review_id not in known_review_ids)
    experiment_store.save_reviews(reviews)
    experiment_store.save_manifest(approved)
    return approved


def build_observation(**values: Any) -> ObservationSnapshot:
    draft = ObservationDraft.model_validate(values)
    supplied_id = draft.snapshot_id
    payload = draft.model_dump(exclude={"snapshot_id"})
    provisional = ObservationSnapshot.model_construct(snapshot_id="", **payload)
    snapshot_id = derive_snapshot_id(provisional)
    if supplied_id is not None and supplied_id != snapshot_id:
        raise ValueError("supplied snapshot ID does not match aggregate metrics")
    return ObservationSnapshot.model_validate({"snapshot_id": snapshot_id, **payload})


def _validate_person_level_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _PERSON_LEVEL_FIELD_TOKENS:
                raise ValueError(f"person-level field is forbidden: {key}")
            _validate_person_level_keys(child)
    elif isinstance(value, list):
        for child in value:
            _validate_person_level_keys(child)


def parse_manual_observations(
    payload: str, format: Literal["json", "csv"]
) -> list[ObservationSnapshot]:
    if len(payload.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("manual metrics import exceeds the 256 KiB limit")
    if format == "json":
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"manual metrics JSON is malformed: {exc.msg}") from exc
        _validate_person_level_keys(parsed)
        rows = parsed if isinstance(parsed, list) else [parsed]
        if not all(isinstance(item, dict) for item in rows):
            raise ValueError("manual metrics JSON must be an object or list of objects")
    elif format == "csv":
        reader = csv.DictReader(io.StringIO(payload))
        if reader.fieldnames is None:
            raise ValueError("manual metrics CSV requires a header row")
        _validate_person_level_keys({field: None for field in reader.fieldnames})
        allowed = set(ObservationDraft.model_fields)
        unknown = set(reader.fieldnames) - allowed
        if unknown:
            raise ValueError(f"manual metrics CSV has unknown field: {sorted(unknown)[0]}")
        rows = [
            {key: value for key, value in row.items() if value not in (None, "")} for row in reader
        ]
    else:
        raise ValueError("manual metrics format must be json or csv")
    if not rows:
        raise ValueError("manual metrics import contains no observations")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"manual metrics import is limited to {MAX_IMPORT_ROWS} rows")
    return [build_observation(**row) for row in rows]


def import_manual_observations(
    experiment_store: ExperimentStore,
    source: Path | str,
    *,
    format: Literal["json", "csv"] | None = None,
) -> list[ObservationSnapshot]:
    if isinstance(source, Path):
        if not source.is_file():
            raise ValueError("manual metrics file does not exist")
        if source.stat().st_size > MAX_IMPORT_BYTES:
            raise ValueError("manual metrics import exceeds the 256 KiB limit")
        selected_format = format or source.suffix.casefold().lstrip(".")
        if selected_format not in {"json", "csv"}:
            raise ValueError("manual metrics file must use .json or .csv")
        payload = source.read_text(encoding="utf-8")
        parsed = parse_manual_observations(payload, selected_format)  # type: ignore[arg-type]
    else:
        if format is None:
            raise ValueError("in-memory manual metrics require an explicit format")
        parsed = parse_manual_observations(source, format)
    return append_observations(experiment_store, parsed)


def _validate_observation_sequence(snapshots: list[ObservationSnapshot]) -> None:
    by_variant: dict[str, list[ObservationSnapshot]] = {}
    for snapshot in snapshots:
        by_variant.setdefault(snapshot.variant_id, []).append(snapshot)
    for variant_id, variant_snapshots in by_variant.items():
        ordered = sorted(variant_snapshots, key=lambda item: item.window_ended_at)
        references = {item.publication_reference for item in ordered}
        starts = {item.window_started_at for item in ordered}
        if len(references) != 1 or len(starts) != 1:
            raise ValueError(
                f"variant {variant_id} observations must describe one cumulative organic post"
            )
        window_ends = [item.window_ended_at for item in ordered]
        if len(window_ends) != len(set(window_ends)):
            raise ValueError(f"variant {variant_id} has duplicate observation windows")
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            for field_name in _CUMULATIVE_FIELDS:
                earlier_value = getattr(earlier, field_name)
                later_value = getattr(later, field_name)
                if (
                    earlier_value is not None
                    and later_value is not None
                    and later_value < earlier_value
                ):
                    raise ValueError(f"cumulative {field_name} regressed for variant {variant_id}")


def append_observations(
    experiment_store: ExperimentStore,
    snapshots: list[ObservationSnapshot],
) -> list[ObservationSnapshot]:
    manifest = experiment_store.manifest()
    if manifest.review_status is not ReviewStatus.APPROVED:
        raise ValueError("experiment and variants require human approval before metrics import")
    variants = {item.variant_id: item for item in manifest.variants}
    for snapshot in snapshots:
        variant = variants.get(snapshot.variant_id)
        if variant is None:
            raise ValueError(f"observation references unknown variant: {snapshot.variant_id}")
        if variant.review_status is not ReviewStatus.APPROVED:
            raise ValueError(f"variant is not approved: {snapshot.variant_id}")
        if snapshot.experiment_id != manifest.experiment_id:
            raise ValueError("observation belongs to a different experiment")
        if snapshot.platform is not manifest.platform:
            raise ValueError("observation platform does not match the experiment")
    log = experiment_store.observations()
    existing_ids = {item.snapshot_id for item in log.snapshots}
    additions = [item for item in snapshots if item.snapshot_id not in existing_ids]
    combined = [*log.snapshots, *additions]
    _validate_observation_sequence(combined)
    if not additions:
        return snapshots
    recommendation_log = experiment_store.recommendations()
    invalidated_at = now_utc()
    invalidated: list[Recommendation] = []
    for recommendation in recommendation_log.recommendations:
        if recommendation.review_status is ReviewStatus.STALE:
            invalidated.append(recommendation)
            continue
        data = recommendation.model_dump()
        data.update(
            review_status=ReviewStatus.STALE,
            approval_hash=None,
            approved_at=None,
            reviewer_identifier=None,
            invalidated_at=invalidated_at,
            invalidation_reason="new aggregate observation requires fresh analysis",
        )
        invalidated.append(Recommendation.model_validate(data))
    recommendation_log.recommendations = invalidated
    experiment_store.save_recommendations(recommendation_log)
    log.snapshots = combined
    experiment_store.save_observations(log)
    return additions


def _latest_observations(
    experiment_store: ExperimentStore,
) -> dict[str, ObservationSnapshot]:
    latest: dict[str, ObservationSnapshot] = {}
    for snapshot in experiment_store.observations().snapshots:
        current = latest.get(snapshot.variant_id)
        if current is None or snapshot.window_ended_at > current.window_ended_at:
            latest[snapshot.variant_id] = snapshot
    return latest


def _metric_value(
    snapshot: ObservationSnapshot,
    definition: MetricDefinition,
) -> float | None:
    if definition.name is MetricName.VIEWS:
        return float(snapshot.view_count)
    if definition.name is MetricName.AVERAGE_WATCH_SECONDS:
        if snapshot.total_watch_time_seconds is None or snapshot.view_count == 0:
            return None
        return snapshot.total_watch_time_seconds / snapshot.view_count
    if definition.numerator_field is None or snapshot.view_count == 0:
        return None
    numerator = getattr(snapshot, definition.numerator_field)
    if numerator is None:
        return None
    return float(numerator) / snapshot.view_count


def _wilson_interval(successes: int, total: int, confidence: float) -> ConfidenceInterval:
    if total <= 0:
        raise ValueError("Wilson interval requires a positive denominator")
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return ConfidenceInterval(lower=max(0, center - margin), upper=min(1, center + margin))


def _compare_variant(
    manifest: ExperimentManifest,
    definition: MetricDefinition,
    control: Variant,
    treatment: Variant,
    control_observation: ObservationSnapshot,
    treatment_observation: ObservationSnapshot,
) -> VariantComparison:
    observation_ids = [control_observation.snapshot_id, treatment_observation.snapshot_id]
    comparison_id = derive_comparison_id(
        control.variant_id,
        treatment.variant_id,
        definition.name,
        observation_ids,
    )
    base: dict[str, Any] = {
        "comparison_id": comparison_id,
        "control_variant_id": control.variant_id,
        "treatment_variant_id": treatment.variant_id,
        "metric": definition.name,
        "confidence_level": manifest.confidence_level,
        "control_views": control_observation.view_count,
        "treatment_views": treatment_observation.view_count,
        "observation_ids": observation_ids,
    }
    duration_max = max(control_observation.window_seconds, treatment_observation.window_seconds)
    duration_difference = abs(
        control_observation.window_seconds - treatment_observation.window_seconds
    )
    if duration_difference / duration_max > manifest.maximum_window_difference_ratio:
        return VariantComparison(
            **base,
            status=ComparisonStatus.NONCOMPARABLE_WINDOW,
            uncertainty=[
                "Observation windows differ beyond the configured tolerance; compare equal-age posts."
            ],
        )
    control_value = _metric_value(control_observation, definition)
    treatment_value = _metric_value(treatment_observation, definition)
    base.update(control_value=control_value, treatment_value=treatment_value)
    if control_value is None or treatment_value is None:
        return VariantComparison(
            **base,
            status=ComparisonStatus.INSUFFICIENT_DATA,
            uncertainty=["The primary metric is missing from one or more aggregate snapshots."],
        )
    if min(control_observation.view_count, treatment_observation.view_count) < (
        manifest.minimum_views_per_variant
    ):
        return VariantComparison(
            **base,
            status=ComparisonStatus.INSUFFICIENT_SAMPLE,
            uncertainty=[
                f"Each variant needs at least {manifest.minimum_views_per_variant} views before comparison."
            ],
        )
    if not definition.supports_confidence_interval:
        return VariantComparison(
            **base,
            status=ComparisonStatus.AGGREGATE_UNCERTAINTY,
            uncertainty=[
                "Aggregate totals do not include the variance or independent-event assumptions needed for a defensible confidence interval."
            ],
        )
    if definition.statistic is not MetricStatistic.PROPORTION:
        raise ValueError("confidence-enabled organic metric must be a proportion")
    assert definition.numerator_field is not None
    control_successes = getattr(control_observation, definition.numerator_field)
    treatment_successes = getattr(treatment_observation, definition.numerator_field)
    if control_successes is None or treatment_successes is None:
        raise ValueError("proportion numerator disappeared during comparison")
    control_interval = _wilson_interval(
        control_successes,
        control_observation.view_count,
        manifest.confidence_level,
    )
    treatment_interval = _wilson_interval(
        treatment_successes,
        treatment_observation.view_count,
        manifest.confidence_level,
    )
    if definition.direction is MetricDirection.HIGHER:
        treatment_wins = treatment_interval.lower > control_interval.upper
        control_wins = control_interval.lower > treatment_interval.upper
    else:
        treatment_wins = treatment_interval.upper < control_interval.lower
        control_wins = control_interval.upper < treatment_interval.lower
    status = (
        ComparisonStatus.TREATMENT_LEADING
        if treatment_wins
        else ComparisonStatus.CONTROL_LEADING
        if control_wins
        else ComparisonStatus.INCONCLUSIVE
    )
    return VariantComparison(
        **base,
        status=status,
        control_interval=control_interval,
        treatment_interval=treatment_interval,
        uncertainty=[
            f"{manifest.confidence_level:.0%} Wilson intervals account for sampling error only; organic distribution, timing, and audience mix remain uncontrolled."
        ],
    )


def analyze_experiment(experiment_store: ExperimentStore) -> Recommendation:
    manifest = experiment_store.manifest()
    if manifest.review_status is not ReviewStatus.APPROVED:
        raise ValueError("experiment requires human approval before analysis")
    integrity_blockers = _variant_integrity_blockers(experiment_store, manifest)
    if integrity_blockers:
        raise ValueError(integrity_blockers[0])
    latest = _latest_observations(experiment_store)
    missing = [item.variant_id for item in manifest.variants if item.variant_id not in latest]
    if missing:
        raise ValueError(f"latest aggregate observation is missing for variant: {missing[0]}")
    definitions = {item.name: item for item in manifest.metric_definitions}
    definition = definitions[manifest.primary_metric]
    control = next(item for item in manifest.variants if item.role is VariantRole.CONTROL)
    treatments = [item for item in manifest.variants if item.role is VariantRole.TREATMENT]
    comparisons = [
        _compare_variant(
            manifest,
            definition,
            control,
            treatment,
            latest[control.variant_id],
            latest[treatment.variant_id],
        )
        for treatment in treatments
    ]
    leading = [item for item in comparisons if item.status is ComparisonStatus.TREATMENT_LEADING]
    if len(leading) == 1 and all(
        item.status in {ComparisonStatus.TREATMENT_LEADING, ComparisonStatus.CONTROL_LEADING}
        for item in comparisons
    ):
        selected = next(
            item for item in treatments if item.variant_id == leading[0].treatment_variant_id
        )
        action = RecommendationAction.ADOPT_VARIANT
        proposed_variant_id = selected.variant_id
        proposed_value = selected.variable_value
        summary = (
            f"Adopt the reviewed {manifest.variable.value} variant '{selected.label}'; "
            "its conservative interval clears the control."
        )
    elif all(item.status is ComparisonStatus.CONTROL_LEADING for item in comparisons):
        action = RecommendationAction.KEEP_CONTROL
        proposed_variant_id = control.variant_id
        proposed_value = control.variable_value
        summary = (
            f"Keep the reviewed control {manifest.variable.value}; every treatment's "
            "conservative interval trails it."
        )
    else:
        action = RecommendationAction.COLLECT_MORE_DATA
        proposed_variant_id = None
        proposed_value = None
        summary = (
            "Do not change the production default yet; the aggregate organic observations "
            "do not establish one defensible winner."
        )
    uncertainty = sorted({message for item in comparisons for message in item.uncertainty})
    data: dict[str, Any] = {
        "recommendation_id": "",
        "experiment_id": manifest.experiment_id,
        "action": action,
        "variable": manifest.variable,
        "proposed_variant_id": proposed_variant_id,
        "proposed_value": proposed_value,
        "control_variant_id": control.variant_id,
        "primary_metric": manifest.primary_metric,
        "comparisons": comparisons,
        "locked_factual_hash": control.locked_factual_hash,
        "summary": summary,
        "uncertainty": uncertainty,
    }
    provisional = Recommendation.model_construct(**data)
    data["recommendation_id"] = derive_recommendation_id(provisional)
    recommendation = Recommendation.model_validate(data)
    log = experiment_store.recommendations()
    existing = next(
        (
            item
            for item in log.recommendations
            if item.recommendation_id == recommendation.recommendation_id
        ),
        None,
    )
    if existing is not None:
        return existing
    log.recommendations.append(recommendation)
    experiment_store.save_recommendations(log)
    return recommendation


def approve_recommendation(
    experiment_store: ExperimentStore,
    recommendation_id: str,
    reviewer_identifier: str,
) -> Recommendation:
    manifest = experiment_store.manifest()
    if manifest.review_status is not ReviewStatus.APPROVED:
        raise ValueError("experiment approval is stale")
    integrity_blockers = _variant_integrity_blockers(experiment_store, manifest)
    if integrity_blockers:
        raise ValueError(integrity_blockers[0])
    log = experiment_store.recommendations()
    index = next(
        (
            position
            for position, item in enumerate(log.recommendations)
            if item.recommendation_id == recommendation_id
        ),
        None,
    )
    if index is None:
        raise ValueError("recommendation does not exist")
    recommendation = log.recommendations[index]
    if recommendation.review_status is ReviewStatus.APPROVED:
        return recommendation
    if recommendation.review_status is ReviewStatus.STALE:
        raise ValueError("recommendation is stale; run fresh analysis")
    if recommendation.action is RecommendationAction.COLLECT_MORE_DATA:
        raise ValueError("inconclusive results cannot authorize a production change")
    variants = {item.variant_id: item for item in manifest.variants}
    proposed = variants.get(recommendation.proposed_variant_id or "")
    if proposed is None or proposed.review_status is not ReviewStatus.APPROVED:
        raise ValueError("recommendation does not reference a current approved variant")
    if proposed.locked_factual_hash != recommendation.locked_factual_hash:
        raise ValueError("recommendation would cross a factual-artifact boundary")
    latest_ids = {item.snapshot_id for item in _latest_observations(experiment_store).values()}
    analyzed_ids = {
        observation_id
        for comparison in recommendation.comparisons
        for observation_id in comparison.observation_ids
    }
    if analyzed_ids != latest_ids:
        raise ValueError("recommendation does not use the latest aggregate observations")
    data = recommendation.model_dump()
    data.update(
        review_status=ReviewStatus.APPROVED,
        approval_hash=recommendation_review_hash(recommendation),
        approved_at=now_utc(),
        reviewer_identifier=reviewer_identifier,
    )
    approved = Recommendation.model_validate(data)
    log.recommendations[index] = approved
    experiment_store.save_recommendations(log)
    return approved


def _variant_integrity_blockers(
    experiment_store: ExperimentStore,
    manifest: ExperimentManifest,
) -> list[str]:
    blockers: list[str] = []
    for variant in manifest.variants:
        media = experiment_store.project_store.path(variant.media_path)
        if not media.is_file() or sha256_file(media) != variant.media_hash:
            blockers.append(f"variant media is missing or changed: {variant.variant_id}")
        if variant.cover_path is not None:
            cover = experiment_store.project_store.path(variant.cover_path)
            if not cover.is_file() or sha256_file(cover) != variant.cover_hash:
                blockers.append(f"variant cover is missing or changed: {variant.variant_id}")
    return blockers


def experiment_status(experiment_store: ExperimentStore) -> ExperimentStatus:
    manifest = experiment_store.manifest()
    latest = _latest_observations(experiment_store)
    recommendations = experiment_store.recommendations().recommendations
    recommendation = recommendations[-1] if recommendations else None
    blockers: list[str] = []
    if manifest.review_status is not ReviewStatus.APPROVED:
        blockers.append("experiment variants require human approval")
    blockers.extend(_variant_integrity_blockers(experiment_store, manifest))
    missing = [item.variant_id for item in manifest.variants if item.variant_id not in latest]
    if missing:
        blockers.append(f"aggregate observations missing for {len(missing)} variant(s)")
    if recommendation is None:
        blockers.append("experiment has not been analyzed")
    elif recommendation.action is RecommendationAction.COLLECT_MORE_DATA:
        blockers.append("results are inconclusive; collect comparable aggregate observations")
    elif recommendation.review_status is not ReviewStatus.APPROVED:
        blockers.append("recommendation requires human approval before any production change")
    return ExperimentStatus(
        experiment_id=manifest.experiment_id,
        approved=manifest.review_status is ReviewStatus.APPROVED,
        variant_count=len(manifest.variants),
        observed_variant_count=len(latest),
        latest_recommendation_id=(
            recommendation.recommendation_id if recommendation is not None else None
        ),
        latest_action=recommendation.action if recommendation is not None else None,
        recommendation_approved=(
            recommendation is not None and recommendation.review_status is ReviewStatus.APPROVED
        ),
        blockers=blockers,
    )
