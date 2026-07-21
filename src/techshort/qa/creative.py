from __future__ import annotations

import math
import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.alignment.captions import (
    MAX_CAPTION_CHARACTERS_PER_SECOND,
    MIN_CAPTION_DURATION_SECONDS,
    CaptionCue,
)
from techshort.domain.creative import RetentionPlan
from techshort.domain.models import (
    AnnotatedChartVisual,
    ScriptManifest,
    StoryboardManifest,
    VisualSpec,
)

CREATIVE_QA_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

PacingProfile = Literal["measured", "brisk", "high-retention"]
EngagementRole = Literal[
    "cold-open",
    "setup",
    "mechanism",
    "evidence",
    "rehook",
    "payoff",
    "limitation",
    "resolution",
]
MotionIntensity = Literal["calm", "precise", "energetic"]
RetentionEventKind = Literal[
    "re-hook",
    "pattern-interrupt",
    "evidence-payoff",
    "limitation-reframe",
    "final-payoff",
]

_INTERNAL_ID = re.compile(
    r"\b(?:claim|scene|segment|asset|render|review|script|storyboard)"
    r"[-_][a-z0-9][a-z0-9_.:-]*\b"
    r"|\b(?:evidence|source)[-_](?!(?:linked|backed)\b)"
    r"[a-z0-9][a-z0-9_.:-]*\b",
    re.IGNORECASE,
)
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_WORD = re.compile(r"[\w']+", re.UNICODE)
_PLACEHOLDER_FOCALS = {
    "",
    "abstract",
    "default",
    "generic",
    "none",
    "placeholder",
    "text",
    "text-only",
}
_MANIPULATIVE_HOOK_PATTERNS = (
    re.compile(r"\byou (?:will not|won't) believe\b", re.IGNORECASE),
    re.compile(r"\b(?:wait|watch) (?:until|for|to) (?:the )?end\b", re.IGNORECASE),
    re.compile(r"\bwhat happens next\b", re.IGNORECASE),
    re.compile(r"\bthey do(?: not|n't) want you to know\b", re.IGNORECASE),
    re.compile(r"\bthis proves?(?: that)?\b", re.IGNORECASE),
    re.compile(r"\bguaranteed(?: to)?\b", re.IGNORECASE),
    re.compile(r"\b(?:shocking|mind[- ]blowing) secret\b", re.IGNORECASE),
)
_FLASH_CUE = re.compile(r"\b(?:flash|strobe|blink|flicker)\b", re.IGNORECASE)
_CADENCE_ROLE_TO_ENGAGEMENT: dict[str, EngagementRole] = {
    "open": "cold-open",
    "develop": "mechanism",
    "re-hook": "rehook",
    "evidence-payoff": "payoff",
    "limitation": "limitation",
    "resolve": "resolution",
}
_CADENCE_ENERGY_TO_MOTION: dict[str, MotionIntensity] = {
    "low": "calm",
    "medium": "precise",
    "high": "energetic",
}


class _StrictQualityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CreativeCoverInput(_StrictQualityModel):
    cover_id: str
    headline: str = Field(min_length=1, max_length=240)
    focal_visual: str | None = Field(default=None, max_length=120)
    layout: str = Field(min_length=1, max_length=80)
    subtitle: str | None = Field(default=None, max_length=300)
    citation: str | None = Field(default=None, max_length=300)
    factual: bool = True


class CreativeSceneInput(_StrictQualityModel):
    scene_id: str
    primitive: str = Field(min_length=1, max_length=80)
    layout: str = Field(min_length=1, max_length=80)
    duration_seconds: float = Field(gt=0, le=300)
    title: str = Field(min_length=1, max_length=300)
    on_screen_text: str = Field(default="", max_length=1200)
    body: str | None = Field(default=None, max_length=1800)
    narration: str = Field(default="", max_length=4000)
    factual: bool = True
    citation: str | None = Field(default=None, max_length=400)
    evidence_label: str | None = Field(default=None, max_length=80)
    series: list[float] = Field(default_factory=list, max_length=100)
    labels: list[str] = Field(default_factory=list, max_length=100)
    x_axis_label: str | None = Field(default=None, max_length=120)
    y_axis_label: str | None = Field(default=None, max_length=120)
    units: str | None = Field(default=None, max_length=60)
    motion_beats: list[str] = Field(default_factory=list, max_length=20)
    engagement_role: EngagementRole | None = None
    motion_intensity: MotionIntensity = "precise"
    flash_events_per_second: float = Field(default=0, ge=0, le=30)
    color_encodings: dict[str, str] = Field(default_factory=dict)
    non_color_cues: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("color_encodings")
    @classmethod
    def colors_are_hex(cls, value: dict[str, str]) -> dict[str, str]:
        if any(_HEX_COLOR.fullmatch(color) is None for color in value.values()):
            raise ValueError("data color encodings must use six-digit hexadecimal colors")
        return value


class CreativeCaptionInput(_StrictQualityModel):
    cue_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def timing_is_ordered(self) -> CreativeCaptionInput:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("caption end must be after its start")
        return self


class CreativeRetentionEventInput(_StrictQualityModel):
    event_id: str
    beat_id: str
    scheduled_at_seconds: float = Field(ge=0, le=300)
    event_kind: RetentionEventKind


class CreativeRetentionInput(_StrictQualityModel):
    plan_version_id: str
    timing_scale: float = Field(default=1, gt=0, le=10)
    cold_open_duration_seconds: float = Field(gt=0, le=30)
    cold_open_text: str = Field(min_length=1, max_length=1000)
    truth_up_front: bool
    deceptive_withholding: bool
    total_duration_seconds: float = Field(gt=0, le=300)
    max_attention_gap_seconds: float = Field(gt=0, le=30)
    events: list[CreativeRetentionEventInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def events_are_ordered_and_bounded(self) -> CreativeRetentionInput:
        times = [event.scheduled_at_seconds for event in self.events]
        if times != sorted(times):
            raise ValueError("creative retention events must be ordered")
        if times[-1] > self.total_duration_seconds:
            raise ValueError("creative retention events must fit inside runtime")
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("creative retention event IDs must be unique")
        return self


class CreativeQualityInput(_StrictQualityModel):
    schema_version: Literal["1.0.0"] = CREATIVE_QA_SCHEMA_VERSION
    case_id: str
    topic_kind: Literal["mechanism", "chart", "comparison", "timeline", "architecture", "other"]
    storyboard_version_id: str
    script_version_id: str
    pacing: PacingProfile = "brisk"
    cover: CreativeCoverInput
    scenes: list[CreativeSceneInput] = Field(min_length=1, max_length=120)
    captions: list[CreativeCaptionInput] = Field(default_factory=list, max_length=500)
    retention: CreativeRetentionInput | None = None

    @model_validator(mode="after")
    def object_ids_are_unique(self) -> CreativeQualityInput:
        scene_ids = [scene.scene_id for scene in self.scenes]
        cue_ids = [cue.cue_id for cue in self.captions]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("creative QA scene IDs must be unique")
        if len(cue_ids) != len(set(cue_ids)):
            raise ValueError("creative QA caption cue IDs must be unique")
        singular_roles = ("cold-open", "payoff")
        for role in singular_roles:
            if sum(scene.engagement_role == role for scene in self.scenes) > 1:
                raise ValueError(f"creative QA may declare at most one {role} scene")
        return self


QualityStatus = Literal["pass", "warning", "failure"]
QualityCategory = Literal[
    "cover",
    "clarity",
    "composition",
    "motion",
    "data-visualization",
    "provenance",
    "captions",
    "accessibility",
    "engagement",
]


class CreativeQualityCheck(_StrictQualityModel):
    check_id: str
    category: QualityCategory
    status: QualityStatus
    message: str
    remediation: str | None = None
    object_ids: list[str] = Field(default_factory=list)
    details: dict[str, str] = Field(default_factory=dict)

    @field_validator("object_ids")
    @classmethod
    def object_ids_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("creative QA check object IDs must be unique")
        return value


class CreativeQualityResult(_StrictQualityModel):
    schema_version: Literal["1.0.0"] = CREATIVE_QA_SCHEMA_VERSION
    case_id: str
    status: QualityStatus
    score: int = Field(ge=0, le=100)
    checks: list[CreativeQualityCheck]

    @model_validator(mode="after")
    def status_matches_checks(self) -> CreativeQualityResult:
        ids = [check.check_id for check in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("creative QA check IDs must be unique")
        expected: QualityStatus = (
            "failure"
            if any(check.status == "failure" for check in self.checks)
            else "warning"
            if any(check.status == "warning" for check in self.checks)
            else "pass"
        )
        if self.status != expected:
            raise ValueError("creative QA result status must match its checks")
        return self

    @property
    def needs_attention(self) -> bool:
        return self.status != "pass"


def _check(
    check_id: str,
    category: QualityCategory,
    status: QualityStatus,
    message: str,
    *,
    remediation: str | None = None,
    object_ids: Sequence[str] = (),
    details: dict[str, str] | None = None,
) -> CreativeQualityCheck:
    return CreativeQualityCheck(
        check_id=check_id,
        category=category,
        status=status,
        message=message,
        remediation=remediation,
        object_ids=list(object_ids),
        details=details or {},
    )


def _words(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _WORD.finditer(text)]


def _normalized_text(text: str) -> str:
    return " ".join(_words(text))


def _worst_status(statuses: Sequence[QualityStatus]) -> QualityStatus:
    if "failure" in statuses:
        return "failure"
    if "warning" in statuses:
        return "warning"
    return "pass"


def _cover_checks(snapshot: CreativeQualityInput) -> list[CreativeQualityCheck]:
    headline_words = len(_words(snapshot.cover.headline))
    headline_length = len(snapshot.cover.headline.strip())
    if headline_words > 14 or headline_length > 90:
        title_status: QualityStatus = "failure"
    elif headline_words > 10 or headline_length > 64:
        title_status = "warning"
    else:
        title_status = "pass"
    title = _check(
        "cover-headline",
        "cover",
        title_status,
        (
            "Cover headline is concise and mobile-readable"
            if title_status == "pass"
            else f"Cover headline uses {headline_words} words and {headline_length} characters"
        ),
        remediation=(
            None
            if title_status == "pass"
            else "Rewrite the cover as a concrete promise of ten words or fewer."
        ),
        object_ids=[snapshot.cover.cover_id],
        details={"words": str(headline_words), "characters": str(headline_length)},
    )

    focal = (snapshot.cover.focal_visual or "").strip().casefold()
    focal_ok = focal not in _PLACEHOLDER_FOCALS
    focal_check = _check(
        "cover-focal-visual",
        "cover",
        "pass" if focal_ok else "failure",
        (
            f"Cover declares the focal visual {snapshot.cover.focal_visual!r}"
            if focal_ok
            else "Cover has no meaningful focal visual"
        ),
        remediation=None if focal_ok else "Select a typed hero diagram, chart, or comparison.",
        object_ids=[snapshot.cover.cover_id],
    )
    return [title, focal_check]


def _rendered_text_objects(snapshot: CreativeQualityInput) -> list[tuple[str, str]]:
    rows = [
        (snapshot.cover.cover_id, snapshot.cover.headline),
        (snapshot.cover.cover_id, snapshot.cover.subtitle or ""),
        (snapshot.cover.cover_id, snapshot.cover.citation or ""),
    ]
    for scene in snapshot.scenes:
        rows.extend(
            [
                (scene.scene_id, scene.title),
                (scene.scene_id, scene.on_screen_text),
                (scene.scene_id, scene.body or ""),
                (scene.scene_id, scene.citation or ""),
            ]
        )
    return rows


def _internal_id_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    offenders = sorted(
        {
            object_id
            for object_id, text in _rendered_text_objects(snapshot)
            if _INTERNAL_ID.search(text)
        }
    )
    return _check(
        "exposed-internal-ids",
        "clarity",
        "failure" if offenders else "pass",
        (
            f"Internal manifest IDs are visible in {len(offenders)} rendered object(s)"
            if offenders
            else "No internal manifest IDs are exposed to viewers"
        ),
        remediation=(
            "Replace internal IDs with human-readable source, section, or evidence labels."
            if offenders
            else None
        ),
        object_ids=offenders,
    )


def _duplication_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    offenders: list[str] = []
    worst_ratio = 0.0
    for scene in snapshot.scenes:
        visible = _normalized_text(scene.on_screen_text)
        narration = _normalized_text(scene.narration)
        if len(_words(visible)) < 6 or not narration:
            continue
        ratio = SequenceMatcher(a=visible, b=narration, autojunk=False).ratio()
        containment = visible in narration or narration in visible
        worst_ratio = max(worst_ratio, ratio)
        if containment or ratio >= 0.78:
            offenders.append(scene.scene_id)
    return _check(
        "narration-screen-duplication",
        "clarity",
        "warning" if offenders else "pass",
        (
            f"Narration is substantially duplicated on screen in {len(offenders)} scene(s)"
            if offenders
            else "On-screen copy complements rather than repeats narration"
        ),
        remediation=(
            "Keep narration in captions and reduce scene copy to a headline, value, or keyword."
            if offenders
            else None
        ),
        object_ids=offenders,
        details={"highest_similarity": f"{worst_ratio:.2f}"},
    )


def _text_density_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    warning_ids: list[str] = []
    failure_ids: list[str] = []
    maximum = 0
    for scene in snapshot.scenes:
        surfaces = {
            text.strip()
            for text in (scene.title, scene.on_screen_text, scene.body or "")
            if text.strip()
        }
        count = len(_words(" ".join(surfaces)))
        maximum = max(maximum, count)
        if count > 48:
            failure_ids.append(scene.scene_id)
        elif count > 30:
            warning_ids.append(scene.scene_id)
    status: QualityStatus = "failure" if failure_ids else "warning" if warning_ids else "pass"
    offenders = failure_ids + warning_ids
    return _check(
        "scene-text-density",
        "composition",
        status,
        (
            f"{len(offenders)} scene(s) exceed the mobile text budget"
            if offenders
            else "Scene surfaces stay within the mobile text budget"
        ),
        remediation=(
            "Split dense scenes or replace prose with a visual label and one emphasized value."
            if offenders
            else None
        ),
        object_ids=offenders,
        details={"maximum_words": str(maximum)},
    )


def _scene_title_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    warnings: list[str] = []
    failures: list[str] = []
    for scene in snapshot.scenes:
        words = len(_words(scene.title))
        characters = len(scene.title.strip())
        if words > 14 or characters > 90:
            failures.append(scene.scene_id)
        elif words > 9 or characters > 60:
            warnings.append(scene.scene_id)
    status: QualityStatus = "failure" if failures else "warning" if warnings else "pass"
    offenders = failures + warnings
    return _check(
        "scene-title-length",
        "composition",
        status,
        (
            f"{len(offenders)} scene title(s) are too long for rapid scanning"
            if offenders
            else "Scene titles are concise"
        ),
        remediation="Shorten titles to nine words or fewer." if offenders else None,
        object_ids=offenders,
    )


def _longest_run(values: Sequence[str]) -> int:
    longest = 0
    current = 0
    previous: str | None = None
    for value in values:
        if value == previous:
            current += 1
        else:
            previous = value
            current = 1
        longest = max(longest, current)
    return longest


def _diversity_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    primitives = [scene.primitive for scene in snapshot.scenes]
    layouts = [scene.layout for scene in snapshot.scenes]
    unique_primitives = len(set(primitives))
    unique_layouts = len(set(layouts))
    longest_layout_run = _longest_run(layouts)
    scene_count = len(snapshot.scenes)
    if scene_count < 4:
        status: QualityStatus = "warning"
    elif unique_primitives == 1 or unique_layouts == 1:
        status = "failure"
    elif unique_primitives < min(3, scene_count) or longest_layout_run > 3:
        status = "warning"
    else:
        status = "pass"
    return _check(
        "primitive-layout-diversity",
        "composition",
        status,
        (
            f"Storyboard uses {unique_primitives} primitives and {unique_layouts} layouts "
            f"across {scene_count} scenes"
        ),
        remediation=(
            "Vary both the visual primitive and composition layout when the idea changes."
            if status != "pass"
            else None
        ),
        object_ids=[scene.scene_id for scene in snapshot.scenes] if status == "failure" else [],
        details={
            "primitives": str(unique_primitives),
            "layouts": str(unique_layouts),
            "longest_layout_run": str(longest_layout_run),
        },
    )


def _motion_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    total_duration = sum(scene.duration_seconds for scene in snapshot.scenes)
    static_scenes = [
        scene
        for scene in snapshot.scenes
        if scene.duration_seconds >= 4 and len(set(scene.motion_beats)) < 2
    ]
    static_duration = sum(scene.duration_seconds for scene in static_scenes)
    ratio = static_duration / total_duration if total_duration else 0.0
    if ratio > 0.60:
        status: QualityStatus = "failure"
    elif ratio > 0.35:
        status = "warning"
    else:
        status = "pass"
    return _check(
        "static-motion-budget",
        "motion",
        status,
        f"Long scenes with fewer than two animation beats occupy {ratio:.0%} of runtime",
        remediation=(
            "Add typed setup, reveal, transform, or emphasis beats to long static scenes."
            if status != "pass"
            else None
        ),
        object_ids=[scene.scene_id for scene in static_scenes],
        details={"static_runtime_ratio": f"{ratio:.3f}"},
    )


def _scene_starts(snapshot: CreativeQualityInput) -> list[float]:
    starts: list[float] = []
    elapsed = 0.0
    for scene in snapshot.scenes:
        starts.append(elapsed)
        elapsed += scene.duration_seconds
    return starts


def _cold_open_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    scene = snapshot.scenes[0]
    beat_count = len(set(scene.motion_beats))
    planned_duration = (
        snapshot.retention.cold_open_duration_seconds
        if snapshot.retention is not None
        else scene.duration_seconds
    )
    duration = max(scene.duration_seconds, planned_duration)
    first_beat = (
        snapshot.retention.events[0].scheduled_at_seconds
        if snapshot.retention is not None
        else duration / max(1, beat_count)
    )
    if duration > 7 or first_beat > 3.5:
        status: QualityStatus = "failure"
    elif duration > 5 or first_beat > 2:
        status = "warning"
    else:
        status = "pass"
    return _check(
        "cold-open-timing",
        "engagement",
        status,
        (
            f"Cold open plan/scene duration is {planned_duration:g}/{scene.duration_seconds:g}s; "
            "its first declared visual beat is "
            f"{'scheduled' if snapshot.retention is not None else 'estimated'} at "
            f"{first_beat:.1f}s"
        ),
        remediation=(
            "Trim the cold open to five seconds or less and schedule a concrete typed visual "
            "event within the first two seconds."
            if status != "pass"
            else None
        ),
        object_ids=[scene.scene_id] if status != "pass" else [],
        details={
            "duration_seconds": f"{duration:.2f}",
            "planned_duration_seconds": f"{planned_duration:.2f}",
            "scene_duration_seconds": f"{scene.duration_seconds:.2f}",
            "declared_motion_beats": str(beat_count),
            "first_visual_beat_seconds": f"{first_beat:.2f}",
            "timing_source": "retention-plan" if snapshot.retention is not None else "derived",
            "timing_scale": (
                f"{snapshot.retention.timing_scale:.3f}"
                if snapshot.retention is not None
                else "1.000"
            ),
        },
    )


def _beat_cadence_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    warning_limit, failure_limit = {
        "measured": (5.0, 7.0),
        "brisk": (4.0, 6.0),
        "high-retention": (5.0, 5.0),
    }[snapshot.pacing]
    warnings: list[str] = []
    failures: list[str] = []
    maximum_interval = 0.0
    runtime_delta = 0.0
    if snapshot.retention is not None:
        scene_runtime = sum(scene.duration_seconds for scene in snapshot.scenes)
        runtime_delta = abs(snapshot.retention.total_duration_seconds - scene_runtime)
        if runtime_delta > 1:
            failures.append(snapshot.retention.plan_version_id)
        elif runtime_delta > 0.25:
            warnings.append(snapshot.retention.plan_version_id)
        failure_limit = min(failure_limit, snapshot.retention.max_attention_gap_seconds)
        previous_time = 0.0
        for event in snapshot.retention.events:
            interval = event.scheduled_at_seconds - previous_time
            maximum_interval = max(maximum_interval, interval)
            if interval > failure_limit:
                failures.append(event.event_id)
            elif interval > warning_limit:
                warnings.append(event.event_id)
            previous_time = event.scheduled_at_seconds
        final_interval = snapshot.retention.total_duration_seconds - previous_time
        maximum_interval = max(maximum_interval, final_interval)
        if final_interval > failure_limit:
            failures.append(snapshot.scenes[-1].scene_id)
        elif final_interval > warning_limit:
            warnings.append(snapshot.scenes[-1].scene_id)
    else:
        for scene in snapshot.scenes[1:]:
            interval = scene.duration_seconds / max(1, len(set(scene.motion_beats)))
            maximum_interval = max(maximum_interval, interval)
            if interval > failure_limit:
                failures.append(scene.scene_id)
            elif interval > warning_limit:
                warnings.append(scene.scene_id)
    status: QualityStatus = "failure" if failures else "warning" if warnings else "pass"
    offenders = failures + warnings
    return _check(
        "visual-beat-cadence",
        "engagement",
        status,
        (
            f"Maximum estimated interval between declared visual beats is "
            f"{maximum_interval:.1f}s for {snapshot.pacing} pacing"
        ),
        remediation=(
            "Add a purposeful reveal, transform, comparison, or emphasis beat; do not add "
            "motion that competes with comprehension."
            if offenders
            else None
        ),
        object_ids=offenders,
        details={
            "warning_limit_seconds": f"{warning_limit:.1f}",
            "failure_limit_seconds": f"{failure_limit:.1f}",
            "maximum_interval_seconds": f"{maximum_interval:.2f}",
            "plan_scene_runtime_delta_seconds": f"{runtime_delta:.2f}",
            "timing_source": "retention-plan" if snapshot.retention is not None else "derived",
            "timing_scale": (
                f"{snapshot.retention.timing_scale:.3f}"
                if snapshot.retention is not None
                else "1.000"
            ),
        },
    )


def _dead_air_static_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    warning_ids: list[str] = []
    failure_ids: list[str] = []
    longest_caption_gap = 0.0
    previous_end = 0.0
    for cue in sorted(snapshot.captions, key=lambda item: (item.start_seconds, item.end_seconds)):
        gap = max(0.0, cue.start_seconds - previous_end)
        longest_caption_gap = max(longest_caption_gap, gap)
        if gap > 3:
            failure_ids.append(cue.cue_id)
        elif gap > 1.5:
            warning_ids.append(cue.cue_id)
        previous_end = max(previous_end, cue.end_seconds)
    starts = _scene_starts(snapshot)
    for scene, start in zip(snapshot.scenes, starts, strict=True):
        beat_count = len(set(scene.motion_beats))
        if beat_count < 2 and scene.duration_seconds > 7:
            failure_ids.append(scene.scene_id)
        elif beat_count < 2 and scene.duration_seconds > 4:
            warning_ids.append(scene.scene_id)
        end = start + scene.duration_seconds
        caption_overlap = any(
            cue.start_seconds < end and cue.end_seconds > start for cue in snapshot.captions
        )
        if (
            not scene.narration.strip()
            and not caption_overlap
            and beat_count < 2
            and scene.duration_seconds >= 3
        ):
            failure_ids.append(scene.scene_id)

    failure_ids = list(dict.fromkeys(failure_ids))
    warning_ids = [item for item in dict.fromkeys(warning_ids) if item not in failure_ids]
    status: QualityStatus = "failure" if failure_ids else "warning" if warning_ids else "pass"
    offenders = failure_ids + warning_ids
    return _check(
        "dead-air-static-stretches",
        "engagement",
        status,
        (
            f"Longest internal caption gap is {longest_caption_gap:.1f}s; "
            f"{len(offenders)} static or silent stretch(es) need attention"
            if offenders
            else "No long caption gaps or under-directed static stretches were detected"
        ),
        remediation=(
            "Close unexplained caption gaps or add a purposeful visual beat. Preserve quiet "
            "holds when they support comprehension."
            if offenders
            else None
        ),
        object_ids=offenders,
        details={"longest_internal_caption_gap_seconds": f"{longest_caption_gap:.2f}"},
    )


def _rehook_payoff_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    if snapshot.retention is not None:
        total_duration = snapshot.retention.total_duration_seconds
        rehooks = [event for event in snapshot.retention.events if event.event_kind == "re-hook"]
        final_payoffs = [
            event for event in snapshot.retention.events if event.event_kind == "final-payoff"
        ]
        evidence_payoffs = [
            event for event in snapshot.retention.events if event.event_kind == "evidence-payoff"
        ]
        valid_plan_rehook = next(
            (
                event
                for event in rehooks
                if 0.35 <= event.scheduled_at_seconds / total_duration <= 0.65
            ),
            None,
        )
        final_payoff = final_payoffs[-1] if final_payoffs else None
        final_position = (
            final_payoff.scheduled_at_seconds / total_duration if final_payoff else None
        )
        valid_final = final_position is not None and 0.75 <= final_position <= 1.0
        plan_status: QualityStatus = (
            "pass"
            if valid_plan_rehook is not None and valid_final and evidence_payoffs
            else "warning"
        )
        plan_offenders: list[str] = []
        if valid_plan_rehook is None:
            plan_offenders.extend(event.event_id for event in rehooks)
        if not valid_final:
            plan_offenders.extend(event.event_id for event in final_payoffs)
        if not evidence_payoffs or not plan_offenders and plan_status != "pass":
            plan_offenders.append(snapshot.retention.plan_version_id)
        plan_offenders = list(dict.fromkeys(plan_offenders))
        return _check(
            "rehook-payoff-placement",
            "engagement",
            plan_status,
            (
                "Retention plan schedules a midpoint re-hook plus evidence and final payoffs"
                if plan_status == "pass"
                else "Retention plan is missing a midpoint re-hook, evidence payoff, or final payoff"
            ),
            remediation=(
                "Schedule a truthful re-hook at 35–65%, an evidence payoff, and the promised "
                "final payoff after 75% without withholding essential context."
                if plan_status != "pass"
                else None
            ),
            object_ids=plan_offenders,
            details={
                "rehook_runtime_position": (
                    f"{valid_plan_rehook.scheduled_at_seconds / total_duration:.3f}"
                    if valid_plan_rehook is not None
                    else "missing"
                ),
                "final_payoff_runtime_position": (
                    f"{final_position:.3f}" if final_position is not None else "missing"
                ),
                "evidence_payoff_count": str(len(evidence_payoffs)),
                "timing_source": "retention-plan",
            },
        )

    declared_rehooks = [
        scene.scene_id for scene in snapshot.scenes if scene.engagement_role == "rehook"
    ]
    declared_payoffs = [
        scene.scene_id for scene in snapshot.scenes if scene.engagement_role == "payoff"
    ]
    return _check(
        "rehook-payoff-placement",
        "engagement",
        "warning",
        "No validated retention plan is available; scene positions and labels cannot verify "
        "re-hook or payoff timing",
        remediation=(
            "Generate and validate an evidence-locked retention plan with explicitly scheduled "
            "re-hook, evidence-payoff, and final-payoff events. Legacy scene labels remain "
            "advisory and are never treated as proof of placement."
        ),
        details={
            "timing_source": "missing-retention-plan",
            "declared_rehook_scene_ids": ",".join(declared_rehooks) or "none",
            "declared_payoff_scene_ids": ",".join(declared_payoffs) or "none",
            "legacy_scene_roles_accepted": "false",
        },
    )


def _hook_integrity_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    first = snapshot.scenes[0]
    retention_hook = snapshot.retention.cold_open_text if snapshot.retention is not None else ""
    hook_text = " ".join(
        filter(
            None,
            (
                snapshot.cover.headline,
                snapshot.cover.subtitle or "",
                retention_hook,
                first.title,
                first.on_screen_text,
                first.narration,
            ),
        )
    )
    matched = [
        pattern.pattern for pattern in _MANIPULATIVE_HOOK_PATTERNS if pattern.search(hook_text)
    ]
    concrete_words = len(_words(f"{first.on_screen_text} {first.narration}"))
    missing_provenance = first.factual and (not first.citation or not first.evidence_label)
    dishonest_plan = bool(
        snapshot.retention is not None
        and (not snapshot.retention.truth_up_front or snapshot.retention.deceptive_withholding)
    )
    if matched or dishonest_plan:
        status: QualityStatus = "failure"
    elif concrete_words < 6 or missing_provenance:
        status = "warning"
    else:
        status = "pass"
    return _check(
        "hook-integrity",
        "engagement",
        status,
        (
            f"Hook contains {len(matched)} manipulative or proof-overclaim pattern(s)"
            if matched
            else "Retention plan declares deceptive withholding or hides the truth up front"
            if dishonest_plan
            else "Hook makes a concrete, evidence-labeled promise without engagement bait"
            if status == "pass"
            else "Hook needs a more concrete or visibly sourced promise"
        ),
        remediation=(
            "State the real mechanism or result immediately, remove bait and proof language, "
            "and preserve uncertainty and scope."
            if status != "pass"
            else None
        ),
        object_ids=[snapshot.cover.cover_id, first.scene_id] if status != "pass" else [],
        details={
            "matched_pattern_count": str(len(matched)),
            "hook_words": str(concrete_words),
            "factual_hook_missing_provenance": str(missing_provenance).lower(),
            "truth_up_front": (
                str(snapshot.retention.truth_up_front).lower()
                if snapshot.retention is not None
                else "not-declared"
            ),
            "deceptive_withholding": (
                str(snapshot.retention.deceptive_withholding).lower()
                if snapshot.retention is not None
                else "not-declared"
            ),
        },
    )


def _caption_timing_accessibility_check(
    snapshot: CreativeQualityInput,
) -> CreativeQualityCheck:
    if not snapshot.captions:
        return _check(
            "caption-timing-accessibility",
            "captions",
            "warning",
            "No caption cues are available for timing review",
            remediation="Generate reviewed caption cues before preview approval.",
        )
    warnings: list[str] = []
    failures: list[str] = []
    shortest = math.inf
    longest = 0.0
    previous: CreativeCaptionInput | None = None
    for cue in sorted(snapshot.captions, key=lambda item: (item.start_seconds, item.end_seconds)):
        duration = cue.end_seconds - cue.start_seconds
        shortest = min(shortest, duration)
        longest = max(longest, duration)
        if duration < 0.5 or duration > 10:
            failures.append(cue.cue_id)
        elif duration < MIN_CAPTION_DURATION_SECONDS or duration > 7:
            warnings.append(cue.cue_id)
        if previous is not None and cue.start_seconds < previous.end_seconds:
            failures.extend([previous.cue_id, cue.cue_id])
        if previous is None or cue.end_seconds > previous.end_seconds:
            previous = cue
    failures = list(dict.fromkeys(failures))
    warnings = [item for item in dict.fromkeys(warnings) if item not in failures]
    status: QualityStatus = "failure" if failures else "warning" if warnings else "pass"
    offenders = failures + warnings
    return _check(
        "caption-timing-accessibility",
        "captions",
        status,
        (
            f"Caption cues range from {shortest:.1f}s to {longest:.1f}s"
            if status == "pass"
            else f"{len(offenders)} caption cue(s) are too brief, too long, or overlap"
        ),
        remediation=(
            "Keep cues between 0.8 and 7 seconds, remove overlaps, then recheck reading speed "
            "and line breaks."
            if offenders
            else None
        ),
        object_ids=offenders,
        details={
            "shortest_cue_seconds": f"{shortest:.2f}",
            "longest_cue_seconds": f"{longest:.2f}",
        },
    )


def _motion_intensity_flashing_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    warnings: list[str] = []
    failures: list[str] = []
    maximum_flash_rate = 0.0
    intensities = [scene.motion_intensity for scene in snapshot.scenes]
    energetic_run = _longest_run(intensities)
    for scene in snapshot.scenes:
        unique_beats = set(scene.motion_beats)
        cue_count = sum(bool(_FLASH_CUE.search(beat)) for beat in unique_beats)
        inferred_rate = cue_count / scene.duration_seconds
        flash_rate = max(scene.flash_events_per_second, inferred_rate)
        maximum_flash_rate = max(maximum_flash_rate, flash_rate)
        beat_interval = scene.duration_seconds / max(1, len(unique_beats))
        explicit_strobe = any("strobe" in beat.casefold() for beat in scene.motion_beats)
        if flash_rate > 3:
            failures.append(scene.scene_id)
        elif flash_rate > 1 or explicit_strobe:
            warnings.append(scene.scene_id)
        elif scene.motion_intensity == "energetic" and beat_interval < 1:
            warnings.append(scene.scene_id)
    if energetic_run >= 3:
        warnings.extend(
            scene.scene_id for scene in snapshot.scenes if scene.motion_intensity == "energetic"
        )
    failures = list(dict.fromkeys(failures))
    warnings = [item for item in dict.fromkeys(warnings) if item not in failures]
    status: QualityStatus = "failure" if failures else "warning" if warnings else "pass"
    offenders = failures + warnings
    return _check(
        "motion-intensity-flashing",
        "accessibility",
        status,
        (
            f"Maximum declared or inferred flashing rate is {maximum_flash_rate:.2f}/s; "
            f"longest energetic run is {energetic_run} scene(s)"
        ),
        remediation=(
            "Remove strobe or rapid flash cues, break up sustained energetic motion, and "
            "verify rendered luminance changes before approval."
            if offenders
            else None
        ),
        object_ids=offenders,
        details={
            "maximum_flash_events_per_second": f"{maximum_flash_rate:.3f}",
            "longest_energetic_scene_run": str(energetic_run),
        },
    )


def _chart_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    charts = [scene for scene in snapshot.scenes if "chart" in scene.primitive.casefold()]
    offenders: list[str] = []
    omissions: dict[str, str] = {}
    for scene in charts:
        missing: list[str] = []
        if not scene.x_axis_label:
            missing.append("x-axis")
        if not scene.y_axis_label:
            missing.append("y-axis")
        if not scene.units:
            missing.append("units")
        if not scene.labels or len(scene.labels) != len(scene.series):
            missing.append("point labels")
        if missing:
            offenders.append(scene.scene_id)
            omissions[scene.scene_id] = ", ".join(missing)
    status: QualityStatus = "failure" if offenders else "pass"
    return _check(
        "chart-context",
        "data-visualization",
        status,
        (
            f"{len(offenders)} chart scene(s) omit axes, units, or labels"
            if offenders
            else "Charts provide axes, units, and labels"
            if charts
            else "No chart scenes to evaluate"
        ),
        remediation=(
            "Supply explicit x/y axis labels, units, and one label per plotted value."
            if offenders
            else None
        ),
        object_ids=offenders,
        details=omissions,
    )


def _citation_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    offenders: list[str] = []
    if snapshot.cover.factual and (
        not snapshot.cover.citation or _INTERNAL_ID.search(snapshot.cover.citation)
    ):
        offenders.append(snapshot.cover.cover_id)
    for scene in snapshot.scenes:
        citation = scene.citation or ""
        if scene.factual and (
            not citation.strip() or not scene.evidence_label or _INTERNAL_ID.search(citation)
        ):
            offenders.append(scene.scene_id)
    return _check(
        "citation-presentation",
        "provenance",
        "failure" if offenders else "pass",
        (
            f"{len(offenders)} factual surface(s) lack a human-readable citation and evidence label"
            if offenders
            else "Factual surfaces use human-readable citations and evidence labels"
        ),
        remediation=(
            "Show a short source/section locator and evidence label; keep manifest IDs internal."
            if offenders
            else None
        ),
        object_ids=offenders,
    )


def _caption_speed_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    warnings: list[str] = []
    failures: list[str] = []
    maximum = 0.0
    for cue in snapshot.captions:
        duration = cue.end_seconds - cue.start_seconds
        characters = len(re.sub(r"\s+", "", cue.text))
        cps = characters / duration
        maximum = max(maximum, cps)
        if cps > 25:
            failures.append(cue.cue_id)
        elif cps > MAX_CAPTION_CHARACTERS_PER_SECOND:
            warnings.append(cue.cue_id)
    status: QualityStatus = "failure" if failures else "warning" if warnings else "pass"
    offenders = failures + warnings
    return _check(
        "caption-reading-speed",
        "captions",
        status,
        (
            f"{len(offenders)} caption cue(s) exceed the reading-speed budget"
            if offenders
            else "Caption reading speed stays at or below 20 characters per second"
        ),
        remediation="Retiming or shorter phrase-aware cues are required." if offenders else None,
        object_ids=offenders,
        details={"maximum_characters_per_second": f"{maximum:.2f}"},
    )


def _estimated_line_count(text: str, width: int = 42) -> int:
    lines = text.splitlines() or [text]
    return sum(max(1, math.ceil(len(line.strip()) / width)) for line in lines)


def _caption_line_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    offenders = [cue.cue_id for cue in snapshot.captions if _estimated_line_count(cue.text) > 2]
    return _check(
        "caption-two-line-limit",
        "captions",
        "failure" if offenders else "pass",
        (
            f"{len(offenders)} caption cue(s) require more than two lines"
            if offenders
            else "Captions fit within two estimated mobile lines"
        ),
        remediation="Split cues at phrase boundaries before the third line." if offenders else None,
        object_ids=offenders,
    )


def _caption_orphan_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    offenders: list[str] = []
    for cue in snapshot.captions:
        lines = [line.strip() for line in cue.text.splitlines() if line.strip()]
        last_line_words = _words(lines[-1]) if lines else []
        duration = cue.end_seconds - cue.start_seconds
        single_cue_word = len(_words(cue.text)) == 1 and duration < 1.2
        dangling_line = len(lines) > 1 and len(last_line_words) == 1
        if single_cue_word or dangling_line:
            offenders.append(cue.cue_id)
    return _check(
        "caption-orphan-words",
        "captions",
        "warning" if offenders else "pass",
        (
            f"{len(offenders)} cue(s) leave a word isolated"
            if offenders
            else "Captions avoid isolated words"
        ),
        remediation="Rebalance phrase breaks so a final line or cue contains at least two words."
        if offenders
        else None,
        object_ids=offenders,
    )


def _hex_rgb(value: str) -> tuple[float, float, float]:
    return (
        int(value[1:3], 16) / 255,
        int(value[3:5], 16) / 255,
        int(value[5:7], 16) / 255,
    )


def _deuteranopia_distance(left: str, right: str) -> float:
    def simulated(value: str) -> tuple[float, float, float]:
        red, green, blue = _hex_rgb(value)
        return (
            0.367 * red + 0.861 * green - 0.228 * blue,
            0.280 * red + 0.673 * green + 0.047 * blue,
            -0.012 * red + 0.043 * green + 0.969 * blue,
        )

    a = simulated(left)
    b = simulated(right)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def _color_differentiation_check(snapshot: CreativeQualityInput) -> CreativeQualityCheck:
    warnings: list[str] = []
    failures: list[str] = []
    for scene in snapshot.scenes:
        colors = list(scene.color_encodings.values())
        if len(colors) < 2:
            continue
        closest = min(
            _deuteranopia_distance(left, right)
            for index, left in enumerate(colors)
            for right in colors[index + 1 :]
        )
        redundant = bool(scene.non_color_cues)
        if not redundant and closest < 0.16:
            failures.append(scene.scene_id)
        elif not redundant or closest < 0.16:
            warnings.append(scene.scene_id)
    status: QualityStatus = "failure" if failures else "warning" if warnings else "pass"
    offenders = failures + warnings
    return _check(
        "color-independent-differentiation",
        "accessibility",
        status,
        (
            f"{len(offenders)} scene(s) rely on color or use color-blind-confusable encodings"
            if offenders
            else "Data encodings have non-color differentiation"
        ),
        remediation=(
            "Add direct labels, shapes, patterns, or spatial grouping in addition to color."
            if offenders
            else None
        ),
        object_ids=offenders,
    )


def evaluate_creative_quality(snapshot: CreativeQualityInput) -> CreativeQualityResult:
    """Evaluate editorial and visual-quality proxies without changing export gates.

    The checks are deterministic authoring feedback. They intentionally remain
    separate from the provenance, rights, and media checks in ``qa.service``.
    """

    checks = [
        *_cover_checks(snapshot),
        _hook_integrity_check(snapshot),
        _cold_open_check(snapshot),
        _rehook_payoff_check(snapshot),
        _beat_cadence_check(snapshot),
        _dead_air_static_check(snapshot),
        _motion_intensity_flashing_check(snapshot),
        _internal_id_check(snapshot),
        _duplication_check(snapshot),
        _text_density_check(snapshot),
        _scene_title_check(snapshot),
        _diversity_check(snapshot),
        _motion_check(snapshot),
        _chart_check(snapshot),
        _citation_check(snapshot),
        _caption_speed_check(snapshot),
        _caption_timing_accessibility_check(snapshot),
        _caption_line_check(snapshot),
        _caption_orphan_check(snapshot),
        _color_differentiation_check(snapshot),
    ]
    status = _worst_status([check.status for check in checks])
    penalty = sum(
        (10 if check.status == "failure" else 4 if check.status == "warning" else 0)
        + min(10, len(check.object_ids))
        for check in checks
        if check.status != "pass"
    )
    return CreativeQualityResult(
        case_id=snapshot.case_id,
        status=status,
        score=max(0, 100 - penalty),
        checks=checks,
    )


def creative_input_from_manifests(
    storyboard: StoryboardManifest,
    script: ScriptManifest,
    captions: Sequence[CaptionCue],
    cover: CreativeCoverInput,
    *,
    case_id: str,
    topic_kind: Literal[
        "mechanism", "chart", "comparison", "timeline", "architecture", "other"
    ] = "other",
    pacing: PacingProfile = "brisk",
    retention_plan: RetentionPlan | None = None,
) -> CreativeQualityInput:
    """Normalize the current manifests into the creative-QA contract.

    Richer visual schemas can populate axis, motion, layout, and color metadata
    directly in ``CreativeQualityInput``. The adapter deliberately exposes the
    gaps in the V1 catch-all visual schema instead of inferring proof of quality.
    """

    segments = {segment.segment_id: segment for segment in script.segments}
    total_duration = max(
        (scene.start_time + scene.duration for scene in storyboard.scenes), default=0.0
    )
    caption_duration = max((cue.end for cue in captions), default=0.0)
    render_duration = caption_duration or total_duration
    scene_timing_scale = render_duration / total_duration if total_duration else 1.0
    retention: CreativeRetentionInput | None = None
    if retention_plan is not None:
        if retention_plan.script_version_id != script.version_id:
            raise ValueError("retention plan does not bind the current script")
        retention_timing_scale = (
            render_duration / retention_plan.cadence.total_duration_seconds
            if render_duration
            else 1.0
        )
        retention = CreativeRetentionInput(
            plan_version_id=retention_plan.version_id,
            timing_scale=retention_timing_scale,
            cold_open_duration_seconds=(
                retention_plan.cold_open.duration_seconds * retention_timing_scale
            ),
            cold_open_text=retention_plan.cold_open.text,
            truth_up_front=retention_plan.cold_open.truth_up_front,
            deceptive_withholding=retention_plan.cold_open.deceptive_withholding,
            total_duration_seconds=(
                retention_plan.cadence.total_duration_seconds * retention_timing_scale
            ),
            max_attention_gap_seconds=retention_plan.cadence.max_attention_gap_seconds,
            events=[
                CreativeRetentionEventInput(
                    event_id=event.event_id,
                    beat_id=event.beat_id,
                    scheduled_at_seconds=event.scheduled_at_seconds * retention_timing_scale,
                    event_kind=event.event_kind,
                )
                for event in retention_plan.attention_events
            ],
        )
    cadence_beats = (
        retention_plan.cadence.beats
        if retention_plan is not None
        and len(retention_plan.cadence.beats) == len(storyboard.scenes)
        else []
    )
    retention_events_by_beat: dict[str, list[str]] = {}
    if retention_plan is not None:
        for event in retention_plan.attention_events:
            retention_events_by_beat.setdefault(event.beat_id, []).append(
                f"{event.event_kind}:{event.device}"
            )
    scenes: list[CreativeSceneInput] = []
    for index, scene in enumerate(storyboard.scenes):
        linked_segments = [
            segments[segment_id]
            for segment_id in scene.script_segment_ids
            if segment_id in segments
        ]
        narration = " ".join(segment.text for segment in linked_segments)
        cadence_beat = cadence_beats[index] if cadence_beats else None
        engagement_role: EngagementRole
        if cadence_beat is not None:
            engagement_role = _CADENCE_ROLE_TO_ENGAGEMENT[cadence_beat.cadence_role]
        elif index == 0:
            engagement_role = "cold-open"
        elif any(segment.segment_type == "limitation" for segment in linked_segments):
            engagement_role = "limitation"
        elif scene.primitive in {"SourceReceipt", "EvidenceHighlight", "AnnotatedChart"}:
            engagement_role = "evidence"
        elif index == len(storyboard.scenes) - 1:
            engagement_role = "resolution"
        else:
            engagement_role = "mechanism"
        visual = scene.visual
        if isinstance(visual, VisualSpec):
            title = visual.title
            body = visual.body
            citation = scene.citation_label or visual.citation
            series = visual.series
            labels = visual.labels
            x_axis_label = None
            y_axis_label = None
            units = None
            color_encodings: dict[str, str] = {}
        elif isinstance(visual, AnnotatedChartVisual):
            title = scene.on_screen_text
            body = None
            citation = scene.citation_label
            series = [point.y for item in visual.series for point in item.points]
            labels = [format(point.x, "g") for item in visual.series for point in item.points]
            x_axis_label = visual.x_axis.label
            y_axis_label = visual.y_axis.label
            units = visual.y_axis.unit or visual.x_axis.unit
            theme_colors = {
                "accent": "#0072B2",
                "warning": "#E69F00",
                "citation": "#56B4E9",
                "danger": "#D55E00",
                "muted": "#777777",
            }
            color_encodings = {item.label: theme_colors[item.color] for item in visual.series}
        else:
            title = scene.on_screen_text
            body = None
            citation = scene.citation_label
            series = []
            labels = []
            x_axis_label = None
            y_axis_label = None
            units = None
            color_encodings = {}
        non_color_cues = ["direct-labels"] if labels else []
        if isinstance(visual, AnnotatedChartVisual) and visual.series:
            non_color_cues.append("series-labels")
        motion_beats = ["scene-enter"]
        if cadence_beat is not None:
            motion_beats.extend(retention_events_by_beat.get(cadence_beat.beat_id, []))
        motion_beats.append(f"{scene.motion}-content-reveal")
        motion_intensity = (
            _CADENCE_ENERGY_TO_MOTION[cadence_beat.energy]
            if cadence_beat is not None
            else scene.motion
        )
        scenes.append(
            CreativeSceneInput(
                scene_id=scene.scene_id,
                primitive=scene.primitive,
                layout=scene.layout,
                duration_seconds=scene.duration * scene_timing_scale,
                title=title,
                on_screen_text=scene.on_screen_text,
                body=body,
                narration=narration,
                factual=bool(scene.claim_ids),
                citation=citation,
                evidence_label=scene.evidence_label,
                series=series,
                labels=labels,
                x_axis_label=x_axis_label,
                y_axis_label=y_axis_label,
                units=units,
                motion_beats=list(dict.fromkeys(motion_beats)),
                engagement_role=engagement_role,
                motion_intensity=motion_intensity,
                color_encodings=color_encodings,
                non_color_cues=non_color_cues,
            )
        )
    normalized_captions = [
        CreativeCaptionInput(
            cue_id=str(cue.index),
            start_seconds=cue.start,
            end_seconds=cue.end,
            text=cue.text,
        )
        for cue in captions
    ]
    return CreativeQualityInput(
        case_id=case_id,
        topic_kind=topic_kind,
        storyboard_version_id=storyboard.version_id,
        script_version_id=script.version_id,
        pacing=pacing,
        cover=cover,
        scenes=scenes,
        captions=normalized_captions,
        retention=retention,
    )


__all__ = [
    "CreativeCaptionInput",
    "CreativeCoverInput",
    "CreativeRetentionEventInput",
    "CreativeRetentionInput",
    "CreativeQualityCheck",
    "CreativeQualityInput",
    "CreativeQualityResult",
    "CreativeSceneInput",
    "creative_input_from_manifests",
    "evaluate_creative_quality",
]
