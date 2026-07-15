from __future__ import annotations

from pathlib import Path

import pytest

from techshort.domain.models import ProjectManifest
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model


def test_atomic_manifest_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "project.json"
    original = ProjectManifest(project_id="project-x", slug="x", title="X")
    atomic_write_model(path, original)
    assert load_model(path, ProjectManifest) == original


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path, "safe")
    store.initialize("Safe")
    with pytest.raises(ValueError, match="escapes"):
        store.path("../../secret")


def test_downstream_invalidation(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path, "safe")
    project = store.initialize("Safe")
    project.approvals.claims = "approved"
    project.approvals.script = "approved"
    project.approvals.storyboard = "approved"
    store.save_project(project)
    changed = store.invalidate_from("claims", "source changed")
    assert changed.approvals.claims == "stale"
    assert changed.approvals.script == "stale"
    assert changed.approvals.storyboard == "stale"
