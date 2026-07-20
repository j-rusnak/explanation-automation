from __future__ import annotations

import math
import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from techshort.alignment.captions import CaptionCue
from techshort.domain.models import (
    AnnotatedChartVisual,
    ScriptManifest,
    StoryboardManifest,
    VisualSpec,
)

CREATIVE_QA_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

_INTERNAL_ID = re.compile(
    r"\b(?:claim|evidence|scene|segment|asset|render|review|source|script|storyboard)"
    r"[-_][a-z0-9][a-z0-9_.:-]*\b",
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


class CreativeQualityInput(_StrictQualityModel):
    schema_version: Literal["1.0.0"] = CREATIVE_QA_SCHEMA_VERSION
    case_id: str
    topic_kind: Literal["mechanism", "chart", "comparison", "timeline", "architecture", "other"]
    storyboard_version_id: str
    script_version_id: str
    cover: CreativeCoverInput
    scenes: list[CreativeSceneInput] = Field(min_length=1, max_length=120)
    captions: list[CreativeCaptionInput] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def object_ids_are_unique(self) -> CreativeQualityInput:
        scene_ids = [scene.scene_id for scene in self.scenes]
        cue_ids = [cue.cue_id for cue in self.captions]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("creative QA scene IDs must be unique")
        if len(cue_ids) != len(set(cue_ids)):
            raise ValueError("creative QA caption cue IDs must be unique")
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
        elif cps > 20:
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
        _internal_id_check(snapshot),
        _duplication_check(snapshot),
        _text_density_check(snapshot),
        _scene_title_check(snapshot),
        _diversity_check(snapshot),
        _motion_check(snapshot),
        _chart_check(snapshot),
        _citation_check(snapshot),
        _caption_speed_check(snapshot),
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
) -> CreativeQualityInput:
    """Normalize the current manifests into the creative-QA contract.

    Richer visual schemas can populate axis, motion, layout, and color metadata
    directly in ``CreativeQualityInput``. The adapter deliberately exposes the
    gaps in the V1 catch-all visual schema instead of inferring proof of quality.
    """

    segments = {segment.segment_id: segment for segment in script.segments}
    scenes: list[CreativeSceneInput] = []
    for scene in storyboard.scenes:
        narration = " ".join(
            segments[segment_id].text
            for segment_id in scene.script_segment_ids
            if segment_id in segments
        )
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
        scenes.append(
            CreativeSceneInput(
                scene_id=scene.scene_id,
                primitive=scene.primitive,
                layout=scene.layout,
                duration_seconds=scene.duration,
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
                motion_beats=["scene-enter", f"{scene.motion}-content-reveal"],
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
        cover=cover,
        scenes=scenes,
        captions=normalized_captions,
    )


__all__ = [
    "CreativeCaptionInput",
    "CreativeCoverInput",
    "CreativeQualityCheck",
    "CreativeQualityInput",
    "CreativeQualityResult",
    "CreativeSceneInput",
    "creative_input_from_manifests",
    "evaluate_creative_quality",
]
