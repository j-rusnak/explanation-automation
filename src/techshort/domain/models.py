from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.domain.hashing import stable_hash

SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
PacingProfile = Literal["measured", "brisk", "high-retention"]

_ACTIVE_CONTENT_PATTERNS = (
    re.compile(r"<\s*/?\s*[a-z!][^>]*>", re.IGNORECASE),
    re.compile(r"\b(?:java|vb)script\s*:", re.IGNORECASE),
    re.compile(r"\bdata\s*:\s*(?:text/html|image/svg\+xml)", re.IGNORECASE),
    re.compile(r"\bon[a-z]{3,}\s*=", re.IGNORECASE),
    re.compile(r"\b(?:eval|exec|__import__)\s*\(", re.IGNORECASE),
    re.compile(r"\bnew\s+function\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:document|window)\s*\.\s*(?:write|location|cookie)\b", re.IGNORECASE),
    re.compile(
        r"(?:^|[\r\n;])\s*(?:#!|powershell(?:\.exe)?\b|cmd(?:\.exe)?\s+/c\b|"
        r"(?:ba|z|k)?sh\s+-c\b)",
        re.IGNORECASE,
    ),
)


def validate_inert_text(value: str) -> str:
    """Reject active markup and obvious executable payloads in rendered scene data."""
    if "\x00" in value:
        raise ValueError("NUL bytes are forbidden in scene text")
    if any(pattern.search(value) for pattern in _ACTIVE_CONTENT_PATTERNS):
        raise ValueError("active content or executable markup is forbidden")
    return value


def now_utc() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION


class SafeZoneInsets(BaseModel):
    """Resolution-independent insets for shared TikTok/Reels-safe content."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)
    top: float = Field(default=0.06, ge=0, le=0.25)
    right: float = Field(default=0.14, ge=0, le=0.25)
    bottom: float = Field(default=0.17, ge=0, le=0.25)
    left: float = Field(default=0.067, ge=0, le=0.25)

    @model_validator(mode="after")
    def leaves_a_useful_content_area(self) -> SafeZoneInsets:
        if self.left + self.right > 0.4 or self.top + self.bottom > 0.4:
            raise ValueError("safe-zone insets leave too little usable content area")
        return self


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STALE = "stale"


class ApprovalState(StrictModel):
    claims: ReviewStatus = ReviewStatus.PENDING
    script: ReviewStatus = ReviewStatus.PENDING
    storyboard: ReviewStatus = ReviewStatus.PENDING
    rights: ReviewStatus = ReviewStatus.PENDING
    final: ReviewStatus = ReviewStatus.PENDING


class ProjectManifest(StrictModel):
    project_id: str
    slug: str
    title: str
    status: str = "draft"
    created_at: datetime = Field(default_factory=now_utc)
    modified_at: datetime = Field(default_factory=now_utc)
    target_duration_seconds: float = 60
    width: int = 1080
    height: int = 1920
    fps: int = 30
    theme: Literal["midnight", "blueprint", "signal-lab", "technical-editorial"] = "blueprint"
    pacing: PacingProfile = "high-retention"
    safe_zone: SafeZoneInsets = Field(default_factory=SafeZoneInsets)
    narration_mode: Literal["narrated", "silent-reviewed"] = "narrated"
    source_ids: list[str] = Field(default_factory=list)
    active_source_id: str | None = None
    active_versions: dict[str, str] = Field(default_factory=dict)
    approvals: ApprovalState = Field(default_factory=ApprovalState)
    content_risk: Literal["low", "review", "prohibited"] = "low"
    dependency_hashes: dict[str, str] = Field(default_factory=dict)
    downstream_valid: bool = False
    stale_artifacts: list[str] = Field(default_factory=list)


class SourceDocument(StrictModel):
    source_id: str
    source_type: Literal["pdf", "markdown", "text"]
    original_filename: str
    content_hash: str
    extracted_text_hash: str | None = None
    section_metadata_hash: str | None = None
    local_path: str
    ingested_at: datetime = Field(default_factory=now_utc)
    page_or_section_count: int
    title: str
    metadata: dict[str, str] = Field(default_factory=dict)
    rights_status: str = "unknown"
    extraction_warnings: list[str] = Field(default_factory=list)
    appears_incomplete: bool = False
    ocr_required: bool = False

    @field_validator("local_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("path must be project-relative and traversal-free")
        return str(path)


class SourceIndex(StrictModel):
    sources: list[SourceDocument]
    active_source_id: str | None = None

    @model_validator(mode="after")
    def active_source_exists(self) -> SourceIndex:
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source IDs must be unique")
        if self.active_source_id is not None and self.active_source_id not in source_ids:
            raise ValueError("active source ID is not present in the source index")
        return self


class EvidenceSpan(StrictModel):
    evidence_id: str
    source_id: str
    page_index: int | None = None
    printed_page_label: str | None = None
    section_heading: str | None = None
    char_start: int
    char_end: int
    bounding_box: tuple[float, float, float, float] | None = None
    excerpt: str = Field(min_length=1, max_length=600)
    context: str = Field(max_length=1200)
    source_hash: str
    extraction_confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)
    locator: str

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> EvidenceSpan:
        if self.char_end <= self.char_start:
            raise ValueError("evidence offsets must be ordered")
        return self


class EvidenceManifest(StrictModel):
    version_id: str
    evidence: list[EvidenceSpan]


class Claim(StrictModel):
    claim_id: str
    text: str
    evidence_span_ids: list[str] = Field(min_length=1)
    relationship: Literal["direct", "inferred", "synthesis"]
    evidence_label: Literal["documented", "measured", "simulated", "inferred"]
    reasoning: str | None = None
    scope: str | None = None
    limitation: str | None = None
    confidence: float = Field(ge=0, le=1)
    risk: Literal["low", "medium", "high"] = "low"
    review_status: ReviewStatus = ReviewStatus.PENDING
    reviewer_edits: str | None = None
    approval_timestamp: datetime | None = None
    approval_hash: str | None = None

    @model_validator(mode="after")
    def inferred_needs_reasoning(self) -> Claim:
        if self.relationship != "direct" and not self.reasoning:
            raise ValueError("inferred and synthesis claims require reasoning")
        return self


class ClaimsManifest(StrictModel):
    version_id: str
    evidence_version_id: str
    claims: list[Claim]


class ClaimCritiqueIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    claim_id: str
    category: Literal[
        "unsupported",
        "partial-support",
        "missing-scope",
        "causal-wording",
        "uncertainty",
        "number-or-unit",
        "conflicting-evidence",
    ]
    severity: Literal["warning", "error"]
    message: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list)


class ClaimCritiqueReport(StrictModel):
    version_id: str
    claims_version_id: str
    provider: Literal["fixture", "manual", "codex"]
    summary: str = Field(min_length=1, max_length=1200)
    issues: list[ClaimCritiqueIssue] = Field(default_factory=list)


AngleKind = Literal["surprising-result", "everyday-mechanism", "engineering-tradeoff"]


class AngleCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    angle: AngleKind
    title: str = Field(min_length=3, max_length=120)
    rationale: str = Field(min_length=12, max_length=800)
    central_claim_ids: list[str] = Field(min_length=1, max_length=8)

    @field_validator("central_claim_ids")
    @classmethod
    def central_claims_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("angle central claim IDs must be unique")
        return value


class AnglesManifest(StrictModel):
    version_id: str
    claims_version_id: str
    candidates: list[AngleCandidate] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def contains_each_required_angle_once(self) -> AnglesManifest:
        expected = {
            "surprising-result",
            "everyday-mechanism",
            "engineering-tradeoff",
        }
        actual = {candidate.angle for candidate in self.candidates}
        if len(actual) != len(self.candidates) or actual != expected:
            raise ValueError("angles must contain each required candidate exactly once")
        substance = {
            (
                " ".join(candidate.title.casefold().split()),
                " ".join(candidate.rationale.casefold().split()),
                tuple(sorted(candidate.central_claim_ids)),
            )
            for candidate in self.candidates
        }
        if len(substance) != len(self.candidates):
            raise ValueError("angle candidates must have distinct substantive content")
        return self


class AngleSelection(StrictModel):
    selection_id: str
    angles_version_id: str
    selected_angle: AngleKind
    selected_candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def identity_matches_selected_candidate(self) -> AngleSelection:
        expected = derive_angle_selection_id(
            self.angles_version_id,
            self.selected_angle,
            self.selected_candidate_hash,
        )
        if self.selection_id != expected:
            raise ValueError("angle selection ID does not match its selected candidate")
        return self


class ScriptSegment(StrictModel):
    segment_id: str
    text: str
    segment_type: Literal["factual", "hook", "transition", "analogy", "caveat", "limitation", "cta"]
    claim_ids: list[str] = Field(default_factory=list)
    approximate_duration: float = Field(gt=0)
    pronunciation_notes: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    approval_hash: str | None = None

    @model_validator(mode="after")
    def every_segment_requires_claims(self) -> ScriptSegment:
        # Requiring a contextual claim even for transitions and CTAs closes a
        # deterministic misclassification loophole: factual prose cannot be made
        # citation-free merely by labelling it as a transition or CTA.
        if not self.claim_ids:
            raise ValueError(f"{self.segment_type} segment requires at least one claim")
        return self


class ScriptManifest(StrictModel):
    version_id: str
    claims_version_id: str
    angles_version_id: str
    angle_selection_id: str
    angle: AngleKind
    segments: list[ScriptSegment]

    @model_validator(mode="after")
    def limitation_required(self) -> ScriptManifest:
        if not any(s.segment_type == "limitation" for s in self.segments):
            raise ValueError("script requires a meaningful limitation segment")
        return self


def derive_angles_version_id(claims_version_id: str, candidates: list[AngleCandidate]) -> str:
    return "angles-" + stable_hash({"claims": claims_version_id, "candidates": candidates})[:16]


def derive_angle_selection_id(
    angles_version_id: str,
    selected_angle: AngleKind,
    selected_candidate_hash: str,
) -> str:
    return (
        "selection-"
        + stable_hash(
            {
                "angles": angles_version_id,
                "angle": selected_angle,
                "candidate": selected_candidate_hash,
            }
        )[:16]
    )


def derive_script_version_id(
    claims_version_id: str,
    angles_version_id: str,
    angle_selection_id: str,
    angle: AngleKind,
    segments: list[ScriptSegment],
) -> str:
    return (
        "script-"
        + stable_hash(
            {
                "claims": claims_version_id,
                "angles": angles_version_id,
                "selection": angle_selection_id,
                "angle": angle,
                "segments": segments,
            }
        )[:16]
    )


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str
    label: str
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    state: Literal["normal", "active", "muted"] = "normal"

    @field_validator("id", "label")
    @classmethod
    def inert_node_text(cls, value: str) -> str:
        return validate_inert_text(value)


class EdgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source: str
    target: str
    label: str | None = None

    @field_validator("source", "target", "label")
    @classmethod
    def inert_edge_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None


class VisualSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    title: str
    body: str | None = None
    nodes: list[NodeSpec] = Field(default_factory=list)
    edges: list[EdgeSpec] = Field(default_factory=list)
    series: list[float] = Field(default_factory=list, max_length=30)
    labels: list[str] = Field(default_factory=list, max_length=30)
    parameter: float | None = Field(default=None, ge=0, le=1)
    left: str | None = None
    right: str | None = None
    citation: str | None = None
    evidence_id: str | None = None

    @field_validator("title", "body", "left", "right", "citation", "evidence_id")
    @classmethod
    def no_executable_markup(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None

    @field_validator("labels")
    @classmethod
    def inert_labels(cls, value: list[str]) -> list[str]:
        return [validate_inert_text(item) for item in value]

    @model_validator(mode="after")
    def diagram_edges_reference_nodes(self) -> VisualSpec:
        node_ids = {node.id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("visual node IDs must be unique")
        for edge in self.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                raise ValueError("visual edges must reference declared nodes")
        return self


ThemeName = Literal["blueprint", "signal-lab", "technical-editorial"]
LayoutPreset = Literal["hero", "full-diagram", "split", "evidence", "numeric", "limitation"]
MotionPreset = Literal["calm", "precise", "energetic"]


class KineticTextVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["kinetic-text"]
    emphasis: list[str] = Field(min_length=1, max_length=4)
    supporting_text: str | None = None

    @field_validator("emphasis")
    @classmethod
    def inert_emphasis(cls, value: list[str]) -> list[str]:
        return [validate_inert_text(item) for item in value]

    @field_validator("supporting_text")
    @classmethod
    def inert_supporting_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None


class SourceReceiptVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["source-receipt"]
    source_title: str
    excerpt: str = Field(min_length=1, max_length=500)
    locator: str
    evidence_id: str
    highlight: str | None = None

    @field_validator("source_title", "excerpt", "locator", "evidence_id", "highlight")
    @classmethod
    def inert_receipt_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None


class MechanismDiagramVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["mechanism-diagram"]
    nodes: list[NodeSpec] = Field(min_length=2, max_length=12)
    edges: list[EdgeSpec] = Field(default_factory=list, max_length=18)
    active_step_id: str | None = None

    @model_validator(mode="after")
    def valid_diagram(self) -> MechanismDiagramVisual:
        node_ids = {node.id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("diagram node IDs must be unique")
        if self.active_step_id is not None and self.active_step_id not in node_ids:
            raise ValueError("active diagram step must reference a declared node")
        for edge in self.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                raise ValueError("diagram edges must reference declared nodes")
        return self


class ChartAxis(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    label: str
    unit: str | None = None

    @field_validator("label", "unit")
    @classmethod
    def inert_axis_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None


class ChartPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float
    y: float


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    label: str
    color: Literal["accent", "warning", "citation", "danger", "muted"]
    points: list[ChartPoint] = Field(min_length=1, max_length=30)

    @field_validator("label")
    @classmethod
    def inert_series_label(cls, value: str) -> str:
        return validate_inert_text(value)


class ChartAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float
    y: float
    label: str

    @field_validator("label")
    @classmethod
    def inert_annotation(cls, value: str) -> str:
        return validate_inert_text(value)


class AnnotatedChartVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["annotated-chart"]
    chart_type: Literal["bar", "line", "dot"]
    x_axis: ChartAxis
    y_axis: ChartAxis
    series: list[ChartSeries] = Field(min_length=1, max_length=4)
    annotations: list[ChartAnnotation] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def annotations_fit_series_range(self) -> AnnotatedChartVisual:
        points = [point for series in self.series for point in series.points]
        minimum_x = min(point.x for point in points)
        maximum_x = max(point.x for point in points)
        minimum_y = min(point.y for point in points)
        maximum_y = max(point.y for point in points)
        if any(
            not minimum_x <= item.x <= maximum_x or not minimum_y <= item.y <= maximum_y
            for item in self.annotations
        ):
            raise ValueError("chart annotations must fall inside the plotted data range")
        return self


class ParameterSimulationVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["parameter-simulation"]
    parameter_label: str
    unit: str | None = None
    minimum: float
    maximum: float
    value: float
    left_label: str
    right_label: str

    @field_validator("parameter_label", "unit", "left_label", "right_label")
    @classmethod
    def inert_parameter_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None

    @model_validator(mode="after")
    def parameter_is_bounded(self) -> ParameterSimulationVisual:
        if self.maximum <= self.minimum or not self.minimum <= self.value <= self.maximum:
            raise ValueError("simulation parameter must lie inside an ordered range")
        return self


ComparisonFeature = Literal["straight-edge", "grid", "rotor", "signal", "generic"]


class ComparisonSide(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    label: str
    value: str
    detail: str | None = None

    @field_validator("label", "value", "detail")
    @classmethod
    def inert_comparison_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None


class ComparisonVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["comparison"]
    feature: ComparisonFeature
    left: ComparisonSide
    right: ComparisonSide


class LimitationVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["limitation"]
    limitation: str
    applies_when: str | None = None

    @field_validator("limitation", "applies_when")
    @classmethod
    def inert_limitation_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None


ScanSubject = Literal["blade", "pole", "grid", "rotor"]


class RasterScanVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["raster-scan"]
    direction: Literal["top-to-bottom", "bottom-to-top", "left-to-right"]
    rows: int = Field(ge=6, le=32)
    subject: ScanSubject
    distortion: float = Field(ge=-1, le=1)
    scan_label: str
    before_label: str
    after_label: str

    @field_validator("scan_label", "before_label", "after_label")
    @classmethod
    def inert_scan_text(cls, value: str) -> str:
        return validate_inert_text(value)


class TimeSlice(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    time: float = Field(ge=0)
    label: str
    offset: float = Field(ge=-1, le=1)

    @field_validator("label")
    @classmethod
    def inert_time_label(cls, value: str) -> str:
        return validate_inert_text(value)


class TimeSliceVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["time-slice"]
    unit: str
    slices: list[TimeSlice] = Field(min_length=2, max_length=12)

    @field_validator("unit")
    @classmethod
    def inert_time_unit(cls, value: str) -> str:
        return validate_inert_text(value)

    @model_validator(mode="after")
    def time_slices_increase(self) -> TimeSliceVisual:
        if any(
            current.time >= following.time
            for current, following in zip(self.slices, self.slices[1:], strict=False)
        ):
            raise ValueError("time slices must have strictly increasing times")
        return self


class GridWarpVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["grid-warp"]
    rows: int = Field(ge=3, le=20)
    columns: int = Field(ge=3, le=20)
    skew: float = Field(ge=-1, le=1)
    curvature: float = Field(ge=-1, le=1)
    before_label: str
    after_label: str

    @field_validator("before_label", "after_label")
    @classmethod
    def inert_grid_labels(cls, value: str) -> str:
        return validate_inert_text(value)


class BeforeAfterOverlayVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["before-after-overlay"]
    feature: Literal["straight-edge", "grid", "rotor", "signal"]
    before_label: str
    after_label: str
    divider: float = Field(ge=0.2, le=0.8)

    @field_validator("before_label", "after_label")
    @classmethod
    def inert_overlay_labels(cls, value: str) -> str:
        return validate_inert_text(value)


class HighlightRange(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered_range(self) -> HighlightRange:
        if self.end <= self.start:
            raise ValueError("highlight offsets must be ordered")
        return self


class EvidenceHighlightVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["evidence-highlight"]
    source_title: str
    excerpt: str = Field(min_length=1, max_length=500)
    locator: str
    evidence_id: str
    highlights: list[HighlightRange] = Field(min_length=1, max_length=6)

    @field_validator("source_title", "excerpt", "locator", "evidence_id")
    @classmethod
    def inert_evidence_text(cls, value: str) -> str:
        return validate_inert_text(value)

    @model_validator(mode="after")
    def highlights_fit_excerpt(self) -> EvidenceHighlightVisual:
        if any(item.end > len(self.excerpt) for item in self.highlights):
            raise ValueError("evidence highlights must fit inside the excerpt")
        ordered = sorted(self.highlights, key=lambda item: (item.start, item.end))
        if any(
            current.end > following.start
            for current, following in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("evidence highlights may not overlap")
        return self


class ProcessFlowVisual(MechanismDiagramVisual):
    kind: Literal["process-flow"]  # type: ignore[assignment]


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    time: float
    label: str
    detail: str | None = None

    @field_validator("label", "detail")
    @classmethod
    def inert_event_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None


class TimelineVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["timeline"]
    unit: str
    events: list[TimelineEvent] = Field(min_length=2, max_length=10)

    @field_validator("unit")
    @classmethod
    def inert_timeline_unit(cls, value: str) -> str:
        return validate_inert_text(value)

    @model_validator(mode="after")
    def timeline_events_increase(self) -> TimelineVisual:
        if any(
            current.time >= following.time
            for current, following in zip(self.events, self.events[1:], strict=False)
        ):
            raise ValueError("timeline events must have strictly increasing times")
        return self


TypedVisualSpec = Annotated[
    KineticTextVisual
    | SourceReceiptVisual
    | MechanismDiagramVisual
    | AnnotatedChartVisual
    | ParameterSimulationVisual
    | ComparisonVisual
    | LimitationVisual
    | RasterScanVisual
    | TimeSliceVisual
    | GridWarpVisual
    | BeforeAfterOverlayVisual
    | EvidenceHighlightVisual
    | ProcessFlowVisual
    | TimelineVisual,
    Field(discriminator="kind"),
]


class CoverComparisonHero(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["comparison"]
    feature: Literal["straight-edge", "grid", "rotor", "signal"]
    before_label: str
    after_label: str

    @field_validator("before_label", "after_label")
    @classmethod
    def inert_cover_labels(cls, value: str) -> str:
        return validate_inert_text(value)


class CoverScanlineHero(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["scanline"]
    subject: ScanSubject
    distortion: float = Field(ge=-1, le=1)


class CoverDiagramHero(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["diagram"]
    nodes: list[NodeSpec] = Field(min_length=2, max_length=12)
    edges: list[EdgeSpec] = Field(default_factory=list, max_length=18)


CoverHero = Annotated[
    CoverComparisonHero | CoverScanlineHero | CoverDiagramHero,
    Field(discriminator="kind"),
]


class CoverCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    candidate_id: str
    headline: str = Field(min_length=3, max_length=72)
    subheadline: str | None = Field(default=None, max_length=110)
    layout: Literal["split-hero", "diagram-hero", "editorial"]
    palette: ThemeName
    hero: CoverHero
    claim_ids: list[str] = Field(min_length=1, max_length=6)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)
    accessibility_description: str

    @field_validator("candidate_id", "headline", "subheadline", "accessibility_description")
    @classmethod
    def inert_cover_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None

    @model_validator(mode="after")
    def unique_cover_links(self) -> CoverCandidate:
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("cover claim IDs must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("cover evidence IDs must be unique")
        return self


class CoverManifest(StrictModel):
    version_id: str
    storyboard_version_id: str
    candidates: list[CoverCandidate] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def unique_cover_candidates(self) -> CoverManifest:
        ids = {item.candidate_id for item in self.candidates}
        if len(ids) != len(self.candidates):
            raise ValueError("cover candidate IDs must be unique")
        return self


class CoverSelection(StrictModel):
    selection_id: str
    cover_version_id: str
    selected_candidate_id: str
    selected_candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def valid_cover_selection_id(self) -> CoverSelection:
        expected = derive_cover_selection_id(
            self.cover_version_id,
            self.selected_candidate_id,
            self.selected_candidate_hash,
        )
        if self.selection_id != expected:
            raise ValueError("cover selection ID does not match its candidate")
        return self


def derive_cover_manifest_id(storyboard_version_id: str, candidates: list[CoverCandidate]) -> str:
    return (
        "covers-"
        + stable_hash({"storyboard": storyboard_version_id, "candidates": candidates})[:16]
    )


def derive_cover_selection_id(
    cover_version_id: str,
    candidate_id: str,
    candidate_hash: str,
) -> str:
    return (
        "cover-selection-"
        + stable_hash(
            {"covers": cover_version_id, "candidate": candidate_id, "hash": candidate_hash}
        )[:16]
    )


ScenePrimitive = Literal[
    "KineticText",
    "SourceReceipt",
    "MechanismDiagram",
    "ChartReveal",
    "ParameterSimulation",
    "Comparison",
    "LimitationCard",
    "RasterScan",
    "TimeSlice",
    "GridWarp",
    "BeforeAfterOverlay",
    "AnnotatedChart",
    "EvidenceHighlight",
    "ProcessFlow",
    "Timeline",
]


class Scene(StrictModel):
    scene_id: str
    order: int = Field(ge=0)
    start_time: float = Field(ge=0)
    duration: float = Field(gt=0)
    transition: Literal["cut", "fade", "slide"] = "fade"
    primitive: ScenePrimitive
    layout: LayoutPreset = "hero"
    motion: MotionPreset = "precise"
    script_segment_ids: list[str] = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    on_screen_text: str
    visual: VisualSpec | TypedVisualSpec
    asset_ids: list[str] = Field(default_factory=list)
    accessibility_description: str
    evidence_label: Literal["DOCUMENTED", "MEASURED", "SIMULATED", "INFERRED"] | None = None
    citation_label: str | None = None
    theme_overrides: dict[str, str] = Field(default_factory=dict)
    review_status: ReviewStatus = ReviewStatus.PENDING
    dependency_hash: str

    @field_validator(
        "scene_id",
        "on_screen_text",
        "accessibility_description",
        "evidence_label",
        "citation_label",
    )
    @classmethod
    def inert_scene_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None

    @model_validator(mode="after")
    def primitive_matches_typed_visual(self) -> Scene:
        if isinstance(self.visual, VisualSpec):
            if self.primitive in {
                "RasterScan",
                "TimeSlice",
                "GridWarp",
                "BeforeAfterOverlay",
                "AnnotatedChart",
                "EvidenceHighlight",
                "ProcessFlow",
                "Timeline",
            }:
                raise ValueError("new scene primitives require a typed visual specification")
            return self
        expected = {
            "KineticText": "kinetic-text",
            "SourceReceipt": "source-receipt",
            "MechanismDiagram": "mechanism-diagram",
            "ChartReveal": "annotated-chart",
            "AnnotatedChart": "annotated-chart",
            "ParameterSimulation": "parameter-simulation",
            "Comparison": "comparison",
            "LimitationCard": "limitation",
            "RasterScan": "raster-scan",
            "TimeSlice": "time-slice",
            "GridWarp": "grid-warp",
            "BeforeAfterOverlay": "before-after-overlay",
            "EvidenceHighlight": "evidence-highlight",
            "ProcessFlow": "process-flow",
            "Timeline": "timeline",
        }
        if self.visual.kind != expected[self.primitive]:
            raise ValueError("scene primitive does not match its typed visual kind")
        return self

    @field_validator("script_segment_ids", "claim_ids", "asset_ids")
    @classmethod
    def inert_scene_ids(cls, value: list[str]) -> list[str]:
        return [validate_inert_text(item) for item in value]

    @field_validator("theme_overrides")
    @classmethod
    def inert_theme_overrides(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {
            "background",
            "panel",
            "text",
            "muted",
            "accent",
            "warning",
            "danger",
            "citation",
        }
        for key, item in value.items():
            validate_inert_text(key)
            validate_inert_text(item)
            if key not in allowed:
                raise ValueError(f"theme override {key!r} is not allowlisted")
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", item):
                raise ValueError("theme overrides must be six-digit hexadecimal colors")
        return value


class StoryboardManifest(StrictModel):
    version_id: str
    script_version_id: str
    scenes: list[Scene]


class Asset(StrictModel):
    asset_id: str
    asset_type: str
    local_path: str
    sha256: str
    origin: str
    creator: str
    source_url: str | None = None
    license: str
    required_attribution: str | None = None
    rights_status: Literal[
        "original", "user-owned", "permissively-licensed", "citation-only", "unknown", "restricted"
    ]
    embedding_allowed: bool
    review_status: ReviewStatus = ReviewStatus.PENDING
    scene_usage: list[str] = Field(default_factory=list)

    @field_validator("local_path")
    @classmethod
    def asset_path_safe(cls, value: str) -> str:
        return SourceDocument.safe_relative_path(value)


class AssetManifest(StrictModel):
    version_id: str
    assets: list[Asset] = Field(default_factory=list)


class ReviewDecision(StrictModel):
    review_id: str
    object_type: str
    object_id: str
    object_hash: str
    decision: Literal["approve", "reject", "edit", "note"]
    edit_or_note: str | None = None
    reviewer_id: str
    timestamp: datetime = Field(default_factory=now_utc)
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None


class ReviewLog(StrictModel):
    reviews: list[ReviewDecision] = Field(default_factory=list)


class RenderManifest(StrictModel):
    render_id: str
    width: int
    height: int
    fps: float
    duration: float
    codec: str
    script_hash: str
    storyboard_hash: str
    scene_versions: dict[str, str]
    asset_hashes: dict[str, str]
    audio_hash: str | None = None
    renderer_version: str
    prompt_versions: dict[str, str]
    source_hashes: dict[str, str]
    output_paths: list[str]
    output_hashes: dict[str, str] = Field(default_factory=dict)
    watermarked: bool = False
    rendered_at: datetime = Field(default_factory=now_utc)


class QACheck(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    check_id: str
    status: Literal["pass", "warning", "failure"]
    message: str
    hard_blocker: bool = False


class QAReport(StrictModel):
    project_id: str
    generated_at: datetime = Field(default_factory=now_utc)
    checks: list[QACheck]
    export_blockers: list[str]
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    media_path: str | None = None
    media_hash: str | None = None

    @property
    def passed(self) -> bool:
        return not self.export_blockers and not any(
            c.status == "failure" and c.hard_blocker for c in self.checks
        )


Artifact = Annotated[
    ProjectManifest
    | SourceIndex
    | EvidenceManifest
    | ClaimCritiqueReport
    | ClaimsManifest
    | AnglesManifest
    | AngleSelection
    | ScriptManifest
    | StoryboardManifest
    | AssetManifest
    | ReviewLog
    | RenderManifest
    | QAReport,
    Field(discriminator=None),
]
