from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from scripts.export_schemas import MODELS, schema_filename
from techshort.audio.providers import NarrationSynthesisReceipt
from techshort.audio.sound_design import SoundDesignReceipt
from techshort.domain.creative import RetentionCritique, RetentionPlan
from techshort.experiments import (
    ExperimentManifest,
    ExperimentReviewLog,
    ObservationLog,
    RecommendationLog,
)
from techshort.publication.models import (
    HumanPublicationConsent,
    OrganicPackageRequest,
    OrganicPostMetadata,
    OrganicPublicationPackage,
)

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"


@pytest.mark.parametrize("model", MODELS, ids=lambda model: model.__name__)
def test_exported_schema_matches_current_model(model: type[BaseModel]) -> None:
    schema_path = SCHEMA_ROOT / schema_filename(model)

    assert schema_path.is_file(), f"run scripts/export_schemas.py to create {schema_path.name}"
    assert json.loads(schema_path.read_text(encoding="utf-8")) == model.model_json_schema()


def test_retention_artifacts_are_in_the_exported_schema_registry() -> None:
    assert RetentionPlan in MODELS
    assert RetentionCritique in MODELS


PERSISTED_WORKFLOW_MODELS = (
    NarrationSynthesisReceipt,
    SoundDesignReceipt,
    ExperimentManifest,
    ObservationLog,
    RecommendationLog,
    ExperimentReviewLog,
    OrganicPackageRequest,
    HumanPublicationConsent,
    OrganicPostMetadata,
    OrganicPublicationPackage,
)


@pytest.mark.parametrize("model", PERSISTED_WORKFLOW_MODELS, ids=lambda model: model.__name__)
def test_new_persisted_workflow_models_are_strict_and_exported(
    model: type[BaseModel],
) -> None:
    assert model in MODELS
    schema = model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"
