from __future__ import annotations

from uuid import uuid4

from techshort.domain.hashing import stable_hash
from techshort.domain.models import (
    AssetManifest,
    ClaimsManifest,
    EvidenceManifest,
    ReviewDecision,
    ReviewLog,
    ReviewStatus,
    ScriptManifest,
    StoryboardManifest,
    now_utc,
)
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.ingestion import resolve_evidence_text


def _record(
    store: ProjectStore,
    object_type: str,
    object_id: str,
    object_hash: str,
    decision: str,
    reviewer: str,
    note: str | None = None,
) -> None:
    path = store.path("reviews/review-log.json")
    log = load_model(path, ReviewLog)
    log.reviews.append(
        ReviewDecision(
            review_id=f"review-{uuid4().hex[:12]}",
            object_type=object_type,
            object_id=object_id,
            object_hash=object_hash,
            decision=decision,
            edit_or_note=note,
            reviewer_id=reviewer,
        )
    )
    atomic_write_model(path, log)


def approve_claims(store: ProjectStore, reviewer: str) -> ClaimsManifest:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    evidence_by_id = {item.evidence_id: item for item in evidence.evidence}
    for claim in claims.claims:
        for evidence_id in claim.evidence_span_ids:
            span = evidence_by_id.get(evidence_id)
            if span is None:
                raise ValueError(
                    f"claim {claim.claim_id} references missing evidence {evidence_id}"
                )
            actual = resolve_evidence_text(store, span.source_id, span.char_start, span.char_end)
            if actual != span.excerpt:
                raise ValueError(f"evidence {evidence_id} no longer resolves to its exact excerpt")
        claim.review_status = ReviewStatus.APPROVED
        claim.approval_timestamp = now_utc()
        claim.approval_hash = stable_hash(
            {
                "claim": claim.model_dump(
                    exclude={"approval_hash", "approval_timestamp", "review_status"}
                ),
                "evidence": [
                    evidence_by_id[e].model_dump(mode="json") for e in claim.evidence_span_ids
                ],
            }
        )
        _record(store, "claim", claim.claim_id, claim.approval_hash, "approve", reviewer)
    atomic_write_model(store.path("claims/claims.json"), claims)
    project = store.project()
    project.approvals.claims = ReviewStatus.APPROVED
    project.stale_artifacts = [item for item in project.stale_artifacts if item != "claims"]
    store.save_project(project)
    return claims


def approve_script(store: ProjectStore, reviewer: str) -> ScriptManifest:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    approved = {
        claim.claim_id for claim in claims.claims if claim.review_status == ReviewStatus.APPROVED
    }
    script = load_model(store.path("script/script.json"), ScriptManifest)
    for segment in script.segments:
        if segment.claim_ids and not set(segment.claim_ids).issubset(approved):
            raise ValueError(f"segment {segment.segment_id} references an unapproved claim")
        segment.review_status = ReviewStatus.APPROVED
        segment.approval_hash = stable_hash(
            {
                "segment": segment.model_dump(exclude={"approval_hash", "review_status"}),
                "claim_ids": segment.claim_ids,
            }
        )
        _record(
            store, "script-segment", segment.segment_id, segment.approval_hash, "approve", reviewer
        )
    atomic_write_model(store.path("script/script.json"), script)
    project = store.project()
    project.approvals.script = ReviewStatus.APPROVED
    project.stale_artifacts = [item for item in project.stale_artifacts if item != "script"]
    store.save_project(project)
    return script


def approve_storyboard(store: ProjectStore, reviewer: str) -> StoryboardManifest:
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    for scene in storyboard.scenes:
        scene.review_status = ReviewStatus.APPROVED
        object_hash = stable_hash(scene)
        _record(store, "scene", scene.scene_id, object_hash, "approve", reviewer)
    atomic_write_model(store.path("storyboard/storyboard.json"), storyboard)
    project = store.project()
    project.approvals.storyboard = ReviewStatus.APPROVED
    project.stale_artifacts = [item for item in project.stale_artifacts if item != "storyboard"]
    store.save_project(project)
    return storyboard


def approve_rights(store: ProjectStore, reviewer: str) -> AssetManifest:
    path = store.path("assets/asset-manifest.json")
    assets = (
        load_model(path, AssetManifest)
        if path.exists()
        else AssetManifest(version_id="assets-empty", assets=[])
    )
    blocked = [
        asset.asset_id
        for asset in assets.assets
        if asset.rights_status in {"unknown", "restricted", "citation-only"}
        or not asset.embedding_allowed
    ]
    if blocked:
        raise ValueError(f"assets cannot be embedded: {', '.join(blocked)}")
    for asset in assets.assets:
        asset.review_status = ReviewStatus.APPROVED
        _record(store, "asset-rights", asset.asset_id, stable_hash(asset), "approve", reviewer)
    atomic_write_model(path, assets)
    project = store.project()
    project.approvals.rights = ReviewStatus.APPROVED
    project.stale_artifacts = [item for item in project.stale_artifacts if item != "rights"]
    store.save_project(project)
    return assets


def approve_final(store: ProjectStore, reviewer: str) -> None:
    project = store.project()
    for gate in ("claims", "script", "storyboard", "rights"):
        if getattr(project.approvals, gate) != ReviewStatus.APPROVED:
            raise ValueError(f"{gate} gate is not approved")
    preview = store.path("renders/previews/preview.mp4")
    qa = store.path("renders/previews/qa-report.json")
    if not preview.exists() or not qa.exists():
        raise ValueError("render and review a QA-checked preview before final approval")
    digest = stable_hash(
        {
            "project": project.model_dump(mode="json"),
            "preview_size": preview.stat().st_size,
            "qa": qa.read_text(encoding="utf-8"),
        }
    )
    _record(store, "final", project.project_id, digest, "approve", reviewer)
    project.approvals.final = ReviewStatus.APPROVED
    project.stale_artifacts = []
    project.downstream_valid = True
    project.status = "approved-for-export"
    store.save_project(project)
