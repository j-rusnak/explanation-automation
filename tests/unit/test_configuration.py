from __future__ import annotations

from pathlib import Path

import pytest

from techshort.configuration import set_pacing_profile, set_safe_zone
from techshort.domain.models import ReviewStatus, SafeZoneInsets
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


def test_safe_zone_is_bounded_and_invalidates_visual_review(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "safe-zone-test")
    store.initialize("Safe zone test")
    assert store.project().safe_zone == SafeZoneInsets()

    set_safe_zone(
        store,
        SafeZoneInsets(top=0.05, right=0.16, bottom=0.18, left=0.07),
    )

    assert store.project().safe_zone.right == 0.16
    assert store.project().approvals.storyboard == ReviewStatus.STALE
    with pytest.raises(ValueError, match="too little usable content"):
        SafeZoneInsets(top=0.22, right=0.1, bottom=0.2, left=0.1)
