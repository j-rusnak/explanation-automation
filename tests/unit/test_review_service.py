from __future__ import annotations

from pathlib import Path

import pytest

from techshort.domain.hashing import sha256_file
from techshort.domain.models import (
    AngleKind,
    AnglesManifest,
    Asset,
    AssetManifest,
    ClaimsManifest,
    EvidenceManifest,
    QACheck,
    QAReport,
    ReviewLog,
    ReviewStatus,
    ScriptManifest,
    SourceIndex,
    StoryboardManifest,
    derive_script_version_id,
)
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.generation import (
    fixture_claims,
    fixture_script,
    fixture_storyboard,
    generate_angles,
    generate_fixture_covers,
    select_angle,
    select_cover,
)
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
    edit_claim,
    edit_scene,
    edit_script_segment,
    final_review_hash,
    has_current_approval,
    note_asset,
    note_claim,
    reject_claim,
)
from techshort.review.service import REQUIRED_FINAL_QA_CHECKS

FIXTURE = Path("examples/rolling-shutter/rolling-shutter.md")


def _claims_store(tmp_path: Path, slug: str = "review") -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", slug)
    store.initialize("Review")
    ingest_source(store, FIXTURE)
    fixture_claims(store)
    return store


def _script_store(
    tmp_path: Path,
    slug: str = "script-review",
    angle: AngleKind = "everyday-mechanism",
) -> ProjectStore:
    store = _claims_store(tmp_path, slug)
    approve_claims(store, "reviewer")
    generate_angles(store, "fixture")
    select_angle(store, angle)
    fixture_script(store, angle)
    return store


def _storyboard_store(
    tmp_path: Path,
    slug: str = "story-review",
    angle: AngleKind = "everyday-mechanism",
) -> ProjectStore:
    store = _script_store(tmp_path, slug, angle)
    approve_script(store, "reviewer")
    fixture_storyboard(store)
    generate_fixture_covers(store)
    select_cover(store, "cover-scanline")
    return store


def test_reviewed_artifact_snapshot_binds_narration_and_transcript_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _storyboard_store(tmp_path, "narration-snapshot")
    narration = tmp_path / "narration.wav"
    transcript = tmp_path / "narration.txt"
    narration.write_bytes(b"audio bytes")
    transcript.write_text("approved narration", encoding="utf-8")
    monkeypatch.setattr("techshort.review.service.active_audio", lambda _store: narration)
    monkeypatch.setattr(
        "techshort.review.service.active_transcript",
        lambda _store: ("approved narration", transcript),
    )

    before = current_artifact_hashes(store)
    transcript.write_text("changed narration", encoding="utf-8")
    after = current_artifact_hashes(store)

    assert before["narration-audio"] == after["narration-audio"]
    assert before["narration-transcript"] != after["narration-transcript"]


def test_unused_legacy_source_does_not_block_current_evidence_snapshot(tmp_path: Path) -> None:
    store = _storyboard_store(tmp_path, "unused-legacy-source")
    index_path = store.path("sources/source-index.json")
    source_index = load_model(index_path, SourceIndex)
    current = source_index.sources[0]
    legacy = current.model_copy(
        update={
            "source_id": "source-unused-legacy",
            "local_path": "sources/originals/unused-legacy.md",
            "section_metadata_hash": None,
        }
    )
    store.path(legacy.local_path).write_bytes(store.path(current.local_path).read_bytes())
    store.path(f"sources/extracted/{legacy.source_id}.txt").write_bytes(
        store.path(f"sources/extracted/{current.source_id}.txt").read_bytes()
    )
    source_index.sources.append(legacy)
    atomic_write_model(index_path, source_index)

    hashes = current_artifact_hashes(store)

    assert f"source:{current.source_id}" in hashes
    assert f"source:{legacy.source_id}" not in hashes
    assert "retention_plan" in hashes
    assert "retention_critique" in hashes


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


def test_review_rejects_numbers_and_units_absent_from_approved_evidence(
    tmp_path: Path,
) -> None:
    claim_store = _claims_store(tmp_path, "claim-number-bypass")
    claims = load_model(claim_store.path("claims/claims.json"), ClaimsManifest)
    claim = claims.claims[0]
    edit_claim(claim_store, claim.claim_id, claim.text + " It runs at 9999 Hz.", "reviewer")
    with pytest.raises(ValueError, match="unsupported number, unit, or DOI"):
        approve_claim(claim_store, claim.claim_id, "reviewer")

    script_store = _script_store(tmp_path, "script-number-bypass")
    script = load_model(script_store.path("script/script.json"), ScriptManifest)
    segment = script.segments[0]
    edit_script_segment(
        script_store,
        segment.segment_id,
        segment.text + " The offset is 9999 px.",
        "reviewer",
    )
    with pytest.raises(ValueError, match="unsupported number, unit, or DOI"):
        approve_script_segment(script_store, segment.segment_id, "reviewer")


def test_claim_edit_archives_and_activates_a_content_derived_version(
    tmp_path: Path,
) -> None:
    store = _claims_store(tmp_path, "claim-edit-version")
    approve_claims(store, "reviewer")
    path = store.path("claims/claims.json")
    before = load_model(path, ClaimsManifest)
    previous_bytes = path.read_bytes()
    critique_path = store.path("claims/critique.json")
    critique_bytes = critique_path.read_bytes()
    assert "claims_critique" in store.project().active_versions
    reviews_before = load_model(store.path("reviews/review-log.json"), ReviewLog)

    edited = edit_claim(
        store,
        before.claims[0].claim_id,
        before.claims[0].text + " Within this example.",
        "reviewer",
    )

    after = load_model(path, ClaimsManifest)
    assert after.version_id != before.version_id
    assert after.version_id.startswith("claims-")
    project = store.project()
    assert project.active_versions["claims"] == after.version_id
    assert "claims_critique" not in project.active_versions
    assert "claims_critique" in project.stale_artifacts
    assert critique_path.read_bytes() == critique_bytes
    assert store.path(f"claims/versions/{before.version_id}.json").read_bytes() == previous_bytes
    reviews_after = load_model(store.path("reviews/review-log.json"), ReviewLog)
    assert len(reviews_after.reviews) == len(reviews_before.reviews) + 1
    assert reviews_after.reviews[-1].decision == "edit"
    assert reviews_after.reviews[-1].object_id == edited.claim_id


def test_script_segment_actions_and_claims_version_dependency(tmp_path: Path) -> None:
    store = _script_store(tmp_path)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    for segment in script.segments:
        approve_script_segment(store, segment.segment_id, "reviewer")
    first = script.segments[0]
    assert store.project().approvals.script == ReviewStatus.APPROVED
    assert has_current_approval(store, "script-segment", first.segment_id)

    script_path = store.path("script/script.json")
    previous_version = script.version_id
    previous_bytes = script_path.read_bytes()
    reviews_before = load_model(store.path("reviews/review-log.json"), ReviewLog)
    edit_script_segment(store, first.segment_id, first.text + " Clearly.", "reviewer")
    edited_script = load_model(script_path, ScriptManifest)
    assert edited_script.version_id != previous_version
    assert edited_script.version_id.startswith("script-")
    assert edited_script.version_id == derive_script_version_id(
        edited_script.claims_version_id,
        edited_script.angles_version_id,
        edited_script.angle_selection_id,
        edited_script.angle,
        edited_script.segments,
    )
    assert store.project().active_versions["script"] == edited_script.version_id
    assert store.path(f"script/versions/{previous_version}.json").read_bytes() == previous_bytes
    reviews_after = load_model(store.path("reviews/review-log.json"), ReviewLog)
    assert len(reviews_after.reviews) == len(reviews_before.reviews) + 1
    assert reviews_after.reviews[-1].decision == "edit"
    assert not has_current_approval(store, "script-segment", first.segment_id)
    assert store.project().approvals.script == ReviewStatus.STALE

    mismatch = _script_store(tmp_path, "script-mismatch")
    mismatch_path = mismatch.path("script/script.json")
    mismatched_script = load_model(mismatch_path, ScriptManifest)
    mismatched_script.claims_version_id = "claims-not-active"
    atomic_write_model(mismatch_path, mismatched_script)
    with pytest.raises(ValueError, match="different claims version"):
        approve_script(mismatch, "reviewer")


def test_script_review_rejects_tampered_angle_claim_links(tmp_path: Path) -> None:
    store = _script_store(tmp_path, "angle-claim-tamper")
    angles_path = store.path("script/angles.json")
    angles = load_model(angles_path, AnglesManifest)
    selected = next(
        candidate for candidate in angles.candidates if candidate.angle == "everyday-mechanism"
    )
    selected.central_claim_ids = ["claim-fabricated"]
    atomic_write_model(angles_path, angles)

    with pytest.raises(ValueError, match="content does not match its version ID"):
        approve_script(store, "reviewer")


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

    storyboard_path = store.path("storyboard/storyboard.json")
    previous_version = storyboard.version_id
    previous_bytes = storyboard_path.read_bytes()
    reviews_before = load_model(store.path("reviews/review-log.json"), ReviewLog)
    edit_scene(
        store,
        first.scene_id,
        {"on_screen_text": "A clearer reviewed title"},
        "reviewer",
    )
    edited_storyboard = load_model(storyboard_path, StoryboardManifest)
    assert edited_storyboard.version_id != previous_version
    assert edited_storyboard.version_id.startswith("storyboard-")
    assert store.project().active_versions["storyboard"] == edited_storyboard.version_id
    assert store.path(f"storyboard/versions/{previous_version}.json").read_bytes() == previous_bytes
    reviews_after = load_model(store.path("reviews/review-log.json"), ReviewLog)
    assert len(reviews_after.reviews) == len(reviews_before.reviews) + 1
    assert reviews_after.reviews[-1].decision == "edit"
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


def test_storyboard_review_rejects_fabricated_labels_citations_and_receipts(
    tmp_path: Path,
) -> None:
    citation_store = _storyboard_store(tmp_path, "fake-scene-citation")
    storyboard = load_model(citation_store.path("storyboard/storyboard.json"), StoryboardManifest)
    scene = storyboard.scenes[0]
    visual = {
        "title": "Legacy visual citation",
        "citation": "doi-10.9999-fabricated",
    }
    edit_scene(
        citation_store,
        scene.scene_id,
        {"primitive": "KineticText", "visual": visual},
        "reviewer",
    )
    with pytest.raises(ValueError, match="fabricated visual citation"):
        approve_scene(citation_store, scene.scene_id, "reviewer")

    label_store = _storyboard_store(tmp_path, "fake-scene-label")
    storyboard = load_model(label_store.path("storyboard/storyboard.json"), StoryboardManifest)
    scene = storyboard.scenes[0]
    edit_scene(label_store, scene.scene_id, {"evidence_label": "MEASURED"}, "reviewer")
    with pytest.raises(ValueError, match="evidence label"):
        approve_scene(label_store, scene.scene_id, "reviewer")

    receipt_store = _storyboard_store(
        tmp_path,
        "fake-evidence-highlight",
        "surprising-result",
    )
    storyboard = load_model(receipt_store.path("storyboard/storyboard.json"), StoryboardManifest)
    receipt = next(item for item in storyboard.scenes if item.primitive == "EvidenceHighlight")
    visual = receipt.visual.model_dump(mode="json")
    visual["evidence_id"] = "evidence-fabricated"
    edit_scene(receipt_store, receipt.scene_id, {"visual": visual}, "reviewer")
    with pytest.raises(ValueError, match="requires evidence cited by its claims"):
        approve_scene(receipt_store, receipt.scene_id, "reviewer")

    legacy_store = _storyboard_store(tmp_path, "fake-legacy-source-receipt")
    storyboard = load_model(legacy_store.path("storyboard/storyboard.json"), StoryboardManifest)
    receipt = storyboard.scenes[0]
    edit_scene(
        legacy_store,
        receipt.scene_id,
        {
            "primitive": "SourceReceipt",
            "visual": {
                "title": "Legacy source receipt",
                "body": "Rows capture different moments.",
                "evidence_id": "evidence-fabricated",
            },
        },
        "reviewer",
    )
    with pytest.raises(ValueError, match="SourceReceipt scene .* requires evidence"):
        approve_scene(legacy_store, receipt.scene_id, "reviewer")


def test_storyboard_review_checks_typed_chart_values_against_claim_evidence(
    tmp_path: Path,
) -> None:
    store = _storyboard_store(
        tmp_path,
        "typed-chart-provenance",
        "engineering-tradeoff",
    )
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    chart = next(item for item in storyboard.scenes if item.primitive == "ChartReveal")
    visual = chart.visual.model_dump(mode="json")
    visual["series"][0]["points"][1]["y"] = 9999
    edit_scene(store, chart.scene_id, {"visual": visual}, "reviewer")

    with pytest.raises(ValueError, match="unsupported number, unit, or DOI: 9999"):
        approve_scene(store, chart.scene_id, "reviewer")


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

    assets_path = store.path("assets/asset-manifest.json")
    previous_version = load_model(assets_path, AssetManifest).version_id
    previous_bytes = assets_path.read_bytes()
    reviews_before = load_model(store.path("reviews/review-log.json"), ReviewLog)
    edit_asset(store, asset.asset_id, {"creator": "Local design team"}, "reviewer")
    edited_assets = load_model(assets_path, AssetManifest)
    assert edited_assets.version_id != previous_version
    assert edited_assets.version_id.startswith("assets-")
    assert store.project().active_versions["assets"] == edited_assets.version_id
    assert store.path(f"assets/versions/{previous_version}.json").read_bytes() == previous_bytes
    reviews_after = load_model(store.path("reviews/review-log.json"), ReviewLog)
    assert len(reviews_after.reviews) == len(reviews_before.reviews) + 1
    assert reviews_after.reviews[-1].decision == "edit"
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
        checks=[
            QACheck(check_id=check_id, status="pass", message="verified")
            for check_id in sorted(REQUIRED_FINAL_QA_CHECKS)
        ],
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

    project.active_versions["final_render"] = "render-derived-after-approval"
    project.dependency_hashes["final_render_output"] = "a" * 64
    project.dependency_hashes["final_render_dependencies"] = "b" * 64
    store.save_project(project)
    assert has_current_approval(store, "final", project.project_id)

    project.width = 720
    store.save_project(project)
    with pytest.raises(ValueError, match="QA report does not match current artifact"):
        final_review_hash(store)
    project.width = 1080
    store.save_project(project)

    source_index = store.path("sources/source-index.json")
    source_index.write_text(source_index.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="QA report does not match current artifact"):
        final_review_hash(store)


def test_final_approval_refuses_a_failed_qa_report(tmp_path: Path) -> None:
    store = _storyboard_store(tmp_path, "failed-final-qa")
    approve_storyboard(store, "reviewer")
    approve_rights(store, "reviewer")
    preview = store.path("renders/previews/preview.mp4")
    preview.write_bytes(b"reviewed preview bytes")
    report = QAReport(
        project_id=store.project().project_id,
        checks=[],
        export_blockers=["Caption safe-zone failure"],
        artifact_hashes=current_artifact_hashes(store),
        media_path=preview.relative_to(store.root).as_posix(),
        media_hash=sha256_file(preview),
    )
    atomic_write_model(store.path("renders/previews/qa-report.json"), report)

    with pytest.raises(ValueError, match="QA report contains export blockers"):
        approve_final(store, "reviewer")
    assert store.project().approvals.final != ReviewStatus.APPROVED
