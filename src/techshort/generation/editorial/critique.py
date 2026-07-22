from __future__ import annotations

import re
from collections import Counter
from typing import cast

from techshort.domain.creative import (
    BeatPlan,
    EditorialCritique,
    EditorialFinding,
    NarrativeBrief,
    StoryboardGuidance,
    VisualCritique,
    VisualFinding,
    derive_creative_id,
)
from techshort.domain.hashing import stable_hash
from techshort.domain.models import ScriptManifest

_WORD_RE = re.compile(r"[\w%]+(?:[-'][\w%]+)*", re.UNICODE)
_MANIPULATIVE_PHRASES = ("you won't believe", "wait until the end", "this proves")


def _normalized_words(text: str) -> list[str]:
    return [word.casefold() for word in _WORD_RE.findall(text)]


def critique_editorial(
    brief: NarrativeBrief,
    plan: BeatPlan,
    script: ScriptManifest,
) -> EditorialCritique:
    """Run deterministic editorial checks; this critique is advice, never proof."""
    findings: list[EditorialFinding] = []
    locks = {lock.claim_id: lock.claim_state_hash for lock in brief.factual_locks}
    if plan.narrative_brief_version_id != brief.version_id or plan.angle != brief.angle:
        findings.append(
            EditorialFinding(
                category="narrative-drift",
                severity="error",
                message="Beat plan does not bind the selected narrative brief and angle.",
            )
        )
    if {lock.claim_id: lock.claim_state_hash for lock in plan.factual_locks} != locks:
        findings.append(
            EditorialFinding(
                category="unsupported-claim",
                severity="error",
                message="Beat-plan factual locks differ from the approved narrative brief.",
            )
        )
    if script.angle != brief.angle:
        findings.append(
            EditorialFinding(
                category="narrative-drift",
                severity="error",
                message="Script angle differs from the selected narrative brief.",
            )
        )
    if (
        script.claims_version_id != brief.claims_version_id
        or script.angles_version_id != brief.angles_version_id
        or script.angle_selection_id != brief.angle_selection_id
    ):
        findings.append(
            EditorialFinding(
                category="narrative-drift",
                severity="error",
                message="Script provenance does not bind the narrative brief inputs.",
            )
        )
    for segment in script.segments:
        unknown = set(segment.claim_ids) - set(locks)
        if unknown:
            findings.append(
                EditorialFinding(
                    category="unsupported-claim",
                    severity="error",
                    message=f"Segment references unlocked claims: {sorted(unknown)}",
                    segment_id=segment.segment_id,
                )
            )
        if len(_normalized_words(segment.text)) > 42:
            findings.append(
                EditorialFinding(
                    category="excessive-text",
                    severity="warning",
                    message="Segment exceeds 42 spoken words and may overload one visual beat.",
                    segment_id=segment.segment_id,
                )
            )
        lowered = " ".join(segment.text.casefold().split())
        if any(phrase in lowered for phrase in _MANIPULATIVE_PHRASES):
            findings.append(
                EditorialFinding(
                    category="manipulative-language",
                    severity="error",
                    message="Segment contains manipulative or proof-overclaim language.",
                    segment_id=segment.segment_id,
                )
            )
    used_claims = {claim_id for segment in script.segments for claim_id in segment.claim_ids}
    missing_central = set(brief.central_claim_ids) - used_claims
    if missing_central:
        findings.append(
            EditorialFinding(
                category="missing-central-claim",
                severity="error",
                message=f"Script omits selected central claims: {sorted(missing_central)}",
            )
        )
    if not (set(brief.evidence_claim_ids) & used_claims):
        findings.append(
            EditorialFinding(
                category="missing-evidence",
                severity="error",
                message="Script never narrates the brief's visible evidence claims.",
            )
        )
    if not any(segment.segment_type == "limitation" for segment in script.segments):
        findings.append(
            EditorialFinding(
                category="missing-limitation",
                severity="error",
                message="Script has no explicit limitation segment.",
            )
        )
    if not script.segments or script.segments[0].segment_type != "hook":
        findings.append(
            EditorialFinding(
                category="weak-hook",
                severity="warning",
                message="Opening segment is not explicitly classified as a hook.",
            )
        )
    normalized = [" ".join(_normalized_words(segment.text)) for segment in script.segments]
    for text, count in Counter(normalized).items():
        if text and count > 1:
            findings.append(
                EditorialFinding(
                    category="repetition",
                    severity="warning",
                    message="The same narration appears in more than one segment.",
                )
            )
            break
    total_words = sum(len(_normalized_words(segment.text)) for segment in script.segments)
    low_words, high_words = brief.target_word_count
    if not low_words <= total_words <= high_words:
        findings.append(
            EditorialFinding(
                category="pacing",
                severity="warning",
                message=f"Script has {total_words} words; target is {low_words}–{high_words}.",
            )
        )
    total_duration = sum(segment.approximate_duration for segment in script.segments)
    low_time, high_time = brief.target_duration_seconds
    if not low_time <= total_duration <= high_time:
        findings.append(
            EditorialFinding(
                category="pacing",
                severity="warning",
                message=(
                    f"Script duration is {total_duration:g}s; "
                    f"target is {low_time:g}–{high_time:g}s."
                ),
            )
        )
    input_hash = stable_hash([brief, plan, script])
    payload: dict[str, object] = {
        "narrative_brief_version_id": brief.version_id,
        "beat_plan_version_id": plan.version_id,
        "script_version_id": script.version_id,
        "input_hash": input_hash,
        "findings": findings,
        "blocking": any(item.severity == "error" for item in findings),
    }
    payload["critique_id"] = derive_creative_id("editorial-critique", payload)
    return EditorialCritique.model_validate(payload)


def critique_visual(
    brief: NarrativeBrief,
    plan: BeatPlan,
    guidance: StoryboardGuidance,
    script: ScriptManifest | None = None,
) -> VisualCritique:
    """Flag deterministic visual-quality problems without executing scene content."""
    findings: list[VisualFinding] = []
    locks = {lock.claim_id for lock in brief.factual_locks}
    guidance_locks = {lock.claim_id: lock.claim_state_hash for lock in guidance.factual_locks}
    brief_locks = {lock.claim_id: lock.claim_state_hash for lock in brief.factual_locks}
    if (
        guidance.narrative_brief_version_id != brief.version_id
        or guidance.beat_plan_version_id != plan.version_id
        or guidance.angle != brief.angle
        or guidance_locks != brief_locks
    ):
        findings.append(
            VisualFinding(
                category="unsupported-visual-assertion",
                severity="error",
                message=(
                    "Storyboard guidance does not bind the current brief, beat plan, "
                    "and factual locks."
                ),
            )
        )
    for scene in guidance.scenes:
        unknown = set(scene.claim_ids) - locks
        if unknown:
            findings.append(
                VisualFinding(
                    category="unsupported-visual-assertion",
                    severity="error",
                    message=f"Scene references unlocked claims: {sorted(unknown)}",
                    scene_key=scene.scene_key,
                )
            )
        if len(_normalized_words(scene.on_screen_text)) > 10:
            findings.append(
                VisualFinding(
                    category="overlong-on-screen-text",
                    severity="warning",
                    message="On-screen text exceeds ten words.",
                    scene_key=scene.scene_key,
                )
            )
        if len(scene.animation_beats) < 2:
            findings.append(
                VisualFinding(
                    category="static-sequence",
                    severity="warning",
                    message="Scene has fewer than two intentional animation beats.",
                    scene_key=scene.scene_key,
                )
            )
        direction = " ".join(scene.visual_direction.casefold().split())
        if any(
            token in direction for token in ("show something", "generic graphic", "camera graphic")
        ):
            findings.append(
                VisualFinding(
                    category="weak-visual-metaphor",
                    severity="warning",
                    message="Visual direction is generic rather than mechanism-specific.",
                    scene_key=scene.scene_key,
                )
            )
        if scene.layout_family == "numeric-result" and not re.search(
            r"(?:%|\bms\b|\bseconds?\b|\bpercent\b)",
            f"{scene.on_screen_text} {scene.visual_direction}",
            re.IGNORECASE,
        ):
            findings.append(
                VisualFinding(
                    category="missing-units",
                    severity="error",
                    message="Numeric-result scene does not display a unit.",
                    scene_key=scene.scene_key,
                )
            )
    if not any(scene.layout_family == "evidence-receipt" for scene in guidance.scenes):
        findings.append(
            VisualFinding(
                category="missing-evidence-receipt",
                severity="error",
                message="Storyboard has no visible evidence-receipt scene.",
            )
        )
    if not any(scene.layout_family == "limitation" for scene in guidance.scenes):
        findings.append(
            VisualFinding(
                category="missing-limitation-card",
                severity="error",
                message="Storyboard has no dedicated limitation scene.",
            )
        )
    primitives = [scene.primitive_hint for scene in guidance.scenes]
    layouts = [scene.layout_family for scene in guidance.scenes]
    for index in range(max(0, len(primitives) - 2)):
        if len(set(primitives[index : index + 3])) == 1:
            findings.append(
                VisualFinding(
                    category="repeated-primitive",
                    severity="warning",
                    message="The same primitive is used for three consecutive scenes.",
                    scene_key=guidance.scenes[index].scene_key,
                )
            )
            break
    if layouts and Counter(layouts).most_common(1)[0][1] > len(layouts) / 2:
        findings.append(
            VisualFinding(
                category="repeated-layout",
                severity="warning",
                message="One layout family occupies more than half of the storyboard.",
            )
        )
    on_screen = [" ".join(_normalized_words(scene.on_screen_text)) for scene in guidance.scenes]
    if any(text and count > 1 for text, count in Counter(on_screen).items()):
        findings.append(
            VisualFinding(
                category="duplicated-narration",
                severity="warning",
                message="Identical on-screen copy is repeated across scenes.",
            )
        )
    if script is not None:
        for scene, segment in zip(guidance.scenes, script.segments, strict=False):
            if " ".join(_normalized_words(scene.on_screen_text)) == " ".join(
                _normalized_words(segment.text)
            ):
                findings.append(
                    VisualFinding(
                        category="duplicated-narration",
                        severity="warning",
                        message="Scene repeats its full narration as on-screen text.",
                        scene_key=scene.scene_key,
                    )
                )
    input_parts = cast(list[object], [brief, plan, guidance])
    if script is not None:
        input_parts.append(script)
    input_hash = stable_hash(input_parts)
    payload: dict[str, object] = {
        "narrative_brief_version_id": brief.version_id,
        "beat_plan_version_id": plan.version_id,
        "storyboard_guidance_version_id": guidance.version_id,
        "input_hash": input_hash,
        "findings": findings,
        "blocking": any(item.severity == "error" for item in findings),
    }
    payload["critique_id"] = derive_creative_id("visual-critique", payload)
    return VisualCritique.model_validate(payload)
