from __future__ import annotations

from pathlib import Path

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    AngleSelection,
    AnglesManifest,
    ClaimsManifest,
    CoverCandidate,
    CoverManifest,
    CoverSelection,
    EvidenceManifest,
    StoryboardManifest,
    derive_cover_manifest_id,
    derive_cover_selection_id,
)
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    load_model,
)


def _archive(store: ProjectStore, relative: str, version_id: str) -> None:
    current = store.path(relative)
    if not current.is_file():
        return
    versions = current.parent / "versions"
    destination = versions / f"{version_id}.json"
    current_hash = sha256_file(current)
    if destination.is_file() and sha256_file(destination) != current_hash:
        destination = versions / f"{version_id}-state-{current_hash[:12]}.json"
    if not destination.exists():
        atomic_copy_file(current, destination)


def _selected_angle(
    store: ProjectStore, claims: ClaimsManifest
) -> tuple[str, list[str], list[str]]:
    angles = load_model(store.path("script/angles.json"), AnglesManifest)
    selection = load_model(store.path("script/angle-selection.json"), AngleSelection)
    project = store.project()
    if (
        angles.claims_version_id != claims.version_id
        or project.active_versions.get("angles") != angles.version_id
        or selection.angles_version_id != angles.version_id
        or project.active_versions.get("angle_selection") != selection.selection_id
    ):
        raise ValueError("cover generation requires a current explicit angle selection")
    candidate = next(
        (item for item in angles.candidates if item.angle == selection.selected_angle), None
    )
    if candidate is None or stable_hash(candidate) != selection.selected_candidate_hash:
        raise ValueError("selected angle candidate is missing or has changed")
    claim_by_id = {claim.claim_id: claim for claim in claims.claims}
    missing = set(candidate.central_claim_ids) - claim_by_id.keys()
    if missing:
        raise ValueError("selected angle references missing claims: " + ", ".join(sorted(missing)))
    evidence_ids = list(
        dict.fromkeys(
            evidence_id
            for claim_id in candidate.central_claim_ids
            for evidence_id in claim_by_id[claim_id].evidence_span_ids
        )
    )
    return selection.selected_angle, candidate.central_claim_ids, evidence_ids


def _headlines(angle: str) -> tuple[str, str, str]:
    return {
        "surprising-result": (
            "Why Straight Lines Look Skewed",
            "The Camera Effect Hidden in One Frame",
            "A Straight Blade, Rebuilt as a Curve",
        ),
        "everyday-mechanism": (
            "One Frame Is Not One Instant",
            "How a Sensor Scans Time",
            "Why Motion Turns Into Skew",
        ),
        "engineering-tradeoff": (
            "Rolling vs Global Shutters",
            "The Timing Tradeoff Inside a Camera",
            "Two Shutters, Two Ways to Capture Time",
        ),
    }[angle]


def generate_fixture_covers(store: ProjectStore) -> CoverManifest:
    """Create three deterministic, evidence-linked cover candidates."""

    project = store.project()
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    if project.active_versions.get("storyboard") != storyboard.version_id:
        raise ValueError("cover generation requires the current storyboard")
    angle, claim_ids, evidence_ids = _selected_angle(store, claims)
    known_evidence = {item.evidence_id for item in evidence.evidence}
    if not evidence_ids or not set(evidence_ids).issubset(known_evidence):
        raise ValueError("cover candidates require resolvable selected-angle evidence")
    first, second, third = _headlines(angle)
    candidates = [
        CoverCandidate(
            candidate_id="cover-scanline",
            headline=first,
            subheadline="A moving subject is sampled row by row across time.",
            layout="split-hero",
            palette="kinetic-pop",
            hero={"kind": "scanline", "subject": "grid", "distortion": 0.72},
            claim_ids=claim_ids[:6],
            evidence_ids=evidence_ids[:6],
            accessibility_description=(
                "A straight grid and a scanline-skewed grid appear side by side."
            ),
        ),
        CoverCandidate(
            candidate_id="cover-comparison",
            headline=second,
            subheadline="The top and bottom of one image can represent different instants.",
            layout="editorial",
            palette="technical-editorial",
            hero={
                "kind": "comparison",
                "feature": "straight-edge",
                "before_label": "same instant",
                "after_label": "row-by-row scan",
            },
            claim_ids=claim_ids[:6],
            evidence_ids=evidence_ids[:6],
            accessibility_description=(
                "A straight edge is compared with the same edge skewed by sequential capture."
            ),
        ),
        CoverCandidate(
            candidate_id="cover-diagram",
            headline=third,
            subheadline="The image is assembled from samples captured at successive times.",
            layout="diagram-hero",
            palette="blueprint",
            hero={
                "kind": "diagram",
                "nodes": [
                    {"id": "rows", "label": "sensor rows", "x": 0.2, "y": 0.5},
                    {
                        "id": "time",
                        "label": "successive time",
                        "x": 0.5,
                        "y": 0.28,
                        "state": "active",
                    },
                    {"id": "frame", "label": "assembled frame", "x": 0.8, "y": 0.5},
                ],
                "edges": [
                    {"source": "rows", "target": "time", "label": "scan"},
                    {"source": "time", "target": "frame", "label": "assemble"},
                ],
            },
            claim_ids=claim_ids[:6],
            evidence_ids=evidence_ids[:6],
            accessibility_description=(
                "A diagram connects sensor rows through successive time to an assembled frame."
            ),
        ),
    ]
    version_id = derive_cover_manifest_id(storyboard.version_id, candidates)
    manifest = CoverManifest(
        version_id=version_id,
        storyboard_version_id=storyboard.version_id,
        candidates=candidates,
    )
    path = store.path("storyboard/covers.json")
    if path.is_file():
        previous = load_model(path, CoverManifest)
        _archive(store, "storyboard/covers.json", previous.version_id)
    atomic_write_model(path, manifest)
    store.invalidate_from("storyboard", "cover candidates regenerated")
    project = store.project()
    project.active_versions["covers"] = manifest.version_id
    project.active_versions.pop("cover_selection", None)
    project.dependency_hashes["covers"] = stable_hash(manifest)
    project.dependency_hashes.pop("cover_selection", None)
    project.stale_artifacts = [
        item for item in project.stale_artifacts if item not in {"covers", "cover_selection"}
    ]
    store.save_project(project)
    return manifest


def select_cover(store: ProjectStore, candidate_id: str) -> CoverSelection:
    covers = load_model(store.path("storyboard/covers.json"), CoverManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    project = store.project()
    if (
        covers.storyboard_version_id != storyboard.version_id
        or project.active_versions.get("covers") != covers.version_id
    ):
        raise ValueError("cover candidates are stale; regenerate them from the current storyboard")
    candidate = next(
        (item for item in covers.candidates if item.candidate_id == candidate_id), None
    )
    if candidate is None:
        raise ValueError(f"unknown cover candidate: {candidate_id}")
    candidate_hash = stable_hash(candidate)
    selection = CoverSelection(
        selection_id=derive_cover_selection_id(
            covers.version_id, candidate.candidate_id, candidate_hash
        ),
        cover_version_id=covers.version_id,
        selected_candidate_id=candidate.candidate_id,
        selected_candidate_hash=candidate_hash,
    )
    path = store.path("storyboard/cover-selection.json")
    if path.is_file():
        previous = load_model(path, CoverSelection)
        _archive(store, "storyboard/cover-selection.json", previous.selection_id)
    atomic_write_model(path, selection)
    store.invalidate_from("storyboard", f"cover selected: {candidate_id}")
    project = store.project()
    project.active_versions["cover_selection"] = selection.selection_id
    project.dependency_hashes["cover_selection"] = stable_hash(selection)
    project.stale_artifacts = [
        item for item in project.stale_artifacts if item != "cover_selection"
    ]
    store.save_project(project)
    return selection


def selected_cover_payload(store: ProjectStore) -> dict[str, object]:
    covers = load_model(store.path("storyboard/covers.json"), CoverManifest)
    selection = load_model(store.path("storyboard/cover-selection.json"), CoverSelection)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    project = store.project()
    candidate = next(
        (
            item
            for item in covers.candidates
            if item.candidate_id == selection.selected_candidate_id
        ),
        None,
    )
    if (
        candidate is None
        or covers.storyboard_version_id != storyboard.version_id
        or selection.cover_version_id != covers.version_id
        or selection.selected_candidate_hash != stable_hash(candidate)
        or project.active_versions.get("covers") != covers.version_id
        or project.active_versions.get("cover_selection") != selection.selection_id
    ):
        raise ValueError("selected cover is missing, stale, or hash-mismatched")
    return {
        "schema_version": "1.0.0",
        "selected_candidate_id": selection.selected_candidate_id,
        "candidates": [item.model_dump(mode="json") for item in covers.candidates],
    }


def cover_paths(store: ProjectStore) -> tuple[Path, Path]:
    return store.path("storyboard/covers.json"), store.path("storyboard/cover-selection.json")
