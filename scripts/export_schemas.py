from __future__ import annotations

from pathlib import Path

from techshort.domain.creative import (
    BeatPlan,
    EditorialCritique,
    NarrativeBrief,
    RetentionCritique,
    RetentionPlan,
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
    RetentionPlan,
    RetentionCritique,
    StoryboardGuidance,
    VisualCritique,
    CreativeQualityInput,
    CreativeQualityResult,
    AssetManifest,
    ReviewLog,
    RenderManifest,
    QAReport,
)


def schema_filename(model: type) -> str:
    """Return the stable repository filename for a model's JSON Schema."""

    name = model.__name__.replace("Manifest", "-manifest").lower()
    return f"{name}.schema.json"


def export_schemas(target: Path = Path("schemas")) -> None:
    """Export every persisted or provider-facing model schema deterministically."""

    target.mkdir(exist_ok=True)
    for model in MODELS:
        atomic_write_json(target / schema_filename(model), model.model_json_schema())


def main() -> None:
    export_schemas()


if __name__ == "__main__":
    main()
