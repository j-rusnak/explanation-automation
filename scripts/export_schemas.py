from __future__ import annotations

from pathlib import Path

from techshort.domain.creative import (
    BeatPlan,
    EditorialCritique,
    NarrativeBrief,
    StoryboardGuidance,
    VisualCritique,
)
from techshort.domain.models import (
    AngleSelection,
    AnglesManifest,
    AssetManifest,
    ClaimCritiqueReport,
    ClaimsManifest,
    CoverManifest,
    CoverSelection,
    EvidenceManifest,
    ProjectManifest,
    QAReport,
    RenderManifest,
    ReviewLog,
    ScriptManifest,
    SourceDocument,
    SourceIndex,
    StoryboardManifest,
)
from techshort.domain.storage import atomic_write_json
from techshort.qa.creative import CreativeQualityInput, CreativeQualityResult

MODELS = (
    ProjectManifest,
    SourceDocument,
    SourceIndex,
    EvidenceManifest,
    ClaimCritiqueReport,
    ClaimsManifest,
    AnglesManifest,
    AngleSelection,
    ScriptManifest,
    StoryboardManifest,
    CoverManifest,
    CoverSelection,
    NarrativeBrief,
    BeatPlan,
    EditorialCritique,
    StoryboardGuidance,
    VisualCritique,
    CreativeQualityInput,
    CreativeQualityResult,
    AssetManifest,
    ReviewLog,
    RenderManifest,
    QAReport,
)


def main() -> None:
    target = Path("schemas")
    target.mkdir(exist_ok=True)
    for model in MODELS:
        name = model.__name__.replace("Manifest", "-manifest").lower()
        atomic_write_json(target / f"{name}.schema.json", model.model_json_schema())


if __name__ == "__main__":
    main()
