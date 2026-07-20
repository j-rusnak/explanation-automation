from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.domain.hashing import stable_hash
from techshort.domain.models import AngleKind

CREATIVE_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

BeatRole = Literal[
    "hook",
    "re-hook",
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


HookRevealStrategy = Literal[
    "show-result-then-explain",
    "state-mechanism-then-demonstrate",
    "ask-bounded-question",
]
RetentionEventKind = Literal[
    "re-hook",
    "pattern-interrupt",
    "evidence-payoff",
    "limitation-reframe",
    "final-payoff",
]
EngagementDevice = Literal[
    "question-pivot",
    "visual-mode-change",
    "source-receipt",
    "parameter-change",
    "comparison-switch",
    "misconception-correction",
    "callback",
]
SoundDesignCue = Literal[
    "soft-hit",
    "scan-pulse",
    "source-click",
    "contrast-shift",
    "resolve-tone",
]
CadenceEnergy = Literal["high", "medium", "low"]
CadenceRole = Literal[
    "open",
    "develop",
    "re-hook",
    "evidence-payoff",
    "limitation",
    "resolve",
]


class HonestColdOpen(CreativeStrictModel):
    hook_id: str = Field(min_length=1, max_length=120)
    beat_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=8, max_length=320)
    claim_ids: list[str] = Field(min_length=1, max_length=8)
    reveal_strategy: HookRevealStrategy
    truth_up_front: Literal[True] = True
    deceptive_withholding: Literal[False] = False
    promised_payoff: str = Field(min_length=12, max_length=500)
    payoff_beat_id: str = Field(min_length=1, max_length=120)
    duration_seconds: float = Field(gt=0, le=5)

    @model_validator(mode="after")
    def hook_is_bounded_and_unique(self) -> HonestColdOpen:
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("cold-open claim IDs must be unique")
        if self.payoff_beat_id == self.beat_id:
            raise ValueError("cold open must promise a later payoff beat")
        return self


class CuriosityThread(CreativeStrictModel):
    thread_id: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=8, max_length=320)
    opened_at_beat_id: str = Field(min_length=1, max_length=120)
    payoff_beat_id: str = Field(min_length=1, max_length=120)
    payoff: str = Field(min_length=12, max_length=500)
    claim_ids: list[str] = Field(min_length=1, max_length=8)
    deceptive_withholding: Literal[False] = False

    @model_validator(mode="after")
    def payoff_is_later_and_claims_are_unique(self) -> CuriosityThread:
        if self.opened_at_beat_id == self.payoff_beat_id:
            raise ValueError("curiosity thread must resolve in a later beat")
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("curiosity-thread claim IDs must be unique")
        return self


class RetentionEvent(CreativeStrictModel):
    event_id: str = Field(min_length=1, max_length=120)
    beat_id: str = Field(min_length=1, max_length=120)
    scheduled_at_seconds: float = Field(ge=0, le=60)
    event_kind: RetentionEventKind
    device: EngagementDevice
    purpose: str = Field(min_length=8, max_length=400)
    claim_ids: list[str] = Field(min_length=1, max_length=8)
    resolves_thread_ids: list[str] = Field(default_factory=list, max_length=4)
    # Metadata only: it cannot name a file, asset, command, or generated sound.
    sound_design: SoundDesignCue | None = None

    @model_validator(mode="after")
    def links_are_unique(self) -> RetentionEvent:
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("retention-event claim IDs must be unique")
        if len(self.resolves_thread_ids) != len(set(self.resolves_thread_ids)):
            raise ValueError("resolved curiosity-thread IDs must be unique")
        return self


class CadenceBeat(CreativeStrictModel):
    beat_id: str = Field(min_length=1, max_length=120)
    starts_at_seconds: float = Field(ge=0, le=60)
    duration_seconds: float = Field(gt=0, le=12)
    energy: CadenceEnergy
    cadence_role: CadenceRole
    ends_with_forward_motion: bool


class BeatCadence(CreativeStrictModel):
    total_duration_seconds: float = Field(ge=45, le=60)
    max_attention_gap_seconds: float = Field(gt=0, le=5)
    beats: list[CadenceBeat] = Field(min_length=6, max_length=12)

    @model_validator(mode="after")
    def beats_are_unique_contiguous_and_complete(self) -> BeatCadence:
        beat_ids = [beat.beat_id for beat in self.beats]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("cadence beat IDs must be unique")
        expected_start = 0.0
        for beat in self.beats:
            if abs(beat.starts_at_seconds - expected_start) > 0.01:
                raise ValueError("cadence beats must be contiguous and start at zero")
            expected_start += beat.duration_seconds
        if abs(expected_start - self.total_duration_seconds) > 0.01:
            raise ValueError("cadence total must equal the sum of beat durations")
        return self


class AntiClickbaitPolicy(CreativeStrictModel):
    honest_opening: Literal[True] = True
    bounded_curiosity: Literal[True] = True
    payoff_matches_promise: Literal[True] = True
    no_false_urgency: Literal[True] = True
    no_exaggerated_certainty: Literal[True] = True
    no_engagement_bait: Literal[True] = True


class RetentionPlan(CreativeStrictModel):
    version_id: str = Field(pattern=r"^retention-[0-9a-f]{16}$")
    narrative_brief_version_id: str
    beat_plan_version_id: str
    script_version_id: str
    claims_version_id: str
    angle: AngleKind
    factual_locks: list[FactualLock] = Field(min_length=1)
    cold_open: HonestColdOpen
    curiosity_threads: list[CuriosityThread] = Field(min_length=1, max_length=4)
    attention_events: list[RetentionEvent] = Field(min_length=5, max_length=12)
    cadence: BeatCadence
    policy: AntiClickbaitPolicy = Field(default_factory=AntiClickbaitPolicy)
    evidence_payoff_beat_id: str
    evidence_claim_ids: list[str] = Field(min_length=1, max_length=16)
    meaningful_limitation_beat_id: str
    meaningful_limitation_claim_ids: list[str] = Field(min_length=1, max_length=16)
    target_word_count: tuple[int, int] = (130, 170)

    @model_validator(mode="after")
    def engagement_is_periodic_honest_and_evidence_locked(self) -> RetentionPlan:
        lock_ids = [lock.claim_id for lock in self.factual_locks]
        if len(lock_ids) != len(set(lock_ids)):
            raise ValueError("retention-plan factual locks must have unique claim IDs")
        cadence_by_id = {beat.beat_id: beat for beat in self.cadence.beats}
        order_by_id = {beat.beat_id: index for index, beat in enumerate(self.cadence.beats)}
        if self.cold_open.beat_id != self.cadence.beats[0].beat_id:
            raise ValueError("cold open must bind the first cadence beat")
        if abs(self.cold_open.duration_seconds - self.cadence.beats[0].duration_seconds) > 0.01:
            raise ValueError("cold-open duration must match its cadence beat")
        if self.cold_open.payoff_beat_id not in cadence_by_id:
            raise ValueError("cold-open payoff beat is missing from cadence")
        if order_by_id[self.cold_open.payoff_beat_id] <= 0:
            raise ValueError("cold-open payoff must occur after the opening beat")
        thread_ids = [thread.thread_id for thread in self.curiosity_threads]
        if len(thread_ids) != len(set(thread_ids)):
            raise ValueError("curiosity-thread IDs must be unique")
        for thread in self.curiosity_threads:
            if (
                thread.opened_at_beat_id not in cadence_by_id
                or thread.payoff_beat_id not in cadence_by_id
            ):
                raise ValueError("curiosity thread references an unknown cadence beat")
            if order_by_id[thread.payoff_beat_id] <= order_by_id[thread.opened_at_beat_id]:
                raise ValueError("curiosity-thread payoff must occur after its opening")
        if self.evidence_payoff_beat_id not in cadence_by_id:
            raise ValueError("evidence payoff beat is missing from cadence")
        if cadence_by_id[self.evidence_payoff_beat_id].cadence_role != "evidence-payoff":
            raise ValueError("evidence payoff beat must use the evidence-payoff cadence role")
        if self.meaningful_limitation_beat_id not in cadence_by_id:
            raise ValueError("meaningful limitation beat is missing from cadence")
        if cadence_by_id[self.meaningful_limitation_beat_id].cadence_role != "limitation":
            raise ValueError("meaningful limitation beat must use the limitation cadence role")
        event_ids = [event.event_id for event in self.attention_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("retention-event IDs must be unique")
        event_times = [event.scheduled_at_seconds for event in self.attention_events]
        if event_times != sorted(event_times):
            raise ValueError("retention events must be ordered by scheduled time")
        for event in self.attention_events:
            cadence_beat = cadence_by_id.get(event.beat_id)
            if cadence_beat is None:
                raise ValueError("retention event references an unknown cadence beat")
            beat_end = cadence_beat.starts_at_seconds + cadence_beat.duration_seconds
            if not cadence_beat.starts_at_seconds <= event.scheduled_at_seconds <= beat_end:
                raise ValueError("retention event must occur inside its cadence beat")
        if event_times[0] > 2:
            raise ValueError("first attention event must occur by two seconds")
        attention_markers = [0.0, *event_times, self.cadence.total_duration_seconds]
        if any(
            later - earlier > self.cadence.max_attention_gap_seconds + 0.01
            for earlier, later in zip(attention_markers, attention_markers[1:], strict=False)
        ):
            raise ValueError("retention events exceed the maximum attention gap")
        event_kinds = {event.event_kind for event in self.attention_events}
        required_kinds = {
            "re-hook",
            "pattern-interrupt",
            "evidence-payoff",
            "limitation-reframe",
            "final-payoff",
        }
        if not required_kinds <= event_kinds:
            raise ValueError("retention plan is missing a required attention-event kind")
        midpoint_rehooks = [
            event
            for event in self.attention_events
            if event.event_kind == "re-hook"
            and self.cadence.total_duration_seconds * 0.35
            <= event.scheduled_at_seconds
            <= self.cadence.total_duration_seconds * 0.65
        ]
        if len(midpoint_rehooks) < 2:
            raise ValueError("retention plan requires two mid-video re-hooks")
        if (
            len({event.beat_id for event in midpoint_rehooks}) < 2
            or len({event.scheduled_at_seconds for event in midpoint_rehooks}) < 2
        ):
            raise ValueError("mid-video re-hooks must use distinct beats and times")
        evidence_claim_ids = set(self.evidence_claim_ids)
        if len(evidence_claim_ids) != len(self.evidence_claim_ids):
            raise ValueError("evidence claim IDs must be unique")
        evidence_threads = [
            thread
            for thread in self.curiosity_threads
            if thread.payoff_beat_id == self.evidence_payoff_beat_id
        ]
        if not evidence_threads or not any(
            set(thread.claim_ids) & evidence_claim_ids for thread in evidence_threads
        ):
            raise ValueError("evidence claims must bind a curiosity payoff at the evidence beat")
        evidence_payoffs = [
            event for event in self.attention_events if event.event_kind == "evidence-payoff"
        ]
        if not evidence_payoffs or any(
            event.beat_id != self.evidence_payoff_beat_id
            or not (set(event.claim_ids) & evidence_claim_ids)
            for event in evidence_payoffs
        ):
            raise ValueError("evidence-payoff events must bind the evidence beat and claims")
        limitation_claim_ids = set(self.meaningful_limitation_claim_ids)
        if len(limitation_claim_ids) != len(self.meaningful_limitation_claim_ids):
            raise ValueError("meaningful-limitation claim IDs must be unique")
        limitation_reframes = [
            event for event in self.attention_events if event.event_kind == "limitation-reframe"
        ]
        if not limitation_reframes or any(
            event.beat_id != self.meaningful_limitation_beat_id
            or not (set(event.claim_ids) & limitation_claim_ids)
            for event in limitation_reframes
        ):
            raise ValueError("limitation-reframe events must bind the limitation beat and claims")
        resolved_threads = {
            thread_id for event in self.attention_events for thread_id in event.resolves_thread_ids
        }
        unknown_threads = resolved_threads - set(thread_ids)
        if unknown_threads:
            raise ValueError(f"retention events resolve unknown threads: {sorted(unknown_threads)}")
        if set(thread_ids) - resolved_threads:
            raise ValueError("every curiosity thread must have an explicit payoff event")
        referenced_claims = set(self.cold_open.claim_ids)
        referenced_claims.update(
            claim_id for thread in self.curiosity_threads for claim_id in thread.claim_ids
        )
        referenced_claims.update(
            claim_id for event in self.attention_events for claim_id in event.claim_ids
        )
        referenced_claims.update(evidence_claim_ids)
        referenced_claims.update(limitation_claim_ids)
        unknown_claims = referenced_claims - set(lock_ids)
        if unknown_claims:
            raise ValueError(f"retention plan references unlocked claims: {sorted(unknown_claims)}")
        if self.target_word_count != (130, 170):
            raise ValueError("retention plan must preserve the 130–170 word target")
        expected = derive_creative_id("retention", self)
        if self.version_id != expected:
            raise ValueError("retention-plan version ID does not match its content")
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
RetentionCategory = Literal[
    "dishonest-cold-open",
    "deceptive-withholding",
    "clickbait-language",
    "unsupported-engagement-claim",
    "missing-payoff",
    "attention-gap",
    "cadence",
    "word-count",
    "missing-limitation",
    "missing-evidence",
    "hook-drift",
    "payoff-drift",
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


class RetentionFinding(CreativeStrictModel):
    category: RetentionCategory
    severity: Literal["warning", "error"]
    message: str = Field(min_length=1, max_length=600)
    beat_id: str | None = None
    segment_id: str | None = None
    event_id: str | None = None


class RetentionCritique(CreativeStrictModel):
    critique_id: str = Field(pattern=r"^retention-critique-[0-9a-f]{16}$")
    retention_plan_version_id: str
    narrative_brief_version_id: str
    beat_plan_version_id: str
    script_version_id: str
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    spoken_word_count: int = Field(ge=0)
    spoken_words_per_minute: float = Field(ge=0)
    findings: list[RetentionFinding] = Field(default_factory=list)
    blocking: bool

    @model_validator(mode="after")
    def blocking_and_id_match_findings(self) -> RetentionCritique:
        expected_blocking = any(item.severity == "error" for item in self.findings)
        if self.blocking != expected_blocking:
            raise ValueError("retention critique blocking state must match error findings")
        expected = derive_creative_id("retention-critique", self)
        if self.critique_id != expected:
            raise ValueError("retention critique ID does not match its content")
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
