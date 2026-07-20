from __future__ import annotations

from techshort.domain.models import PacingProfile, SafeZoneInsets
from techshort.domain.storage import ProjectStore

PACING_PROFILES: tuple[PacingProfile, ...] = ("measured", "brisk", "high-retention")


def set_pacing_profile(store: ProjectStore, pacing: PacingProfile) -> None:
    """Apply a reviewed render cadence and invalidate visuals derived from it."""

    if pacing not in PACING_PROFILES:
        raise ValueError("pacing must be measured, brisk, or high-retention")
    project = store.project()
    if project.pacing == pacing:
        return
    project = store.invalidate_from("storyboard", f"pacing changed to {pacing}")
    project.pacing = pacing
    store.save_project(project)


def set_safe_zone(store: ProjectStore, safe_zone: SafeZoneInsets) -> None:
    """Apply resolution-independent social-platform insets and stale visual review."""

    project = store.project()
    if project.safe_zone == safe_zone:
        return
    project = store.invalidate_from("storyboard", "platform safe zone changed")
    project.safe_zone = safe_zone
    store.save_project(project)
