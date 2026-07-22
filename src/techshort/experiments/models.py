from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.domain.hashing import stable_hash
from techshort.domain.models import ReviewStatus, StrictModel, now_utc

EXPERIMENT_ID_PATTERN = re.compile(r"^exp-[0-9a-f]{16}$")
VARIANT_ID_PATTERN = re.compile(r"^var-[0-9a-f]{16}$")
SNAPSHOT_ID_PATTERN = re.compile(r"^obs-[0-9a-f]{16}$")
RECOMMENDATION_ID_PATTERN = re.compile(r"^rec-[0-9a-f]{16}$")
REVIEW_ID_PATTERN = re.compile(r"^xreview-[0-9a-f]{16}$")
SHA256_PATTERN = r"^[0-9a-f]{64}$"
SAFE_REFERENCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class ExperimentVariable(StrEnum):
    HOOK = "hook"
    COVER = "cover"
    PACING = "pacing"
    CAPTION_STYLE = "caption-style"
    AUDIO_TREATMENT = "audio-treatment"
    NARRATION_PACE = "narration-pace"


class OrganicPlatform(StrEnum):
    TIKTOK = "tiktok"
    INSTAGRAM_REELS = "instagram-reels"


class MetricName(StrEnum):
    VIEWS = "views"
    AVERAGE_WATCH_SECONDS = "average-watch-seconds"
    COMPLETION_RATE = "completion-rate"
    SKIP_RATE = "skip-rate"
    LIKE_RATE = "like-rate"
    COMMENT_RATE = "comment-rate"
    SHARE_RATE = "share-rate"
    SAVE_RATE = "save-rate"
    FOLLOW_RATE = "follow-rate"


class MetricDirection(StrEnum):
    HIGHER = "higher"
    LOWER = "lower"


class MetricStatistic(StrEnum):
    COUNT = "count"
    MEAN = "mean"
    PROPORTION = "proportion"


class VariantRole(StrEnum):
    CONTROL = "control"
    TREATMENT = "treatment"


class RecommendationAction(StrEnum):
    ADOPT_VARIANT = "adopt-variant"
    KEEP_CONTROL = "keep-control"
    COLLECT_MORE_DATA = "collect-more-data"


class ComparisonStatus(StrEnum):
    TREATMENT_LEADING = "treatment-leading"
    CONTROL_LEADING = "control-leading"
    INCONCLUSIVE = "inconclusive"
    INSUFFICIENT_SAMPLE = "insufficient-sample"
    INSUFFICIENT_DATA = "insufficient-data"
    NONCOMPARABLE_WINDOW = "noncomparable-window"
    AGGREGATE_UNCERTAINTY = "aggregate-uncertainty"


_METRIC_CONTRACTS: dict[
    MetricName,
    tuple[str, MetricDirection, MetricStatistic, str | None, bool],
] = {
    MetricName.VIEWS: (
        "Views",
        MetricDirection.HIGHER,
        MetricStatistic.COUNT,
        None,
        False,
    ),
    MetricName.AVERAGE_WATCH_SECONDS: (
        "Average watch time",
        MetricDirection.HIGHER,
        MetricStatistic.MEAN,
        "seconds",
        False,
    ),
    MetricName.COMPLETION_RATE: (
        "Completion rate",
        MetricDirection.HIGHER,
        MetricStatistic.PROPORTION,
        "completed_view_count",
        True,
    ),
    MetricName.SKIP_RATE: (
        "Skip rate",
        MetricDirection.LOWER,
        MetricStatistic.PROPORTION,
        "skipped_view_count",
        True,
    ),
    MetricName.LIKE_RATE: (
        "Likes per view",
        MetricDirection.HIGHER,
        MetricStatistic.PROPORTION,
        "like_count",
        False,
    ),
    MetricName.COMMENT_RATE: (
        "Comments per view",
        MetricDirection.HIGHER,
        MetricStatistic.PROPORTION,
        "comment_count",
        False,
    ),
    MetricName.SHARE_RATE: (
        "Shares per view",
        MetricDirection.HIGHER,
        MetricStatistic.PROPORTION,
        "share_count",
        False,
    ),
    MetricName.SAVE_RATE: (
        "Saves per view",
        MetricDirection.HIGHER,
        MetricStatistic.PROPORTION,
        "save_count",
        False,
    ),
    MetricName.FOLLOW_RATE: (
        "Follows per view",
        MetricDirection.HIGHER,
        MetricStatistic.PROPORTION,
        "follow_count",
        False,
    ),
}


class ExperimentModel(StrictModel):
    """Strict, versioned base for credential-free experiment artifacts."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class MetricDefinition(ExperimentModel):
    name: MetricName
    label: str = Field(min_length=2, max_length=80)
    direction: MetricDirection
    statistic: MetricStatistic
    numerator_field: str | None = None
    denominator_field: Literal["view_count"] | None = None
    unit: Literal["count", "seconds", "ratio"]
    supports_confidence_interval: bool

    @model_validator(mode="after")
    def matches_allowlisted_contract(self) -> MetricDefinition:
        label, direction, statistic, numerator, supports_interval = _METRIC_CONTRACTS[self.name]
        expected_unit = {
            MetricStatistic.COUNT: "count",
            MetricStatistic.MEAN: "seconds",
            MetricStatistic.PROPORTION: "ratio",
        }[statistic]
        expected_denominator = "view_count" if statistic is MetricStatistic.PROPORTION else None
        actual = (
            self.label,
            self.direction,
            self.statistic,
            self.numerator_field,
            self.denominator_field,
            self.unit,
            self.supports_confidence_interval,
        )
        expected = (
            label,
            direction,
            statistic,
            numerator,
            expected_denominator,
            expected_unit,
            supports_interval,
        )
        if actual != expected:
            raise ValueError(f"metric {self.name} does not match its organic-v1 definition")
        return self


def metric_definition(name: MetricName) -> MetricDefinition:
    label, direction, statistic, numerator, supports_interval = _METRIC_CONTRACTS[name]
    return MetricDefinition(
        name=name,
        label=label,
        direction=direction,
        statistic=statistic,
        numerator_field=numerator,
        denominator_field=("view_count" if statistic is MetricStatistic.PROPORTION else None),
        unit={
            MetricStatistic.COUNT: "count",
            MetricStatistic.MEAN: "seconds",
            MetricStatistic.PROPORTION: "ratio",
        }[statistic],
        supports_confidence_interval=supports_interval,
    )


def default_metric_definitions() -> list[MetricDefinition]:
    return [metric_definition(name) for name in MetricName]


def _safe_project_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must be project-relative and traversal-free")
    normalized = str(path)
    if not normalized or normalized == ".":
        raise ValueError("path must identify a project file")
    return normalized


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value


class Variant(ExperimentModel):
    variant_id: str
    label: str = Field(min_length=2, max_length=80)
    role: VariantRole
    variable: ExperimentVariable
    variable_value: str = Field(min_length=1, max_length=100)
    media_path: str
    media_hash: str = Field(pattern=SHA256_PATTERN)
    cover_path: str | None = None
    cover_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    locked_factual_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    claims_hash: str = Field(pattern=SHA256_PATTERN)
    limitation_hash: str = Field(pattern=SHA256_PATTERN)
    rights_hash: str = Field(pattern=SHA256_PATTERN)
    review_status: ReviewStatus = ReviewStatus.PENDING
    approval_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    approved_at: datetime | None = None
    reviewer_identifier: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("media_path", "cover_path")
    @classmethod
    def path_is_safe(cls, value: str | None) -> str | None:
        return _safe_project_path(value) if value is not None else None

    @field_validator("approved_at")
    @classmethod
    def approved_at_is_aware(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value) if value is not None else None

    @model_validator(mode="after")
    def identity_and_approval_are_current(self) -> Variant:
        expected_id = derive_variant_id(
            self.role,
            self.variable,
            self.variable_value,
            self.media_hash,
            self.cover_hash,
        )
        if self.variant_id != expected_id:
            raise ValueError("variant ID does not match its controlled content")
        if self.review_status is ReviewStatus.APPROVED:
            if self.approval_hash != variant_review_hash(self):
                raise ValueError("approved variant hash is stale or missing")
            if self.approved_at is None or self.reviewer_identifier is None:
                raise ValueError("approved variant requires reviewer and timestamp")
        elif any(
            value is not None
            for value in (self.approval_hash, self.approved_at, self.reviewer_identifier)
        ):
            raise ValueError("only approved variants may carry approval metadata")
        return self


class ExperimentManifest(ExperimentModel):
    experiment_id: str
    project_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=3, max_length=100)
    hypothesis: str = Field(min_length=12, max_length=500)
    platform: OrganicPlatform
    variable: ExperimentVariable
    primary_metric: MetricName = MetricName.COMPLETION_RATE
    metric_definitions: list[MetricDefinition] = Field(
        default_factory=default_metric_definitions,
        min_length=1,
    )
    minimum_views_per_variant: int = Field(default=500, ge=100, le=10_000_000)
    confidence_level: float = Field(default=0.95, ge=0.9, le=0.99)
    maximum_window_difference_ratio: float = Field(default=0.1, ge=0, le=0.25)
    variants: list[Variant] = Field(min_length=2, max_length=8)
    created_at: datetime = Field(default_factory=now_utc)
    review_status: ReviewStatus = ReviewStatus.PENDING
    approval_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    approved_at: datetime | None = None
    reviewer_identifier: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("created_at", "approved_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value) if value is not None else None

    @field_validator("confidence_level")
    @classmethod
    def confidence_level_is_allowlisted(cls, value: float) -> float:
        if value not in {0.9, 0.95, 0.99}:
            raise ValueError("confidence level must be 0.90, 0.95, or 0.99")
        return value

    @model_validator(mode="after")
    def is_one_variable_controlled_experiment(self) -> ExperimentManifest:
        if not EXPERIMENT_ID_PATTERN.fullmatch(self.experiment_id):
            raise ValueError("experiment ID has an invalid format")
        expected_id = derive_experiment_id(
            self.project_id,
            self.name,
            self.variable,
            self.variants[0].locked_factual_hash,
        )
        if self.experiment_id != expected_id:
            raise ValueError("experiment ID does not match its locked experiment contract")
        metric_names = [item.name for item in self.metric_definitions]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("metric definitions must be unique")
        if self.primary_metric not in metric_names:
            raise ValueError("primary metric must have a definition")
        variant_ids = [item.variant_id for item in self.variants]
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError("variant IDs must be unique")
        if sum(item.role is VariantRole.CONTROL for item in self.variants) != 1:
            raise ValueError("experiment requires exactly one control variant")
        if any(item.variable is not self.variable for item in self.variants):
            raise ValueError("all variants must change only the declared experiment variable")
        values = [item.variable_value.casefold() for item in self.variants]
        if len(values) != len(set(values)):
            raise ValueError("variant values must be distinct")
        if self.variable is ExperimentVariable.COVER:
            if any(item.cover_path is None or item.cover_hash is None for item in self.variants):
                raise ValueError("cover experiments require a cover artifact for every variant")
            if len({item.cover_hash for item in self.variants}) != len(self.variants):
                raise ValueError("cover experiments require distinct cover hashes")
            if len({item.media_hash for item in self.variants}) != 1:
                raise ValueError("cover experiments must preserve identical rendered media")
        else:
            if len({item.media_hash for item in self.variants}) != len(self.variants):
                raise ValueError("each non-cover variant must identify distinct rendered media")
            if len({item.cover_hash for item in self.variants}) != 1:
                raise ValueError("non-cover experiments must preserve the same cover")
        locked_fields = (
            "locked_factual_hash",
            "evidence_hash",
            "claims_hash",
            "limitation_hash",
            "rights_hash",
        )
        for field_name in locked_fields:
            if len({getattr(item, field_name) for item in self.variants}) != 1:
                raise ValueError(f"variants must preserve the same {field_name.replace('_', ' ')}")
        if self.review_status is ReviewStatus.APPROVED:
            if any(item.review_status is not ReviewStatus.APPROVED for item in self.variants):
                raise ValueError("approved experiments require every variant to be approved")
            if self.approval_hash != experiment_review_hash(self):
                raise ValueError("approved experiment hash is stale or missing")
            if self.approved_at is None or self.reviewer_identifier is None:
                raise ValueError("approved experiment requires reviewer and timestamp")
        elif any(
            value is not None
            for value in (self.approval_hash, self.approved_at, self.reviewer_identifier)
        ):
            raise ValueError("only approved experiments may carry approval metadata")
        return self


class ObservationSnapshot(ExperimentModel):
    snapshot_id: str
    experiment_id: str
    variant_id: str
    platform: OrganicPlatform
    source: Literal["manual-organic"] = "manual-organic"
    publication_reference: str = Field(pattern=SAFE_REFERENCE_PATTERN)
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

    @field_validator("window_started_at", "window_ended_at", "captured_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def has_ordered_window_and_stable_identity(self) -> ObservationSnapshot:
        if not EXPERIMENT_ID_PATTERN.fullmatch(self.experiment_id):
            raise ValueError("observation experiment ID has an invalid format")
        if not VARIANT_ID_PATTERN.fullmatch(self.variant_id):
            raise ValueError("observation variant ID has an invalid format")
        if self.window_ended_at <= self.window_started_at:
            raise ValueError("observation window must have positive duration")
        if self.captured_at < self.window_ended_at:
            raise ValueError("capture time cannot precede the observation window")
        for field_name in ("completed_view_count", "skipped_view_count"):
            value = getattr(self, field_name)
            if value is not None and value > self.view_count:
                raise ValueError(f"{field_name} cannot exceed view_count")
        if self.snapshot_id != derive_snapshot_id(self):
            raise ValueError("snapshot ID does not match its aggregate metrics")
        return self

    @property
    def window_seconds(self) -> float:
        return (self.window_ended_at - self.window_started_at).total_seconds()


class ObservationLog(ExperimentModel):
    experiment_id: str
    snapshots: list[ObservationSnapshot] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def snapshots_are_unique_and_scoped(self) -> ObservationLog:
        if any(item.experiment_id != self.experiment_id for item in self.snapshots):
            raise ValueError("observation belongs to a different experiment")
        ids = [item.snapshot_id for item in self.snapshots]
        if len(ids) != len(set(ids)):
            raise ValueError("observation snapshot IDs must be unique")
        return self


class ExperimentReviewDecision(ExperimentModel):
    review_id: str
    experiment_id: str
    object_type: Literal["experiment", "variant"]
    object_id: str
    object_hash: str = Field(pattern=SHA256_PATTERN)
    decision: Literal["approve", "reject"]
    reviewer_identifier: str = Field(min_length=1, max_length=80)
    timestamp: datetime = Field(default_factory=now_utc)

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def identity_matches_decision(self) -> ExperimentReviewDecision:
        expected = derive_experiment_review_id(
            self.experiment_id,
            self.object_type,
            self.object_id,
            self.object_hash,
            self.decision,
            self.reviewer_identifier,
        )
        if self.review_id != expected:
            raise ValueError("experiment review ID does not match its decision")
        return self


class ExperimentReviewLog(ExperimentModel):
    experiment_id: str
    decisions: list[ExperimentReviewDecision] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def decisions_are_unique_and_scoped(self) -> ExperimentReviewLog:
        if any(item.experiment_id != self.experiment_id for item in self.decisions):
            raise ValueError("review decision belongs to a different experiment")
        ids = [item.review_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("experiment review IDs must be unique")
        return self


class ConfidenceInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> ConfidenceInterval:
        if self.upper < self.lower:
            raise ValueError("confidence interval bounds must be ordered")
        return self


class VariantComparison(ExperimentModel):
    comparison_id: str
    control_variant_id: str
    treatment_variant_id: str
    metric: MetricName
    status: ComparisonStatus
    control_value: float | None = None
    treatment_value: float | None = None
    control_interval: ConfidenceInterval | None = None
    treatment_interval: ConfidenceInterval | None = None
    confidence_level: float = Field(ge=0.9, le=0.99)
    control_views: int = Field(ge=0)
    treatment_views: int = Field(ge=0)
    observation_ids: list[str] = Field(min_length=2, max_length=2)
    uncertainty: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def identity_matches_observations(self) -> VariantComparison:
        expected = derive_comparison_id(
            self.control_variant_id,
            self.treatment_variant_id,
            self.metric,
            self.observation_ids,
        )
        if self.comparison_id != expected:
            raise ValueError("comparison ID does not match its observation inputs")
        return self


class Recommendation(ExperimentModel):
    recommendation_id: str
    experiment_id: str
    action: RecommendationAction
    variable: ExperimentVariable
    proposed_variant_id: str | None = None
    proposed_value: str | None = Field(default=None, max_length=100)
    control_variant_id: str
    primary_metric: MetricName
    comparisons: list[VariantComparison] = Field(min_length=1, max_length=7)
    locked_factual_hash: str = Field(pattern=SHA256_PATTERN)
    generated_at: datetime = Field(default_factory=now_utc)
    summary: str = Field(min_length=12, max_length=500)
    uncertainty: list[str] = Field(min_length=1, max_length=12)
    review_status: ReviewStatus = ReviewStatus.PENDING
    approval_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    approved_at: datetime | None = None
    reviewer_identifier: str | None = Field(default=None, min_length=1, max_length=80)
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("generated_at", "approved_at", "invalidated_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value) if value is not None else None

    @model_validator(mode="after")
    def action_and_approval_are_consistent(self) -> Recommendation:
        if self.action is RecommendationAction.ADOPT_VARIANT:
            if self.proposed_variant_id is None or self.proposed_value is None:
                raise ValueError("adopt recommendation requires an existing proposed variant")
            if self.proposed_variant_id == self.control_variant_id:
                raise ValueError("adopt recommendation cannot propose the control variant")
        elif self.action is RecommendationAction.KEEP_CONTROL:
            if self.proposed_variant_id != self.control_variant_id:
                raise ValueError("keep-control recommendation must identify the control")
            if self.proposed_value is None:
                raise ValueError("keep-control recommendation requires the control value")
        elif self.proposed_variant_id is not None or self.proposed_value is not None:
            raise ValueError("collect-more-data recommendation cannot propose a change")
        if self.recommendation_id != derive_recommendation_id(self):
            raise ValueError("recommendation ID does not match its comparison inputs")
        if self.review_status is ReviewStatus.APPROVED:
            if self.action is RecommendationAction.COLLECT_MORE_DATA:
                raise ValueError("an inconclusive recommendation cannot authorize a change")
            if self.approval_hash != recommendation_review_hash(self):
                raise ValueError("approved recommendation hash is stale or missing")
            if self.approved_at is None or self.reviewer_identifier is None:
                raise ValueError("approved recommendation requires reviewer and timestamp")
        elif self.review_status is ReviewStatus.STALE:
            if self.invalidated_at is None or self.invalidation_reason is None:
                raise ValueError("stale recommendation requires an invalidation record")
            if any(
                value is not None
                for value in (self.approval_hash, self.approved_at, self.reviewer_identifier)
            ):
                raise ValueError("stale recommendations cannot retain approval metadata")
        elif any(
            value is not None
            for value in (self.approval_hash, self.approved_at, self.reviewer_identifier)
        ):
            raise ValueError("only approved recommendations may carry approval metadata")
        return self


class RecommendationLog(ExperimentModel):
    experiment_id: str
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def recommendations_are_unique_and_scoped(self) -> RecommendationLog:
        if any(item.experiment_id != self.experiment_id for item in self.recommendations):
            raise ValueError("recommendation belongs to a different experiment")
        ids = [item.recommendation_id for item in self.recommendations]
        if len(ids) != len(set(ids)):
            raise ValueError("recommendation IDs must be unique")
        return self


class ExperimentStatus(ExperimentModel):
    experiment_id: str
    approved: bool
    variant_count: int = Field(ge=2)
    observed_variant_count: int = Field(ge=0)
    latest_recommendation_id: str | None = None
    latest_action: RecommendationAction | None = None
    recommendation_approved: bool = False
    blockers: list[str] = Field(default_factory=list)


def derive_experiment_id(
    project_id: str,
    name: str,
    variable: ExperimentVariable,
    locked_factual_hash: str,
) -> str:
    return (
        "exp-"
        + stable_hash(
            {
                "project_id": project_id,
                "name": " ".join(name.casefold().split()),
                "variable": variable.value,
                "locked_factual_hash": locked_factual_hash,
            }
        )[:16]
    )


def derive_variant_id(
    role: VariantRole,
    variable: ExperimentVariable,
    variable_value: str,
    media_hash: str,
    cover_hash: str | None = None,
) -> str:
    return (
        "var-"
        + stable_hash(
            {
                "role": role.value,
                "variable": variable.value,
                "value": " ".join(variable_value.casefold().split()),
                "media_hash": media_hash,
                "cover_hash": cover_hash,
            }
        )[:16]
    )


def derive_experiment_review_id(
    experiment_id: str,
    object_type: Literal["experiment", "variant"],
    object_id: str,
    object_hash: str,
    decision: Literal["approve", "reject"],
    reviewer_identifier: str,
) -> str:
    return (
        "xreview-"
        + stable_hash(
            {
                "experiment_id": experiment_id,
                "object_type": object_type,
                "object_id": object_id,
                "object_hash": object_hash,
                "decision": decision,
                "reviewer_identifier": reviewer_identifier,
            }
        )[:16]
    )


def _variant_content(variant: Variant) -> dict[str, object]:
    return variant.model_dump(
        mode="json",
        exclude={"review_status", "approval_hash", "approved_at", "reviewer_identifier"},
    )


def variant_review_hash(variant: Variant) -> str:
    return stable_hash(_variant_content(variant))


def _experiment_content(manifest: ExperimentManifest) -> dict[str, object]:
    content = manifest.model_dump(
        mode="json",
        exclude={"review_status", "approval_hash", "approved_at", "reviewer_identifier"},
    )
    content["variants"] = [_variant_content(item) for item in manifest.variants]
    return content


def experiment_review_hash(manifest: ExperimentManifest) -> str:
    return stable_hash(_experiment_content(manifest))


def derive_snapshot_id(snapshot: ObservationSnapshot) -> str:
    return "obs-" + stable_hash(snapshot.model_dump(mode="json", exclude={"snapshot_id"}))[:16]


def derive_comparison_id(
    control_variant_id: str,
    treatment_variant_id: str,
    metric: MetricName,
    observation_ids: list[str],
) -> str:
    return (
        "cmp-"
        + stable_hash(
            {
                "control": control_variant_id,
                "treatment": treatment_variant_id,
                "metric": metric.value,
                "observations": observation_ids,
            }
        )[:16]
    )


def derive_recommendation_id(recommendation: Recommendation) -> str:
    return (
        "rec-"
        + stable_hash(
            {
                "experiment_id": recommendation.experiment_id,
                "action": recommendation.action.value,
                "variable": recommendation.variable.value,
                "proposed_variant_id": recommendation.proposed_variant_id,
                "proposed_value": recommendation.proposed_value,
                "control_variant_id": recommendation.control_variant_id,
                "primary_metric": recommendation.primary_metric.value,
                "comparison_ids": [item.comparison_id for item in recommendation.comparisons],
                "locked_factual_hash": recommendation.locked_factual_hash,
            }
        )[:16]
    )


def _recommendation_content(recommendation: Recommendation) -> dict[str, object]:
    return recommendation.model_dump(
        mode="json",
        exclude={
            "review_status",
            "approval_hash",
            "approved_at",
            "reviewer_identifier",
            "invalidated_at",
            "invalidation_reason",
        },
    )


def recommendation_review_hash(recommendation: Recommendation) -> str:
    return stable_hash(_recommendation_content(recommendation))
