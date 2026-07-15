from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from techshort.domain.models import ProjectManifest, ReviewLog, now_utc

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


def atomic_write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump_json(indent=2, exclude_none=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
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
        if self.manifest_path.exists():
            return self.project()
        for directory in self.DIRECTORIES:
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        manifest = ProjectManifest(project_id=f"project-{self.slug}", slug=self.slug, title=title)
        atomic_write_model(self.manifest_path, manifest)
        atomic_write_model(self.root / "reviews/review-log.json", ReviewLog())
        return manifest

    def project(self) -> ProjectManifest:
        return load_model(self.manifest_path, ProjectManifest)

    def save_project(self, manifest: ProjectManifest) -> None:
        manifest.modified_at = now_utc()
        atomic_write_model(self.manifest_path, manifest)

    def path(self, relative: str) -> Path:
        return within(self.root, self.root / relative)

    def invalidate_from(self, stage: str, reason: str) -> ProjectManifest:
        order = ["claims", "script", "storyboard", "rights", "final"]
        project = self.project()
        start = order.index(stage)
        for gate in order[start:]:
            setattr(project.approvals, gate, "stale")
            if gate not in project.stale_artifacts:
                project.stale_artifacts.append(gate)
        project.downstream_valid = False
        project.status = f"stale: {reason}"
        self.save_project(project)
        return project
