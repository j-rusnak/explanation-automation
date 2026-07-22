from __future__ import annotations

from dataclasses import dataclass

from techshort.domain.creative import (
    BeatPlan,
    NarrativeBrief,
    RetentionCritique,
    RetentionPlan,
)
from techshort.domain.models import (
    AngleSelection,
    AnglesManifest,
    ClaimsManifest,
    EvidenceManifest,
    ScriptManifest,
)
from techshort.generation.editorial.general_foundation import (
    build_provider_neutral_beat_plan,
    build_provider_neutral_narrative_brief,
)
from techshort.generation.editorial.general_retention import (
    build_provider_neutral_retention_plan,
)
from techshort.generation.editorial.retention import critique_retention

__all__ = (
    "ProviderNeutralEditorialArtifacts",
    "build_provider_neutral_beat_plan",
    "build_provider_neutral_editorial_artifacts",
    "build_provider_neutral_narrative_brief",
    "build_provider_neutral_retention_plan",
)


@dataclass(frozen=True)
class ProviderNeutralEditorialArtifacts:
    """Deterministic editorial artifacts derived after provider normalization."""

    narrative_brief: NarrativeBrief
    beat_plan: BeatPlan
    retention_plan: RetentionPlan
    retention_critique: RetentionCritique


def build_provider_neutral_editorial_artifacts(
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
    angles: AnglesManifest,
    selection: AngleSelection,
    script: ScriptManifest,
) -> ProviderNeutralEditorialArtifacts:
    """Create the full deterministic editorial chain for manual or Codex output."""
    brief = build_provider_neutral_narrative_brief(claims, evidence, angles, selection, script)
    beat_plan = build_provider_neutral_beat_plan(brief, claims, evidence, angles, selection, script)
    retention_plan = build_provider_neutral_retention_plan(brief, beat_plan, script)
    retention_critique = critique_retention(retention_plan, brief, beat_plan, script)
    return ProviderNeutralEditorialArtifacts(
        narrative_brief=brief,
        beat_plan=beat_plan,
        retention_plan=retention_plan,
        retention_critique=retention_critique,
    )
