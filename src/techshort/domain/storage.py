from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from techshort.domain.models import ProjectManifest, ReviewLog, SourceIndex, now_utc

T = TypeVar("T", bound=BaseModel)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def validate_slug(slug: str) -> str:
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("project slug must contain lowercase letters, digits, or hyphens")
    return slug


def sanitize_filename(name: str) -> str:
    name = Path(name).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(" .-")
    if not safe or safe in {".", ".."}:
        raise ValueError("filename has no safe characters")
    return safe[:180]


def within(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    resolved = candidate.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"path escapes project root: {candidate}")
    return resolved


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def atomic_write_model(path: Path, model: BaseModel) -> None:
    atomic_write_text(path, model.model_dump_json(indent=2, exclude_none=True) + "\n")


def atomic_copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with source.open("rb") as source_handle, os.fdopen(fd, "wb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_model(path: Path, model_type: type[T]) -> T:
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


class ProjectStore:
    DIRECTORIES = (
        "sources/originals",
        "sources/extracted",
        "evidence",
        "claims",
        "script",
        "storyboard",
        "assets/originals",
        "assets/generated",
        "audio",
        "captions",
        "reviews",
        "renders/previews",
        "renders/final",
        "export",
    )

    def __init__(self, projects_root: Path, slug: str) -> None:
        self.projects_root = projects_root.resolve()
        self.slug = validate_slug(slug)
        self.root = within(self.projects_root, self.projects_root / slug)

    @property
    def manifest_path(self) -> Path:
        return self.root / "project.json"

    def initialize(self, title: str) -> ProjectManifest:
        for directory in self.DIRECTORIES:
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        if self.manifest_path.exists():
            manifest = self.project()
            if manifest.slug != self.slug:
                raise ValueError("project manifest slug does not match its directory")
            self._repair_active_source_metadata(manifest)
        else:
            manifest = ProjectManifest(
                project_id=f"project-{self.slug}", slug=self.slug, title=title
            )
            atomic_write_model(self.manifest_path, manifest)
        review_path = self.root / "reviews/review-log.json"
        if review_path.exists():
            load_model(review_path, ReviewLog)
        else:
            atomic_write_model(review_path, ReviewLog())
        return manifest

    def _repair_active_source_metadata(self, manifest: ProjectManifest) -> None:
        index_path = self.root / "sources/source-index.json"
        if not index_path.exists():
            return
        source_index = load_model(index_path, SourceIndex)
        source_ids = [source.source_id for source in source_index.sources]
        selected = manifest.active_source_id or source_index.active_source_id
        if selected is None and len(source_ids) == 1:
            selected = source_ids[0]
        if selected is None or selected not in source_ids:
            return
        changed_manifest = manifest.active_source_id != selected
        changed_index = source_index.active_source_id != selected
        if changed_manifest:
            manifest.active_source_id = selected
            self.save_project(manifest)
        if changed_index:
            source_index.active_source_id = selected
            atomic_write_model(index_path, source_index)

    def project(self) -> ProjectManifest:
        return load_model(self.manifest_path, ProjectManifest)

    def save_project(self, manifest: ProjectManifest) -> None:
        manifest.modified_at = now_utc()
        atomic_write_model(self.manifest_path, manifest)

    def path(self, relative: str) -> Path:
        return within(self.root, self.root / relative)

    def invalidate_from(self, stage: str, reason: str) -> ProjectManifest:
        order = ["claims", "script", "storyboard", "rights", "final"]
        if stage not in order:
            raise ValueError(f"unknown invalidation stage: {stage}")
        project = self.project()
        start = order.index(stage)
        for gate in order[start:]:
            setattr(project.approvals, gate, "stale")
            if gate not in project.stale_artifacts:
                project.stale_artifacts.append(gate)
        project.downstream_valid = False
        project.dependency_hashes.pop("final_approval", None)
        project.status = f"stale: {reason}"
        self.save_project(project)
        review_path = self.root / "reviews/review-log.json"
        if review_path.exists():
            log = load_model(review_path, ReviewLog)
            affected_types = {
                "claims": {
                    "claim",
                    "script-segment",
                    "scene",
                    "asset-rights",
                    "rights",
                    "final",
                },
                "script": {"script-segment", "scene", "asset-rights", "rights", "final"},
                "storyboard": {"scene", "asset-rights", "rights", "final"},
                "rights": {"asset-rights", "rights", "final"},
                "final": {"final"},
            }[stage]
            changed = False
            for review in log.reviews:
                if (
                    review.decision == "approve"
                    and review.object_type in affected_types
                    and review.invalidated_at is None
                ):
                    review.invalidated_at = now_utc()
                    review.invalidation_reason = reason
                    changed = True
            if changed:
                atomic_write_model(review_path, log)
        return project
