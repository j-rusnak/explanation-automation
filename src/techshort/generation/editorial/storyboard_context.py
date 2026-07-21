from __future__ import annotations

from techshort.domain.creative import (
    BeatPlan,
    NarrativeBrief,
    RetentionCritique,
    RetentionPlan,
)
from techshort.domain.models import ProjectManifest, ScriptManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.generation.editorial.retention import critique_retention
from techshort.prompts.editorial import RETENTION_PLAN_TEMPLATE


def build_storyboard_retention_context(
    store: ProjectStore,
    project: ProjectManifest,
    script: ScriptManifest,
) -> dict[str, object]:
    """Return a validated, prose-free schedule for generic storyboard providers."""
    artifact_paths = {
        "narrative_brief": store.path("script/narrative-brief.json"),
        "beat_plan": store.path("script/beat-plan.json"),
        "retention_plan": store.path("script/retention-plan.json"),
        "retention_critique": store.path("script/retention-critique.json"),
    }
    if any(not path.is_file() for path in artifact_paths.values()):
        raise ValueError(
            "manual and Codex storyboard generation requires current retention planning artifacts"
        )
    brief = load_model(artifact_paths["narrative_brief"], NarrativeBrief)
    beat_plan = load_model(artifact_paths["beat_plan"], BeatPlan)
    retention_plan = load_model(artifact_paths["retention_plan"], RetentionPlan)
    retention_critique = load_model(artifact_paths["retention_critique"], RetentionCritique)
    current_versions = {
        "narrative_brief": brief.version_id,
        "beat_plan": beat_plan.version_id,
        "retention_plan": retention_plan.version_id,
        "retention_critique": retention_critique.critique_id,
    }
    if any(project.active_versions.get(key) != value for key, value in current_versions.items()):
        raise ValueError("storyboard retention planning artifacts are stale")
    if (
        brief.claims_version_id != script.claims_version_id
        or brief.angle != script.angle
        or beat_plan.narrative_brief_version_id != brief.version_id
        or beat_plan.claims_version_id != script.claims_version_id
        or beat_plan.angle != script.angle
        or retention_plan.narrative_brief_version_id != brief.version_id
        or retention_plan.beat_plan_version_id != beat_plan.version_id
        or retention_plan.script_version_id != script.version_id
        or retention_plan.claims_version_id != script.claims_version_id
        or retention_plan.angle != script.angle
        or retention_critique.retention_plan_version_id != retention_plan.version_id
        or retention_critique.narrative_brief_version_id != brief.version_id
        or retention_critique.beat_plan_version_id != beat_plan.version_id
        or retention_critique.script_version_id != script.version_id
    ):
        raise ValueError("storyboard retention planning artifacts are stale")
    expected_critique = critique_retention(retention_plan, brief, beat_plan, script)
    if retention_critique != expected_critique:
        raise ValueError("storyboard retention critique no longer matches the current script")
    if retention_critique.blocking:
        messages = [
            finding.message
            for finding in retention_critique.findings
            if finding.severity == "error"
        ]
        raise ValueError(
            "retention critique blocks storyboard generation: " + "; ".join(messages[:3])
        )
    if (
        project.dependency_hashes.get("retention_plan_template")
        != RETENTION_PLAN_TEMPLATE.template_hash
        or project.dependency_hashes.get("retention_critique_input")
        != retention_critique.input_hash
    ):
        raise ValueError("storyboard retention planning dependencies are stale")
    if not (len(script.segments) == len(beat_plan.beats) == len(retention_plan.cadence.beats)):
        raise ValueError("storyboard retention cadence no longer matches the script")

    cadence_beats: list[dict[str, object]] = []
    for segment, planned_beat, cadence_beat in zip(
        script.segments,
        beat_plan.beats,
        retention_plan.cadence.beats,
        strict=True,
    ):
        if (
            planned_beat.beat_id != cadence_beat.beat_id
            or abs(planned_beat.approximate_duration - cadence_beat.duration_seconds) > 0.01
            or abs(segment.approximate_duration - cadence_beat.duration_seconds) > 0.01
        ):
            raise ValueError("storyboard retention cadence no longer matches the beat plan")
        cadence_beats.append(
            {
                "beat_id": cadence_beat.beat_id,
                "script_segment_id": segment.segment_id,
                "starts_at_seconds": cadence_beat.starts_at_seconds,
                "duration_seconds": cadence_beat.duration_seconds,
                "energy": cadence_beat.energy,
                "cadence_role": cadence_beat.cadence_role,
                "ends_with_forward_motion": cadence_beat.ends_with_forward_motion,
                "planned_role": planned_beat.role,
                "primitive_hint": planned_beat.primitive_hint,
                "layout_family": planned_beat.layout_family,
                "claim_ids": planned_beat.claim_ids,
                "evidence_span_ids": planned_beat.evidence_span_ids,
            }
        )

    return {
        "context_version": "1.0.0",
        "classification": "inert-validated-retention-schedule",
        "retention_plan_version_id": retention_plan.version_id,
        "retention_critique_id": retention_critique.critique_id,
        "script_version_id": script.version_id,
        "beat_plan_version_id": beat_plan.version_id,
        "cadence": {
            "total_duration_seconds": retention_plan.cadence.total_duration_seconds,
            "max_attention_gap_seconds": retention_plan.cadence.max_attention_gap_seconds,
            "beats": cadence_beats,
        },
        "cold_open": {
            "beat_id": retention_plan.cold_open.beat_id,
            "payoff_beat_id": retention_plan.cold_open.payoff_beat_id,
            "duration_seconds": retention_plan.cold_open.duration_seconds,
            "reveal_strategy": retention_plan.cold_open.reveal_strategy,
            "claim_ids": retention_plan.cold_open.claim_ids,
        },
        "curiosity_threads": [
            {
                "thread_id": thread.thread_id,
                "opened_at_beat_id": thread.opened_at_beat_id,
                "payoff_beat_id": thread.payoff_beat_id,
                "claim_ids": thread.claim_ids,
            }
            for thread in retention_plan.curiosity_threads
        ],
        "attention_events": [
            {
                "event_id": event.event_id,
                "beat_id": event.beat_id,
                "scheduled_at_seconds": event.scheduled_at_seconds,
                "event_kind": event.event_kind,
                "device": event.device,
                "claim_ids": event.claim_ids,
                "resolves_thread_ids": event.resolves_thread_ids,
            }
            for event in retention_plan.attention_events
        ],
        "evidence_payoff": {
            "beat_id": retention_plan.evidence_payoff_beat_id,
            "claim_ids": retention_plan.evidence_claim_ids,
        },
        "meaningful_limitation": {
            "beat_id": retention_plan.meaningful_limitation_beat_id,
            "claim_ids": retention_plan.meaningful_limitation_claim_ids,
        },
    }
