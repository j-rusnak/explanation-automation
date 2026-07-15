from __future__ import annotations

from pathlib import Path

import pytest

from techshort.domain.hashing import sha256_file
from techshort.domain.models import (
    Asset,
    AssetManifest,
    ClaimsManifest,
    EvidenceManifest,
    QAReport,
    ReviewStatus,
    ScriptManifest,
    StoryboardManifest,
)
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.generation import fixture_claims, fixture_script, fixture_storyboard
from techshort.ingestion import ingest_source
from techshort.review import (
    approve_asset,
    approve_claim,
    approve_claims,
    approve_final,
    approve_rights,
    approve_scene,
    approve_script,
    approve_script_segment,
    approve_storyboard,
    current_artifact_hashes,
    edit_asset,
    edit_scene,
    edit_script_segment,
    final_review_hash,
    has_current_approval,
    note_asset,
    note_claim,
    reject_claim,
)

FIXTURE = Path("examples/rolling-shutter/rolling-shutter.md")


def _claims_store(tmp_path: Path, slug: str = "review") -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", slug)
    store.initialize("Review")
    ingest_source(store, FIXTURE)
    fixture_claims(store)
    return store


def _script_store(tmp_path: Path, slug: str = "script-review") -> ProjectStore:
    store = _claims_store(tmp_path, slug)
    approve_claims(store, "reviewer")
    fixture_script(store)
    return store


def _storyboard_store(tmp_path: Path, slug: str = "story-review") -> ProjectStore:
    store = _script_store(tmp_path, slug)
    approve_script(store, "reviewer")
    fixture_storyboard(store)
    return store


def test_claim_approval_hashes_are_current_and_notes_do_not_replace_decision(
    tmp_path: Path,
) -> None:
    store = _claims_store(tmp_path)
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    for claim in claims.claims:
        approve_claim(store, claim.claim_id, "reviewer")
    first = claims.claims[0]
    assert store.project().approvals.claims == ReviewStatus.APPROVED
    assert has_current_approval(store, "claim", first.claim_id)

    note_claim(store, first.claim_id, "Evidence wording checked.", "reviewer")
    assert has_current_approval(store, "claim", first.claim_id)

    reject_claim(store, first.claim_id, "reviewer", "Needs narrower scope")
    assert not has_current_approval(store, "claim", first.claim_id)
    assert store.project().approvals.claims == ReviewStatus.STALE


def test_claim_approval_rejects_wrong_evidence_version_and_source_hash(
    tmp_path: Path,
) -> None:
    version_store = _claims_store(tmp_path, "wrong-version")
    claims_path = version_store.path("claims/claims.json")
    claims = load_model(claims_path, ClaimsManifest)
    claims.evidence_version_id = "evidence-not-active"
    atomic_write_model(claims_path, claims)
    with pytest.raises(ValueError, match="different evidence version"):
        approve_claims(version_store, "reviewer")

    hash_store = _claims_store(tmp_path, "wrong-hash")
    evidence_path = hash_store.path("evidence/evidence.json")
    evidence = load_model(evidence_path, EvidenceManifest)
    evidence.evidence[0].source_hash = "0" * 64
    atomic_write_model(evidence_path, evidence)
    with pytest.raises(ValueError, match="stale source content hash"):
        approve_claims(hash_store, "reviewer")


def test_script_segment_actions_and_claims_version_dependency(tmp_path: Path) -> None:
    store = _script_store(tmp_path)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    for segment in script.segments:
        approve_script_segment(store, segment.segment_id, "reviewer")
    first = script.segments[0]
    assert store.project().approvals.script == ReviewStatus.APPROVED
    assert has_current_approval(store, "script-segment", first.segment_id)

    edit_script_segment(store, first.segment_id, first.text + " Clearly.", "reviewer")
    assert not has_current_approval(store, "script-segment", first.segment_id)
    assert store.project().approvals.script == ReviewStatus.STALE

    mismatch = _script_store(tmp_path, "script-mismatch")
    mismatch_path = mismatch.path("script/script.json")
    mismatched_script = load_model(mismatch_path, ScriptManifest)
    mismatched_script.claims_version_id = "claims-not-active"
    atomic_write_model(mismatch_path, mismatched_script)
    with pytest.raises(ValueError, match="different claims version"):
        approve_script(mismatch, "reviewer")


def test_scene_actions_validate_script_version_dependency_and_inert_edits(
    tmp_path: Path,
) -> None:
    store = _storyboard_store(tmp_path)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    for scene in storyboard.scenes:
        approve_scene(store, scene.scene_id, "reviewer")
    first = storyboard.scenes[0]
    assert store.project().approvals.storyboard == ReviewStatus.APPROVED
    assert has_current_approval(store, "scene", first.scene_id)

    edit_scene(
        store,
        first.scene_id,
        {"on_screen_text": "A clearer reviewed title"},
        "reviewer",
    )
    assert not has_current_approval(store, "scene", first.scene_id)
    assert store.project().approvals.storyboard == ReviewStatus.STALE

    with pytest.raises(ValueError, match="active content|executable markup"):
        edit_scene(
            store,
            first.scene_id,
            {"accessibility_description": '<img src=x onerror="alert(1)">'},
            "reviewer",
        )

    mismatch = _storyboard_store(tmp_path, "story-mismatch")
    mismatch_path = mismatch.path("storyboard/storyboard.json")
    mismatched_storyboard = load_model(mismatch_path, StoryboardManifest)
    mismatched_storyboard.script_version_id = "script-not-active"
    atomic_write_model(mismatch_path, mismatched_storyboard)
    with pytest.raises(ValueError, match="different script version"):
        approve_storyboard(mismatch, "reviewer")

    dependency = _storyboard_store(tmp_path, "story-dependency")
    dependency_path = dependency.path("storyboard/storyboard.json")
    stale_storyboard = load_model(dependency_path, StoryboardManifest)
    stale_storyboard.scenes[0].dependency_hash = "0" * 64
    atomic_write_model(dependency_path, stale_storyboard)
    with pytest.raises(ValueError, match="stale script dependency hash"):
        approve_storyboard(dependency, "reviewer")


def test_asset_actions_require_exact_file_hash_and_active_manifest_version(
    tmp_path: Path,
) -> None:
    store = _storyboard_store(tmp_path)
    approve_storyboard(store, "reviewer")
    asset_path = store.path("assets/originals/diagram.txt")
    asset_path.write_text("original deterministic diagram", encoding="utf-8")
    asset = Asset(
        asset_id="asset-diagram",
        asset_type="diagram-data",
        local_path=asset_path.relative_to(store.root).as_posix(),
        sha256=sha256_file(asset_path),
        origin="local project",
        creator="reviewer",
        license="user-owned",
        rights_status="user-owned",
        embedding_allowed=True,
    )
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    assets.version_id = "assets-v1"
    assets.assets.append(asset)
    atomic_write_model(store.path("assets/asset-manifest.json"), assets)
    project = store.project()
    project.active_versions["assets"] = assets.version_id
    store.save_project(project)

    for registered_asset in assets.assets:
        approve_asset(store, registered_asset.asset_id, "reviewer")
    assert store.project().approvals.rights == ReviewStatus.APPROVED
    assert has_current_approval(store, "asset", asset.asset_id)
    note_asset(store, asset.asset_id, "Ownership confirmed.", "reviewer")
    assert has_current_approval(store, "asset-rights", asset.asset_id)

    edit_asset(store, asset.asset_id, {"creator": "Local design team"}, "reviewer")
    assert not has_current_approval(store, "asset", asset.asset_id)
    assert store.project().approvals.rights == ReviewStatus.STALE

    mismatch = _storyboard_store(tmp_path, "asset-version")
    approve_storyboard(mismatch, "reviewer")
    mismatch_file = mismatch.path("assets/originals/diagram.txt")
    mismatch_file.write_text("diagram", encoding="utf-8")
    atomic_write_model(
        mismatch.path("assets/asset-manifest.json"),
        AssetManifest(
            version_id="assets-current",
            assets=[
                asset.model_copy(
                    update={
                        "local_path": mismatch_file.relative_to(mismatch.root).as_posix(),
                        "sha256": sha256_file(mismatch_file),
                    }
                )
            ],
        ),
    )
    project = mismatch.project()
    project.active_versions["assets"] = "assets-older"
    mismatch.save_project(project)
    with pytest.raises(ValueError, match="active assets version"):
        approve_rights(mismatch, "reviewer")

    hash_store = _storyboard_store(tmp_path, "asset-hash")
    approve_storyboard(hash_store, "reviewer")
    bad_file = hash_store.path("assets/originals/bad.txt")
    bad_file.write_text("actual", encoding="utf-8")
    atomic_write_model(
        hash_store.path("assets/asset-manifest.json"),
        AssetManifest(
            version_id="assets-bad",
            assets=[
                asset.model_copy(
                    update={
                        "local_path": bad_file.relative_to(hash_store.root).as_posix(),
                        "sha256": "0" * 64,
                    }
                )
            ],
        ),
    )
    hash_project = hash_store.project()
    hash_project.active_versions["assets"] = "assets-bad"
    hash_store.save_project(hash_project)
    with pytest.raises(ValueError, match="asset hash"):
        approve_rights(hash_store, "reviewer")


def test_final_review_digest_is_revalidatable_and_bound_to_qa_snapshot(
    tmp_path: Path,
) -> None:
    store = _storyboard_store(tmp_path, "final-review")
    approve_storyboard(store, "reviewer")
    approve_rights(store, "reviewer")
    preview = store.path("renders/previews/preview.mp4")
    preview.write_bytes(b"reviewed preview bytes")
    artifacts = current_artifact_hashes(store)
    report = QAReport(
        project_id=store.project().project_id,
        checks=[],
        export_blockers=[],
        artifact_hashes=artifacts,
        media_path=preview.relative_to(store.root).as_posix(),
        media_hash=sha256_file(preview),
    )
    atomic_write_model(store.path("renders/previews/qa-report.json"), report)

    expected = final_review_hash(store)
    approve_final(store, "reviewer")
    project = store.project()
    assert project.dependency_hashes["final_approval"] == expected
    assert has_current_approval(store, "final", project.project_id)

    source_index = store.path("sources/source-index.json")
    source_index.write_text(source_index.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="QA report does not match current artifact"):
        final_review_hash(store)
