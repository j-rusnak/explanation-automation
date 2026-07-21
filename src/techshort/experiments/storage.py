from __future__ import annotations

import re
from pathlib import Path

from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.experiments.models import (
    EXPERIMENT_ID_PATTERN,
    ExperimentManifest,
    ExperimentReviewLog,
    ObservationLog,
    RecommendationLog,
)


class ExperimentStore:
    """Atomic validated storage constrained to one project's experiments directory."""

    def __init__(self, project_store: ProjectStore, experiment_id: str) -> None:
        if not EXPERIMENT_ID_PATTERN.fullmatch(experiment_id):
            raise ValueError("experiment ID has an invalid format")
        self.project_store = project_store
        self.experiment_id = experiment_id
        self.root = project_store.path(f"experiments/{experiment_id}")

    @property
    def manifest_path(self) -> Path:
        return self.root / "experiment.json"

    @property
    def observations_path(self) -> Path:
        return self.root / "observations.json"

    @property
    def recommendations_path(self) -> Path:
        return self.root / "recommendations.json"

    @property
    def reviews_path(self) -> Path:
        return self.root / "reviews.json"

    def initialize(self, manifest: ExperimentManifest) -> ExperimentManifest:
        if manifest.experiment_id != self.experiment_id:
            raise ValueError("manifest belongs to a different experiment")
        if self.manifest_path.exists():
            existing = self.manifest()
            if existing != manifest:
                raise FileExistsError(
                    "experiment already exists; create a new deterministic experiment ID"
                )
            if self.observations_path.exists():
                self.observations()
            else:
                atomic_write_model(
                    self.observations_path,
                    ObservationLog(experiment_id=self.experiment_id),
                )
            if self.recommendations_path.exists():
                self.recommendations()
            else:
                atomic_write_model(
                    self.recommendations_path,
                    RecommendationLog(experiment_id=self.experiment_id),
                )
            if self.reviews_path.exists():
                self.reviews()
            else:
                atomic_write_model(
                    self.reviews_path,
                    ExperimentReviewLog(experiment_id=self.experiment_id),
                )
            return existing
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_model(self.manifest_path, manifest)
        atomic_write_model(
            self.observations_path,
            ObservationLog(experiment_id=self.experiment_id),
        )
        atomic_write_model(
            self.recommendations_path,
            RecommendationLog(experiment_id=self.experiment_id),
        )
        atomic_write_model(
            self.reviews_path,
            ExperimentReviewLog(experiment_id=self.experiment_id),
        )
        return manifest

    def manifest(self) -> ExperimentManifest:
        return load_model(self.manifest_path, ExperimentManifest)

    def save_manifest(self, manifest: ExperimentManifest) -> None:
        if manifest.experiment_id != self.experiment_id:
            raise ValueError("manifest belongs to a different experiment")
        atomic_write_model(self.manifest_path, manifest)

    def observations(self) -> ObservationLog:
        return load_model(self.observations_path, ObservationLog)

    def save_observations(self, observations: ObservationLog) -> None:
        if observations.experiment_id != self.experiment_id:
            raise ValueError("observations belong to a different experiment")
        atomic_write_model(self.observations_path, observations)

    def recommendations(self) -> RecommendationLog:
        return load_model(self.recommendations_path, RecommendationLog)

    def save_recommendations(self, recommendations: RecommendationLog) -> None:
        if recommendations.experiment_id != self.experiment_id:
            raise ValueError("recommendations belong to a different experiment")
        atomic_write_model(self.recommendations_path, recommendations)

    def reviews(self) -> ExperimentReviewLog:
        return load_model(self.reviews_path, ExperimentReviewLog)

    def save_reviews(self, reviews: ExperimentReviewLog) -> None:
        if reviews.experiment_id != self.experiment_id:
            raise ValueError("reviews belong to a different experiment")
        atomic_write_model(self.reviews_path, reviews)


def list_experiment_ids(project_store: ProjectStore) -> list[str]:
    root = project_store.path("experiments")
    if not root.is_dir():
        return []
    return sorted(
        item.name
        for item in root.iterdir()
        if item.is_dir()
        and re.fullmatch(EXPERIMENT_ID_PATTERN, item.name)
        and (item / "experiment.json").is_file()
    )
