from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.domain.hashing import stable_hash
from techshort.domain.models import AngleKind

CREATIVE_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

BeatRole = Literal[
    "hook",
    "setup",
    "mechanism",
    "evidence",
    "consequence",
    "tradeoff",
    "limitation",
    "resolution",
]
LayoutFamily = Literal[
    "hero",
    "full-diagram",
    "split-comparison",
    "evidence-receipt",
    "numeric-result",
    "limitation",
]
PrimitiveHint = Literal[
    "KineticText",
    "SourceReceipt",
    "MechanismDiagram",
    "ChartReveal",
    "ParameterSimulation",
    "Comparison",
    "LimitationCard",
    "RasterScan",
    "GridWarp",
    "BeforeAfterOverlay",
    "EvidenceHighlight",
    "Timeline",
]


def _complete_json_value(value: object) -> Any:
    """Normalize nested models without the approval-field exclusions of stable_hash."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _complete_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_complete_json_value(item) for item in value]
    return value


def derive_creative_id(prefix: str, payload: BaseModel | dict[str, object]) -> str:
    """Derive an immutable artifact ID from its complete versioned payload."""
    if isinstance(payload, BaseModel):
        value = payload.model_dump(mode="json")
    else:
        value = _complete_json_value(payload)
        # Pydantic supplies this default before model-level integrity validation.
        # Include it for callers deriving an ID from pre-validation input too.
        value.setdefault("schema_version", CREATIVE_SCHEMA_VERSION)
    value.pop("version_id", None)
    value.pop("critique_id", None)
    return f"{prefix}-{stable_hash(value)[:16]}"


class CreativeStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)
    schema_version: Literal["1.0.0"] = CREATIVE_SCHEMA_VERSION


class FactualLock(CreativeStrictModel):
    """Exact claim-content snapshot that creative artifacts may not expand."""

    claim_id: str = Field(min_length=1, max_length=160)
    claim_state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    assertion: str = Field(min_length=1, max_length=1200)
    evidence_span_ids: list[str] = Field(min_length=1, max_length=16)

    @field_validator("evidence_span_ids")
    @classmethod
    def evidence_ids_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("factual-lock evidence IDs must be unique")
        return value


class NarrativeBrief(CreativeStrictModel):
    version_id: str = Field(pattern=r"^brief-[0-9a-f]{16}$")
    claims_version_id: str
    evidence_version_id: str
    angles_version_id: str
    angle_selection_id: str
    angle: AngleKind
    audience: str = Field(min_length=3, max_length=240)
    promise: str = Field(min_length=12, max_length=400)
    central_mechanism: str = Field(min_length=12, max_length=800)
    central_claim_ids: list[str] = Field(min_length=1, max_length=8)
    evidence_claim_ids: list[str] = Field(min_length=1, max_length=8)
    limitation_claim_ids: list[str] = Field(min_length=1, max_length=8)
    visible_evidence: str = Field(min_length=12, max_length=600)
    meaningful_limitation: str = Field(min_length=20, max_length=600)
    visual_motif: str = Field(min_length=12, max_length=600)
    target_word_count: tuple[int, int] = (130, 170)
    target_duration_seconds: tuple[float, float] = (45, 75)
    factual_locks: list[FactualLock] = Field(min_length=1)

    @model_validator(mode="after")
    def references_only_locked_claims_and_has_content_id(self) -> NarrativeBrief:
        lock_ids = [lock.claim_id for lock in self.factual_locks]
        if len(lock_ids) != len(set(lock_ids)):
            raise ValueError("narrative-brief factual locks must have unique claim IDs")
        referenced = set(
            self.central_claim_ids + self.evidence_claim_ids + self.limitation_claim_ids
        )
        unknown = referenced - set(lock_ids)
        if unknown:
            raise ValueError(f"narrative brief references unlocked claims: {sorted(unknown)}")
        if self.target_word_count[0] > self.target_word_count[1]:
            raise ValueError("target word-count range must be ordered")
        if self.target_duration_seconds[0] > self.target_duration_seconds[1]:
            raise ValueError("target duration range must be ordered")
        expected = derive_creative_id("brief", self)
        if self.version_id != expected:
            raise ValueError("narrative brief version ID does not match its content")
        return self


class Beat(CreativeStrictModel):
    beat_id: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=0)
    role: BeatRole
    purpose: str = Field(min_length=8, max_length=500)
    narration_guidance: str = Field(min_length=8, max_length=800)
    on_screen_text: str = Field(min_length=1, max_length=100)
    visual_guidance: str = Field(min_length=8, max_length=1000)
    primitive_hint: PrimitiveHint
    layout_family: LayoutFamily
    animation_beats: list[str] = Field(min_length=1, max_length=8)
    claim_ids: list[str] = Field(min_length=1, max_length=8)
    evidence_span_ids: list[str] = Field(default_factory=list, max_length=16)
    approximate_duration: float = Field(gt=0, le=30)

    @model_validator(mode="after")
    def evidence_beat_has_locator_and_claims_are_unique(self) -> Beat:
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("beat claim IDs must be unique")
        if len(self.evidence_span_ids) != len(set(self.evidence_span_ids)):
            raise ValueError("beat evidence IDs must be unique")
        if self.role == "evidence" and not self.evidence_span_ids:
            raise ValueError("evidence beat requires at least one exact evidence span")
        return self


class BeatPlan(CreativeStrictModel):
    version_id: str = Field(pattern=r"^beats-[0-9a-f]{16}$")
    narrative_brief_version_id: str
    claims_version_id: str
    angle: AngleKind
    factual_locks: list[FactualLock] = Field(min_length=1)
    beats: list[Beat] = Field(min_length=5, max_length=12)

    @model_validator(mode="after")
    def has_required_beats_and_only_locked_claims(self) -> BeatPlan:
        lock_ids = [lock.claim_id for lock in self.factual_locks]
        if len(lock_ids) != len(set(lock_ids)):
            raise ValueError("beat-plan factual locks must have unique claim IDs")
        if [beat.order for beat in self.beats] != list(range(len(self.beats))):
            raise ValueError("beat order must be contiguous and start at zero")
        beat_ids = [beat.beat_id for beat in self.beats]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("beat IDs must be unique")
        roles = {beat.role for beat in self.beats}
        if "evidence" not in roles:
            raise ValueError("beat plan requires a visible evidence beat")
        if "limitation" not in roles:
            raise ValueError("beat plan requires a meaningful limitation beat")
        referenced = {claim_id for beat in self.beats for claim_id in beat.claim_ids}
        unknown = referenced - set(lock_ids)
        if unknown:
            raise ValueError(f"beat plan references unlocked claims: {sorted(unknown)}")
        expected = derive_creative_id("beats", self)
        if self.version_id != expected:
            raise ValueError("beat-plan version ID does not match its content")
        return self


class SceneGuidance(CreativeStrictModel):
    scene_key: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=0)
    beat_id: str
    layout_family: LayoutFamily
    primitive_hint: PrimitiveHint
    on_screen_text: str = Field(min_length=1, max_length=100)
    visual_direction: str = Field(min_length=8, max_length=1000)
    animation_beats: list[str] = Field(min_length=1, max_length=8)
    claim_ids: list[str] = Field(min_length=1, max_length=8)
    evidence_span_ids: list[str] = Field(default_factory=list, max_length=16)


class StoryboardGuidance(CreativeStrictModel):
    version_id: str = Field(pattern=r"^visual-plan-[0-9a-f]{16}$")
    narrative_brief_version_id: str
    beat_plan_version_id: str
    script_version_id: str
    angle: AngleKind
    factual_locks: list[FactualLock] = Field(min_length=1)
    scenes: list[SceneGuidance] = Field(min_length=5, max_length=12)

    @model_validator(mode="after")
    def guidance_is_ordered_and_locked(self) -> StoryboardGuidance:
        if [scene.order for scene in self.scenes] != list(range(len(self.scenes))):
            raise ValueError("scene guidance order must be contiguous and start at zero")
        keys = [scene.scene_key for scene in self.scenes]
        if len(keys) != len(set(keys)):
            raise ValueError("scene guidance keys must be unique")
        lock_ids = {lock.claim_id for lock in self.factual_locks}
        unknown = {claim_id for scene in self.scenes for claim_id in scene.claim_ids} - lock_ids
        if unknown:
            raise ValueError(f"storyboard guidance references unlocked claims: {sorted(unknown)}")
        expected = derive_creative_id("visual-plan", self)
        if self.version_id != expected:
            raise ValueError("storyboard-guidance version ID does not match its content")
        return self


EditorialCategory = Literal[
    "unsupported-claim",
    "missing-central-claim",
    "missing-evidence",
    "missing-limitation",
    "repetition",
    "excessive-text",
    "weak-hook",
    "pacing",
    "manipulative-language",
    "narrative-drift",
]
VisualCategory = Literal[
    "unsupported-visual-assertion",
    "missing-evidence-receipt",
    "missing-limitation-card",
    "repeated-primitive",
    "repeated-layout",
    "duplicated-narration",
    "overlong-on-screen-text",
    "missing-units",
    "weak-visual-metaphor",
    "static-sequence",
]


class EditorialFinding(CreativeStrictModel):
    category: EditorialCategory
    severity: Literal["warning", "error"]
    message: str = Field(min_length=1, max_length=600)
    beat_id: str | None = None
    segment_id: str | None = None


class EditorialCritique(CreativeStrictModel):
    critique_id: str = Field(pattern=r"^editorial-critique-[0-9a-f]{16}$")
    narrative_brief_version_id: str
    beat_plan_version_id: str
    script_version_id: str
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    findings: list[EditorialFinding] = Field(default_factory=list)
    blocking: bool

    @model_validator(mode="after")
    def blocking_and_id_match_findings(self) -> EditorialCritique:
        expected_blocking = any(item.severity == "error" for item in self.findings)
        if self.blocking != expected_blocking:
            raise ValueError("editorial critique blocking state must match error findings")
        expected = derive_creative_id("editorial-critique", self)
        if self.critique_id != expected:
            raise ValueError("editorial critique ID does not match its content")
        return self


class VisualFinding(CreativeStrictModel):
    category: VisualCategory
    severity: Literal["warning", "error"]
    message: str = Field(min_length=1, max_length=600)
    scene_key: str | None = None


class VisualCritique(CreativeStrictModel):
    critique_id: str = Field(pattern=r"^visual-critique-[0-9a-f]{16}$")
    narrative_brief_version_id: str
    beat_plan_version_id: str
    storyboard_guidance_version_id: str
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    findings: list[VisualFinding] = Field(default_factory=list)
    blocking: bool

    @model_validator(mode="after")
    def blocking_and_id_match_findings(self) -> VisualCritique:
        expected_blocking = any(item.severity == "error" for item in self.findings)
        if self.blocking != expected_blocking:
            raise ValueError("visual critique blocking state must match error findings")
        expected = derive_creative_id("visual-critique", self)
        if self.critique_id != expected:
            raise ValueError("visual critique ID does not match its content")
        return self
