from __future__ import annotations

from pathlib import Path

import pytest

from techshort.configuration import set_pacing_profile
from techshort.domain.models import ReviewStatus
from techshort.domain.storage import ProjectStore


def test_pacing_profile_defaults_to_high_retention_and_invalidates_visual_review(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path / "projects", "pacing-test")
    store.initialize("Pacing test")
    project = store.project()
    assert project.pacing == "high-retention"
    project.approvals.storyboard = ReviewStatus.APPROVED
    project.approvals.rights = ReviewStatus.APPROVED
    project.approvals.final = ReviewStatus.APPROVED
    store.save_project(project)

    set_pacing_profile(store, "brisk")

    updated = store.project()
    assert updated.pacing == "brisk"
    assert updated.approvals.storyboard == ReviewStatus.STALE
    assert updated.approvals.rights == ReviewStatus.STALE
    assert updated.approvals.final == ReviewStatus.STALE


def test_pacing_profile_rejects_unknown_values(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "pacing-test")
    store.initialize("Pacing test")
    with pytest.raises(ValueError, match="measured, brisk, or high-retention"):
        set_pacing_profile(store, "viral-chaos")  # type: ignore[arg-type]
