from __future__ import annotations

import json
from pathlib import Path

from techshort.domain.models import (
    AssetManifest,
    ClaimsManifest,
    EvidenceManifest,
    ProjectManifest,
    QAReport,
    RenderManifest,
    ReviewLog,
    ScriptManifest,
    SourceIndex,
    StoryboardManifest,
)

MODELS = (
    ProjectManifest,
    SourceIndex,
    EvidenceManifest,
    ClaimsManifest,
    ScriptManifest,
    StoryboardManifest,
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
        (target / f"{name}.schema.json").write_text(
            json.dumps(model.model_json_schema(), indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
