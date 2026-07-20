from __future__ import annotations

from techshort.domain.creative import (
    BeatPlan,
    NarrativeBrief,
    SceneGuidance,
    StoryboardGuidance,
    derive_creative_id,
)
from techshort.domain.models import ScriptManifest


def build_rolling_shutter_storyboard_guidance(
    brief: NarrativeBrief,
    plan: BeatPlan,
    script: ScriptManifest,
) -> StoryboardGuidance:
    if plan.narrative_brief_version_id != brief.version_id:
        raise ValueError("beat plan does not bind the narrative brief")
    if script.angle != brief.angle or script.claims_version_id != brief.claims_version_id:
        raise ValueError("script does not bind the narrative brief")
    scenes = [
        SceneGuidance(
            scene_key=f"scene-guidance-{beat.order + 1:02d}",
            order=beat.order,
            beat_id=beat.beat_id,
            layout_family=beat.layout_family,
            primitive_hint=beat.primitive_hint,
            on_screen_text=beat.on_screen_text,
            visual_direction=beat.visual_guidance,
            animation_beats=beat.animation_beats,
            claim_ids=beat.claim_ids,
            evidence_span_ids=beat.evidence_span_ids,
        )
        for beat in plan.beats
    ]
    payload: dict[str, object] = {
        "narrative_brief_version_id": brief.version_id,
        "beat_plan_version_id": plan.version_id,
        "script_version_id": script.version_id,
        "angle": brief.angle,
        "factual_locks": brief.factual_locks,
        "scenes": scenes,
    }
    payload["version_id"] = derive_creative_id("visual-plan", payload)
    return StoryboardGuidance.model_validate(payload)
