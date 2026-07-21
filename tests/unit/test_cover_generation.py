from __future__ import annotations

from pathlib import Path

import pytest

from techshort.domain.models import StoryboardManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.generation import (
    fixture_claims,
    fixture_script,
    fixture_storyboard,
    generate_angles,
    select_angle,
)
from techshort.generation.design import (
    generate_fixture_covers,
    select_cover,
    selected_cover_payload,
)
from techshort.ingestion import ingest_source
from techshort.review import approve_claims, approve_script, edit_scene


def _storyboard_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "cover-design")
    store.initialize("Cover design")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "cover-reviewer")
    generate_angles(store, "fixture")
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "cover-reviewer")
    fixture_storyboard(store)
    return store


def test_fixture_cover_candidates_are_distinct_linked_and_selectable(tmp_path: Path) -> None:
    store = _storyboard_store(tmp_path)
    covers = generate_fixture_covers(store)

    assert len(covers.candidates) == 3
    assert len({item.headline for item in covers.candidates}) == 3
    assert len({item.layout for item in covers.candidates}) == 3
    assert all(item.claim_ids and item.evidence_ids for item in covers.candidates)
    proof_first = covers.candidates[0]
    assert proof_first.palette == "kinetic-pop"
    assert proof_first.headline == "One Frame Is Not One Instant"
    assert proof_first.hero.kind == "scanline"
    assert proof_first.hero.subject == "grid"

    selected = select_cover(store, "cover-scanline")
    payload = selected_cover_payload(store)
    assert payload["selected_candidate_id"] == "cover-scanline"
    assert selected.selection_id == store.project().active_versions["cover_selection"]


def test_cover_selection_fails_after_storyboard_changes(tmp_path: Path) -> None:
    store = _storyboard_store(tmp_path)
    generate_fixture_covers(store)
    select_cover(store, "cover-comparison")

    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    edit_scene(
        store,
        storyboard.scenes[0].scene_id,
        {"on_screen_text": "A changed visual headline"},
        "cover-reviewer",
    )

    with pytest.raises(ValueError, match="stale"):
        selected_cover_payload(store)
