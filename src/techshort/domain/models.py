from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

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
    theme: str = "midnight"
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
    def factual_requires_claims(self) -> ScriptSegment:
        if (
            self.segment_type in {"factual", "hook", "analogy", "caveat", "limitation"}
            and not self.claim_ids
        ):
            raise ValueError(f"{self.segment_type} segment requires at least one claim")
        return self


class ScriptManifest(StrictModel):
    version_id: str
    claims_version_id: str
    angle: Literal["surprising-result", "everyday-mechanism", "engineering-tradeoff"]
    segments: list[ScriptSegment]

    @model_validator(mode="after")
    def limitation_required(self) -> ScriptManifest:
        if not any(s.segment_type == "limitation" for s in self.segments):
            raise ValueError("script requires a meaningful limitation segment")
        return self


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

    @field_validator("title", "body", "left", "right", "citation")
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


ScenePrimitive = Literal[
    "KineticText",
    "SourceReceipt",
    "MechanismDiagram",
    "ChartReveal",
    "ParameterSimulation",
    "Comparison",
    "LimitationCard",
]


class Scene(StrictModel):
    scene_id: str
    order: int = Field(ge=0)
    start_time: float = Field(ge=0)
    duration: float = Field(gt=0)
    transition: Literal["cut", "fade", "slide"] = "fade"
    primitive: ScenePrimitive
    script_segment_ids: list[str] = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    on_screen_text: str
    visual: VisualSpec
    asset_ids: list[str] = Field(default_factory=list)
    accessibility_description: str
    evidence_label: str | None = None
    theme_overrides: dict[str, str] = Field(default_factory=dict)
    review_status: ReviewStatus = ReviewStatus.PENDING
    dependency_hash: str

    @field_validator(
        "scene_id",
        "on_screen_text",
        "accessibility_description",
        "evidence_label",
    )
    @classmethod
    def inert_scene_text(cls, value: str | None) -> str | None:
        return validate_inert_text(value) if value is not None else None

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
    | ClaimsManifest
    | ScriptManifest
    | StoryboardManifest
    | AssetManifest
    | ReviewLog
    | RenderManifest
    | QAReport,
    Field(discriminator=None),
]
