from __future__ import annotations

from techshort.domain.models import (
    ClaimsManifest,
    ScriptManifest,
    SourceIndex,
    StoryboardManifest,
)
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.providers.fixture import FixtureProvider


def fixture_claims(store: ProjectStore) -> ClaimsManifest:
    sources = load_model(store.path("sources/source-index.json"), SourceIndex)
    if not sources.sources:
        raise ValueError("ingest a source first")
    source = sources.sources[0]
    text = store.path(f"sources/extracted/{source.source_id}.txt").read_text(encoding="utf-8")
    provider = FixtureProvider()
    evidence = provider.evidence(text, source.source_id, source.content_hash)
    claims = provider.generate_claims(text, source.source_id, source.content_hash)
    atomic_write_model(store.path("evidence/evidence.json"), evidence)
    atomic_write_model(store.path("claims/claims.json"), claims)
    project = store.project()
    project.active_versions.update(evidence=evidence.version_id, claims=claims.version_id)
    store.save_project(project)
    return claims


def fixture_script(store: ProjectStore, angle: str = "everyday-mechanism") -> ScriptManifest:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    if not all(c.review_status == "approved" for c in claims.claims):
        raise ValueError("all claims must be approved before script generation")
    script = FixtureProvider().generate_script(claims, angle)
    atomic_write_model(store.path("script/script.json"), script)
    project = store.project()
    project.active_versions["script"] = script.version_id
    store.save_project(project)
    return script


def fixture_storyboard(store: ProjectStore) -> StoryboardManifest:
    script = load_model(store.path("script/script.json"), ScriptManifest)
    if not all(s.review_status == "approved" for s in script.segments):
        raise ValueError("all script segments must be approved before storyboard generation")
    storyboard = FixtureProvider().generate_storyboard(script)
    atomic_write_model(store.path("storyboard/storyboard.json"), storyboard)
    project = store.project()
    project.active_versions["storyboard"] = storyboard.version_id
    store.save_project(project)
    return storyboard
