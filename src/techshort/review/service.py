from __future__ import annotations

from typing import Literal
from uuid import uuid4

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    Asset,
    AssetManifest,
    Claim,
    ClaimsManifest,
    EvidenceManifest,
    ProjectManifest,
    QAReport,
    ReviewDecision,
    ReviewLog,
    ReviewStatus,
    Scene,
    ScriptManifest,
    ScriptSegment,
    SourceDocument,
    SourceIndex,
    StoryboardManifest,
    now_utc,
)
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.ingestion import (
    get_active_source,
    resolve_evidence_text,
    verify_source_integrity,
)

Decision = Literal["approve", "reject", "edit", "note"]
ObjectType = Literal["claim", "script-segment", "scene", "asset-rights", "rights", "final"]


def claim_review_hash(claim: Claim, evidence: EvidenceManifest) -> str:
    evidence_by_id = {item.evidence_id: item for item in evidence.evidence}
    try:
        spans = [evidence_by_id[item] for item in claim.evidence_span_ids]
    except KeyError as exc:
        raise ValueError(
            f"claim {claim.claim_id} references missing evidence {exc.args[0]}"
        ) from exc
    return stable_hash(
        {
            "claim": claim.model_dump(
                exclude={"approval_hash", "approval_timestamp", "review_status"}
            ),
            "evidence": [span.model_dump(mode="json") for span in spans],
        }
    )


def script_segment_review_hash(segment: ScriptSegment) -> str:
    return stable_hash(
        {
            "segment": segment.model_dump(exclude={"approval_hash", "review_status"}),
            "claim_ids": segment.claim_ids,
        }
    )


def scene_dependency_hash(scene: Scene, script: ScriptManifest) -> str:
    segment_by_id = {segment.segment_id: segment for segment in script.segments}
    try:
        segments = [segment_by_id[item] for item in scene.script_segment_ids]
    except KeyError as exc:
        raise ValueError(
            f"scene {scene.scene_id} references missing script segment {exc.args[0]}"
        ) from exc
    if len(segments) == 1:
        return stable_hash(segments[0])
    return stable_hash({"segments": segments})


def scene_review_hash(scene: Scene) -> str:
    return stable_hash(scene)


def asset_review_hash(asset: Asset) -> str:
    return stable_hash(asset)


def rights_review_hash(assets: AssetManifest) -> str:
    return stable_hash(assets)


def current_artifact_hashes(store: ProjectStore) -> dict[str, str]:
    source = verify_source_integrity(store, get_active_source(store))
    source_index = load_model(store.path("sources/source-index.json"), SourceIndex)
    paths = {
        "source-index": store.path("sources/source-index.json"),
        "active-source": store.path(source.local_path),
        "active-source-extracted": store.path(f"sources/extracted/{source.source_id}.txt"),
        "evidence": store.path("evidence/evidence.json"),
        "claims": store.path("claims/claims.json"),
        "script": store.path("script/script.json"),
        "storyboard": store.path("storyboard/storyboard.json"),
        "assets": store.path("assets/asset-manifest.json"),
    }
    missing = [key for key, path in paths.items() if not path.is_file()]
    if missing:
        raise ValueError(f"required artifact is missing: {missing[0]}")
    hashes = {key: sha256_file(path) for key, path in paths.items()}
    for indexed_source in source_index.sources:
        verify_source_integrity(store, indexed_source)
        hashes[f"source:{indexed_source.source_id}"] = sha256_file(
            store.path(indexed_source.local_path)
        )
        hashes[f"source:{indexed_source.source_id}:extracted"] = sha256_file(
            store.path(f"sources/extracted/{indexed_source.source_id}.txt")
        )
    return hashes


def final_review_hash(store: ProjectStore, qa_report: QAReport | None = None) -> str:
    project = store.project()
    qa_path = store.path("renders/previews/qa-report.json")
    qa_report = qa_report or load_model(qa_path, QAReport)
    if qa_report.media_path is None or qa_report.media_hash is None:
        raise ValueError("QA report does not identify the exact reviewed media")
    media_path = store.path(qa_report.media_path)
    expected_preview = store.path("renders/previews/preview.mp4")
    if media_path != expected_preview:
        raise ValueError("final approval requires QA of the current preview")
    if not media_path.is_file() or sha256_file(media_path) != qa_report.media_hash:
        raise ValueError("QA-reviewed media is missing or has changed")
    artifacts = current_artifact_hashes(store)
    stale_artifacts = [
        key
        for key, artifact_hash in artifacts.items()
        if qa_report.artifact_hashes.get(key) != artifact_hash
    ]
    if stale_artifacts:
        raise ValueError(f"QA report does not match current artifact: {stale_artifacts[0]}")
    return stable_hash(
        {
            "project_id": project.project_id,
            "active_source_id": project.active_source_id,
            "active_versions": project.active_versions,
            "dependency_hashes": {
                key: value
                for key, value in project.dependency_hashes.items()
                if key != "final_approval"
            },
            "artifacts": artifacts,
            "qa_hash": sha256_file(qa_path),
            "media_path": qa_report.media_path,
            "media_hash": qa_report.media_hash,
        }
    )


def _canonical_object_type(object_type: str) -> ObjectType:
    aliases = {
        "claim": "claim",
        "script-segment": "script-segment",
        "scene": "scene",
        "asset": "asset-rights",
        "asset-rights": "asset-rights",
        "rights": "rights",
        "rights-gate": "rights",
        "final": "final",
    }
    try:
        return aliases[object_type]  # type: ignore[return-value]
    except KeyError as exc:
        raise ValueError(f"unsupported review object type: {object_type}") from exc


def current_object_hash(store: ProjectStore, object_type: str, object_id: str) -> str:
    canonical = _canonical_object_type(object_type)
    if canonical == "claim":
        claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
        evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
        claim = _find_claim(claims, object_id)
        return claim_review_hash(claim, evidence)
    if canonical == "script-segment":
        script = load_model(store.path("script/script.json"), ScriptManifest)
        return script_segment_review_hash(_find_segment(script, object_id))
    if canonical == "scene":
        storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
        return scene_review_hash(_find_scene(storyboard, object_id))
    if canonical == "final":
        if object_id != store.project().project_id:
            raise ValueError(f"unknown final review object: {object_id}")
        return final_review_hash(store)
    assets = _load_assets(store)
    if canonical == "rights":
        if object_id not in {assets.version_id, store.project().project_id}:
            raise ValueError(f"unknown rights review object: {object_id}")
        return rights_review_hash(assets)
    asset = _find_asset(assets, object_id)
    asset_path = store.path(asset.local_path)
    if not asset_path.is_file() or sha256_file(asset_path) != asset.sha256:
        raise ValueError(f"asset file is missing or changed: {asset.asset_id}")
    return asset_review_hash(asset)


def has_current_approval(store: ProjectStore, object_type: str, object_id: str) -> bool:
    canonical = _canonical_object_type(object_type)
    try:
        expected = current_object_hash(store, canonical, object_id)
    except (OSError, ValueError):
        return False
    log = _load_review_log(store)
    for decision in reversed(log.reviews):
        try:
            decision_type = _canonical_object_type(decision.object_type)
        except ValueError:
            continue
        if (
            decision_type != canonical
            or decision.object_id != object_id
            or decision.invalidated_at is not None
            or decision.decision == "note"
        ):
            continue
        return decision.decision == "approve" and decision.object_hash == expected
    return False


def _load_review_log(store: ProjectStore) -> ReviewLog:
    path = store.path("reviews/review-log.json")
    if not path.exists():
        atomic_write_model(path, ReviewLog())
    return load_model(path, ReviewLog)


def _record_many(
    store: ProjectStore,
    rows: list[tuple[ObjectType, str, str, Decision, str | None]],
    reviewer: str,
) -> None:
    if not reviewer.strip():
        raise ValueError("reviewer identifier cannot be empty")
    path = store.path("reviews/review-log.json")
    log = _load_review_log(store)
    for object_type, object_id, object_hash, decision, note in rows:
        log.reviews.append(
            ReviewDecision(
                review_id=f"review-{uuid4().hex[:12]}",
                object_type=object_type,
                object_id=object_id,
                object_hash=object_hash,
                decision=decision,
                edit_or_note=note,
                reviewer_id=reviewer.strip(),
            )
        )
    atomic_write_model(path, log)


def _record(
    store: ProjectStore,
    object_type: ObjectType,
    object_id: str,
    object_hash: str,
    decision: Decision,
    reviewer: str,
    note: str | None = None,
) -> None:
    _record_many(
        store,
        [(object_type, object_id, object_hash, decision, note)],
        reviewer,
    )


def _find_claim(claims: ClaimsManifest, claim_id: str) -> Claim:
    claim = next((item for item in claims.claims if item.claim_id == claim_id), None)
    if claim is None:
        raise ValueError(f"unknown claim: {claim_id}")
    return claim


def _find_segment(script: ScriptManifest, segment_id: str) -> ScriptSegment:
    segment = next((item for item in script.segments if item.segment_id == segment_id), None)
    if segment is None:
        raise ValueError(f"unknown script segment: {segment_id}")
    return segment


def _find_scene(storyboard: StoryboardManifest, scene_id: str) -> Scene:
    scene = next((item for item in storyboard.scenes if item.scene_id == scene_id), None)
    if scene is None:
        raise ValueError(f"unknown scene: {scene_id}")
    return scene


def _find_asset(assets: AssetManifest, asset_id: str) -> Asset:
    asset = next((item for item in assets.assets if item.asset_id == asset_id), None)
    if asset is None:
        raise ValueError(f"unknown asset: {asset_id}")
    return asset


def _load_assets(store: ProjectStore) -> AssetManifest:
    path = store.path("assets/asset-manifest.json")
    return (
        load_model(path, AssetManifest)
        if path.exists()
        else AssetManifest(version_id="assets-empty")
    )


def _validate_unique_ids(values: list[str], kind: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{kind} IDs must be unique")


def _ensure_active_versions(project: ProjectManifest, **versions: str) -> None:
    for artifact, actual in versions.items():
        expected = project.active_versions.get(artifact)
        if expected is not None and expected != actual:
            raise ValueError(
                f"active {artifact} version is {expected}, not loaded version {actual}"
            )
        project.active_versions.setdefault(artifact, actual)


def _validate_claim_dependencies(
    store: ProjectStore,
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
    project: ProjectManifest,
) -> None:
    if claims.evidence_version_id != evidence.version_id:
        raise ValueError("claims were generated from a different evidence version")
    if not evidence.evidence:
        raise ValueError("at least one evidence span is required")
    if not claims.claims:
        raise ValueError("at least one evidence-linked claim is required")
    _ensure_active_versions(project, evidence=evidence.version_id, claims=claims.version_id)
    _validate_unique_ids([span.evidence_id for span in evidence.evidence], "evidence")
    _validate_unique_ids([claim.claim_id for claim in claims.claims], "claim")
    evidence_by_id = {span.evidence_id: span for span in evidence.evidence}
    verified_sources: dict[str, SourceDocument] = {}
    for span in evidence.evidence:
        if span.source_id not in project.source_ids:
            raise ValueError(f"evidence {span.evidence_id} references an undeclared project source")
        document = verified_sources.get(span.source_id)
        if document is None:
            document = verify_source_integrity(store, span.source_id)
            verified_sources[span.source_id] = document
        if span.source_hash != document.content_hash:
            raise ValueError(f"evidence {span.evidence_id} has a stale source content hash")
        actual = resolve_evidence_text(
            store,
            span.source_id,
            span.char_start,
            span.char_end,
            expected_source_hash=span.source_hash,
            expected_extracted_hash=document.extracted_text_hash,
        )
        if actual != span.excerpt:
            raise ValueError(f"evidence {span.evidence_id} no longer resolves to its exact excerpt")
    for claim in claims.claims:
        if len(claim.evidence_span_ids) != len(set(claim.evidence_span_ids)):
            raise ValueError(f"claim {claim.claim_id} repeats an evidence span")
        missing = set(claim.evidence_span_ids) - evidence_by_id.keys()
        if missing:
            raise ValueError(
                f"claim {claim.claim_id} references missing evidence {sorted(missing)[0]}"
            )


def _claim_is_current(store: ProjectStore, claim: Claim, evidence: EvidenceManifest) -> bool:
    return (
        claim.review_status == ReviewStatus.APPROVED
        and claim.approval_hash == claim_review_hash(claim, evidence)
        and has_current_approval(store, "claim", claim.claim_id)
    )


def _validate_script_dependencies(
    store: ProjectStore,
    script: ScriptManifest,
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
    project: ProjectManifest,
) -> None:
    _validate_claim_dependencies(store, claims, evidence, project)
    if script.claims_version_id != claims.version_id:
        raise ValueError("script was generated from a different claims version")
    _ensure_active_versions(project, script=script.version_id)
    _validate_unique_ids([segment.segment_id for segment in script.segments], "script segment")
    approved = {
        claim.claim_id for claim in claims.claims if _claim_is_current(store, claim, evidence)
    }
    for segment in script.segments:
        missing = set(segment.claim_ids) - approved
        if missing:
            raise ValueError(
                f"segment {segment.segment_id} references an unapproved or stale claim "
                f"{sorted(missing)[0]}"
            )


def _segment_is_current(store: ProjectStore, segment: ScriptSegment) -> bool:
    return (
        segment.review_status == ReviewStatus.APPROVED
        and segment.approval_hash == script_segment_review_hash(segment)
        and has_current_approval(store, "script-segment", segment.segment_id)
    )


def _validate_storyboard_dependencies(
    store: ProjectStore,
    storyboard: StoryboardManifest,
    script: ScriptManifest,
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
    project: ProjectManifest,
) -> None:
    _validate_script_dependencies(store, script, claims, evidence, project)
    if storyboard.script_version_id != script.version_id:
        raise ValueError("storyboard was generated from a different script version")
    _ensure_active_versions(project, storyboard=storyboard.version_id)
    _validate_unique_ids([scene.scene_id for scene in storyboard.scenes], "scene")
    segment_by_id = {segment.segment_id: segment for segment in script.segments}
    approved_claims = {
        claim.claim_id for claim in claims.claims if _claim_is_current(store, claim, evidence)
    }
    assets = _load_assets(store)
    asset_ids = {asset.asset_id for asset in assets.assets}
    for scene in storyboard.scenes:
        try:
            linked_segments = [segment_by_id[item] for item in scene.script_segment_ids]
        except KeyError as exc:
            raise ValueError(
                f"scene {scene.scene_id} references missing script segment {exc.args[0]}"
            ) from exc
        stale_segments = [
            segment.segment_id
            for segment in linked_segments
            if not _segment_is_current(store, segment)
        ]
        if stale_segments:
            raise ValueError(
                f"scene {scene.scene_id} references unapproved or stale script segment "
                f"{stale_segments[0]}"
            )
        linked_claims = {claim_id for segment in linked_segments for claim_id in segment.claim_ids}
        if not set(scene.claim_ids).issubset(linked_claims):
            raise ValueError(
                f"scene {scene.scene_id} cites a claim not carried by its script segments"
            )
        if not set(scene.claim_ids).issubset(approved_claims):
            raise ValueError(f"scene {scene.scene_id} cites an unapproved or stale claim")
        factual_types = {"factual", "hook", "analogy", "caveat", "limitation"}
        if (
            scene.evidence_label
            or any(segment.segment_type in factual_types for segment in linked_segments)
        ) and not scene.claim_ids:
            raise ValueError(f"factual scene {scene.scene_id} requires approved claim IDs")
        expected_dependency = scene_dependency_hash(scene, script)
        if scene.dependency_hash != expected_dependency:
            raise ValueError(f"scene {scene.scene_id} has a stale script dependency hash")
        missing_assets = set(scene.asset_ids) - asset_ids
        if missing_assets:
            raise ValueError(
                f"scene {scene.scene_id} references missing asset {sorted(missing_assets)[0]}"
            )


def _validate_rights_dependencies(
    store: ProjectStore,
    assets: AssetManifest,
    project: ProjectManifest,
) -> None:
    _ensure_active_versions(project, assets=assets.version_id)
    _validate_unique_ids([asset.asset_id for asset in assets.assets], "asset")
    storyboard_path = store.path("storyboard/storyboard.json")
    storyboard = (
        load_model(storyboard_path, StoryboardManifest) if storyboard_path.exists() else None
    )
    if storyboard is not None:
        _ensure_active_versions(project, storyboard=storyboard.version_id)
    scene_ids = {scene.scene_id for scene in storyboard.scenes} if storyboard else set()
    declared_assets = {asset.asset_id for asset in assets.assets}
    if storyboard:
        referenced_assets = {
            asset_id for scene in storyboard.scenes for asset_id in scene.asset_ids
        }
        missing_assets = referenced_assets - declared_assets
        if missing_assets:
            raise ValueError(f"storyboard references missing asset {sorted(missing_assets)[0]}")
    for asset in assets.assets:
        if asset.rights_status in {"unknown", "restricted", "citation-only"}:
            raise ValueError(f"asset cannot be embedded: {asset.asset_id}")
        if not asset.embedding_allowed:
            raise ValueError(f"asset embedding is not allowed: {asset.asset_id}")
        if not asset.origin.strip() or not asset.creator.strip() or not asset.license.strip():
            raise ValueError(f"asset rights metadata is incomplete: {asset.asset_id}")
        path = store.path(asset.local_path)
        if not path.is_file():
            raise ValueError(f"asset file is missing: {asset.asset_id}")
        if sha256_file(path) != asset.sha256:
            raise ValueError(f"asset hash no longer matches: {asset.asset_id}")
        missing_scenes = set(asset.scene_usage) - scene_ids
        if missing_scenes:
            raise ValueError(
                f"asset {asset.asset_id} names missing scene {sorted(missing_scenes)[0]}"
            )


def _set_gate(
    store: ProjectStore,
    gate: Literal["claims", "script", "storyboard", "rights", "final"],
    status: ReviewStatus,
    project: ProjectManifest | None = None,
) -> None:
    project = project or store.project()
    setattr(project.approvals, gate, status)
    if status == ReviewStatus.APPROVED:
        project.stale_artifacts = [item for item in project.stale_artifacts if item != gate]
    project.downstream_valid = gate == "final" and status == ReviewStatus.APPROVED
    store.save_project(project)


def approve_claim(store: ProjectStore, claim_id: str, reviewer: str) -> Claim:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    project = store.project()
    _validate_claim_dependencies(store, claims, evidence, project)
    claim = _find_claim(claims, claim_id)
    claim.review_status = ReviewStatus.APPROVED
    claim.approval_timestamp = now_utc()
    claim.approval_hash = claim_review_hash(claim, evidence)
    atomic_write_model(store.path("claims/claims.json"), claims)
    _record(store, "claim", claim_id, claim.approval_hash, "approve", reviewer)
    all_approved = all(_claim_is_current(store, item, evidence) for item in claims.claims)
    _set_gate(
        store,
        "claims",
        ReviewStatus.APPROVED if all_approved else ReviewStatus.PENDING,
        project,
    )
    return claim


def approve_claims(store: ProjectStore, reviewer: str) -> ClaimsManifest:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    project = store.project()
    _validate_claim_dependencies(store, claims, evidence, project)
    rows: list[tuple[ObjectType, str, str, Decision, str | None]] = []
    for claim in claims.claims:
        claim.review_status = ReviewStatus.APPROVED
        claim.approval_timestamp = now_utc()
        claim.approval_hash = claim_review_hash(claim, evidence)
        rows.append(("claim", claim.claim_id, claim.approval_hash, "approve", None))
    atomic_write_model(store.path("claims/claims.json"), claims)
    _record_many(store, rows, reviewer)
    _set_gate(store, "claims", ReviewStatus.APPROVED, project)
    return claims


def approve_script_segment(store: ProjectStore, segment_id: str, reviewer: str) -> ScriptSegment:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    project = store.project()
    _validate_script_dependencies(store, script, claims, evidence, project)
    segment = _find_segment(script, segment_id)
    segment.review_status = ReviewStatus.APPROVED
    segment.approval_hash = script_segment_review_hash(segment)
    atomic_write_model(store.path("script/script.json"), script)
    _record(
        store,
        "script-segment",
        segment_id,
        segment.approval_hash,
        "approve",
        reviewer,
    )
    all_approved = all(_segment_is_current(store, item) for item in script.segments)
    _set_gate(
        store,
        "script",
        ReviewStatus.APPROVED if all_approved else ReviewStatus.PENDING,
        project,
    )
    return segment


def approve_script(store: ProjectStore, reviewer: str) -> ScriptManifest:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    project = store.project()
    _validate_script_dependencies(store, script, claims, evidence, project)
    rows: list[tuple[ObjectType, str, str, Decision, str | None]] = []
    for segment in script.segments:
        segment.review_status = ReviewStatus.APPROVED
        segment.approval_hash = script_segment_review_hash(segment)
        rows.append(
            (
                "script-segment",
                segment.segment_id,
                segment.approval_hash,
                "approve",
                None,
            )
        )
    atomic_write_model(store.path("script/script.json"), script)
    _record_many(store, rows, reviewer)
    _set_gate(store, "script", ReviewStatus.APPROVED, project)
    return script


def approve_scene(store: ProjectStore, scene_id: str, reviewer: str) -> Scene:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    project = store.project()
    _validate_storyboard_dependencies(store, storyboard, script, claims, evidence, project)
    scene = _find_scene(storyboard, scene_id)
    scene.review_status = ReviewStatus.APPROVED
    atomic_write_model(store.path("storyboard/storyboard.json"), storyboard)
    _record(store, "scene", scene_id, scene_review_hash(scene), "approve", reviewer)
    all_approved = all(
        item.review_status == ReviewStatus.APPROVED
        and has_current_approval(store, "scene", item.scene_id)
        for item in storyboard.scenes
    )
    _set_gate(
        store,
        "storyboard",
        ReviewStatus.APPROVED if all_approved else ReviewStatus.PENDING,
        project,
    )
    return scene


def approve_storyboard(store: ProjectStore, reviewer: str) -> StoryboardManifest:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    project = store.project()
    _validate_storyboard_dependencies(store, storyboard, script, claims, evidence, project)
    rows: list[tuple[ObjectType, str, str, Decision, str | None]] = []
    for scene in storyboard.scenes:
        scene.review_status = ReviewStatus.APPROVED
        rows.append(("scene", scene.scene_id, scene_review_hash(scene), "approve", None))
    atomic_write_model(store.path("storyboard/storyboard.json"), storyboard)
    _record_many(store, rows, reviewer)
    _set_gate(store, "storyboard", ReviewStatus.APPROVED, project)
    return storyboard


def approve_asset(store: ProjectStore, asset_id: str, reviewer: str) -> Asset:
    assets = _load_assets(store)
    project = store.project()
    _validate_rights_dependencies(store, assets, project)
    asset = _find_asset(assets, asset_id)
    asset.review_status = ReviewStatus.APPROVED
    atomic_write_model(store.path("assets/asset-manifest.json"), assets)
    _record(
        store,
        "asset-rights",
        asset_id,
        asset_review_hash(asset),
        "approve",
        reviewer,
    )
    all_approved = bool(assets.assets) and all(
        item.review_status == ReviewStatus.APPROVED
        and has_current_approval(store, "asset-rights", item.asset_id)
        for item in assets.assets
    )
    if all_approved:
        _record(
            store,
            "rights",
            assets.version_id,
            rights_review_hash(assets),
            "approve",
            reviewer,
        )
    _set_gate(
        store,
        "rights",
        ReviewStatus.APPROVED if all_approved else ReviewStatus.PENDING,
        project,
    )
    return asset


def approve_rights(store: ProjectStore, reviewer: str) -> AssetManifest:
    assets = _load_assets(store)
    project = store.project()
    _validate_rights_dependencies(store, assets, project)
    rows: list[tuple[ObjectType, str, str, Decision, str | None]] = []
    for asset in assets.assets:
        asset.review_status = ReviewStatus.APPROVED
        rows.append(
            (
                "asset-rights",
                asset.asset_id,
                asset_review_hash(asset),
                "approve",
                None,
            )
        )
    rows.append(("rights", assets.version_id, rights_review_hash(assets), "approve", None))
    atomic_write_model(store.path("assets/asset-manifest.json"), assets)
    _record_many(store, rows, reviewer)
    _set_gate(store, "rights", ReviewStatus.APPROVED, project)
    return assets


def _all_gate_dependencies_are_current(store: ProjectStore) -> None:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    assets = _load_assets(store)
    project = store.project()
    _validate_storyboard_dependencies(store, storyboard, script, claims, evidence, project)
    _validate_rights_dependencies(store, assets, project)
    if not all(_claim_is_current(store, claim, evidence) for claim in claims.claims):
        raise ValueError("claim approvals are not current")
    if not all(_segment_is_current(store, segment) for segment in script.segments):
        raise ValueError("script approvals are not current")
    if not all(
        scene.review_status == ReviewStatus.APPROVED
        and has_current_approval(store, "scene", scene.scene_id)
        for scene in storyboard.scenes
    ):
        raise ValueError("storyboard approvals are not current")
    if not all(
        asset.review_status == ReviewStatus.APPROVED
        and has_current_approval(store, "asset-rights", asset.asset_id)
        for asset in assets.assets
    ):
        raise ValueError("asset-rights approvals are not current")
    if not has_current_approval(store, "rights", assets.version_id):
        raise ValueError("rights gate approval is not current")


def approve_final(store: ProjectStore, reviewer: str) -> None:
    project = store.project()
    for gate in ("claims", "script", "storyboard", "rights"):
        if getattr(project.approvals, gate) != ReviewStatus.APPROVED:
            raise ValueError(f"{gate} gate is not approved")
    _all_gate_dependencies_are_current(store)
    preview = store.path("renders/previews/preview.mp4")
    qa = store.path("renders/previews/qa-report.json")
    if not preview.exists() or not qa.exists():
        raise ValueError("render and review a QA-checked preview before final approval")
    report = load_model(qa, QAReport)
    if not report.passed:
        raise ValueError("QA report contains export blockers")
    digest = final_review_hash(store, report)
    _record(store, "final", project.project_id, digest, "approve", reviewer)
    project.dependency_hashes["final_approval"] = digest
    project.approvals.final = ReviewStatus.APPROVED
    project.stale_artifacts = []
    project.downstream_valid = True
    project.status = "approved-for-export"
    store.save_project(project)


def edit_claim(store: ProjectStore, claim_id: str, new_text: str, reviewer: str) -> Claim:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    claim = _find_claim(claims, claim_id)
    text = new_text.strip()
    if not text:
        raise ValueError("claim text cannot be empty")
    if text == claim.text:
        return claim
    claim.text = text
    claim.reviewer_edits = text
    claim.review_status = ReviewStatus.PENDING
    claim.approval_hash = None
    claim.approval_timestamp = None
    atomic_write_model(store.path("claims/claims.json"), claims)
    store.invalidate_from("claims", f"claim {claim_id} edited")
    object_hash = current_object_hash(store, "claim", claim_id)
    _record(store, "claim", claim_id, object_hash, "edit", reviewer, text)
    return claim


def reject_claim(
    store: ProjectStore, claim_id: str, reviewer: str, note: str | None = None
) -> Claim:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    claim = _find_claim(claims, claim_id)
    claim.review_status = ReviewStatus.REJECTED
    claim.approval_hash = None
    claim.approval_timestamp = None
    atomic_write_model(store.path("claims/claims.json"), claims)
    store.invalidate_from("claims", f"claim {claim_id} rejected")
    _record(
        store,
        "claim",
        claim_id,
        current_object_hash(store, "claim", claim_id),
        "reject",
        reviewer,
        note,
    )
    return claim


def edit_script_segment(
    store: ProjectStore, segment_id: str, new_text: str, reviewer: str
) -> ScriptSegment:
    script = load_model(store.path("script/script.json"), ScriptManifest)
    segment = _find_segment(script, segment_id)
    text = new_text.strip()
    if not text:
        raise ValueError("script segment text cannot be empty")
    if text == segment.text:
        return segment
    segment.text = text
    segment.review_status = ReviewStatus.PENDING
    segment.approval_hash = None
    atomic_write_model(store.path("script/script.json"), script)
    store.invalidate_from("script", f"script segment {segment_id} edited")
    _record(
        store,
        "script-segment",
        segment_id,
        current_object_hash(store, "script-segment", segment_id),
        "edit",
        reviewer,
        text,
    )
    return segment


def reject_script_segment(
    store: ProjectStore,
    segment_id: str,
    reviewer: str,
    note: str | None = None,
) -> ScriptSegment:
    script = load_model(store.path("script/script.json"), ScriptManifest)
    segment = _find_segment(script, segment_id)
    segment.review_status = ReviewStatus.REJECTED
    segment.approval_hash = None
    atomic_write_model(store.path("script/script.json"), script)
    store.invalidate_from("script", f"script segment {segment_id} rejected")
    _record(
        store,
        "script-segment",
        segment_id,
        current_object_hash(store, "script-segment", segment_id),
        "reject",
        reviewer,
        note,
    )
    return segment


def edit_scene(
    store: ProjectStore,
    scene_id: str,
    updates: dict[str, object],
    reviewer: str,
) -> Scene:
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    scene = _find_scene(storyboard, scene_id)
    forbidden = {"schema_version", "scene_id", "review_status", "dependency_hash"}
    if forbidden.intersection(updates):
        raise ValueError("scene identity, review state, and dependency hash are immutable")
    payload = scene.model_dump(mode="json")
    payload.update(updates)
    payload["review_status"] = ReviewStatus.PENDING
    edited = Scene.model_validate(payload)
    if scene_review_hash(edited) == scene_review_hash(scene):
        return scene
    storyboard.scenes[storyboard.scenes.index(scene)] = edited
    atomic_write_model(store.path("storyboard/storyboard.json"), storyboard)
    store.invalidate_from("storyboard", f"scene {scene_id} edited")
    _record(
        store,
        "scene",
        scene_id,
        current_object_hash(store, "scene", scene_id),
        "edit",
        reviewer,
        str(updates),
    )
    return edited


def reject_scene(
    store: ProjectStore, scene_id: str, reviewer: str, note: str | None = None
) -> Scene:
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    scene = _find_scene(storyboard, scene_id)
    scene.review_status = ReviewStatus.REJECTED
    atomic_write_model(store.path("storyboard/storyboard.json"), storyboard)
    store.invalidate_from("storyboard", f"scene {scene_id} rejected")
    _record(
        store,
        "scene",
        scene_id,
        current_object_hash(store, "scene", scene_id),
        "reject",
        reviewer,
        note,
    )
    return scene


def edit_asset(
    store: ProjectStore,
    asset_id: str,
    updates: dict[str, object],
    reviewer: str,
) -> Asset:
    assets = _load_assets(store)
    asset = _find_asset(assets, asset_id)
    forbidden = {"schema_version", "asset_id", "review_status"}
    if forbidden.intersection(updates):
        raise ValueError("asset identity and review state are immutable")
    payload = asset.model_dump(mode="json")
    payload.update(updates)
    payload["review_status"] = ReviewStatus.PENDING
    edited = Asset.model_validate(payload)
    if asset_review_hash(edited) == asset_review_hash(asset):
        return asset
    assets.assets[assets.assets.index(asset)] = edited
    atomic_write_model(store.path("assets/asset-manifest.json"), assets)
    store.invalidate_from("rights", f"asset {asset_id} edited")
    _record(
        store,
        "asset-rights",
        asset_id,
        current_object_hash(store, "asset-rights", asset_id),
        "edit",
        reviewer,
        str(updates),
    )
    return edited


def reject_asset(
    store: ProjectStore, asset_id: str, reviewer: str, note: str | None = None
) -> Asset:
    assets = _load_assets(store)
    asset = _find_asset(assets, asset_id)
    asset.review_status = ReviewStatus.REJECTED
    atomic_write_model(store.path("assets/asset-manifest.json"), assets)
    store.invalidate_from("rights", f"asset {asset_id} rejected")
    _record(
        store,
        "asset-rights",
        asset_id,
        current_object_hash(store, "asset-rights", asset_id),
        "reject",
        reviewer,
        note,
    )
    return asset


def add_note(
    store: ProjectStore,
    object_type: str,
    object_id: str,
    note: str,
    reviewer: str,
) -> None:
    text = note.strip()
    if not text:
        raise ValueError("note cannot be empty")
    canonical = _canonical_object_type(object_type)
    _record(
        store,
        canonical,
        object_id,
        current_object_hash(store, canonical, object_id),
        "note",
        reviewer,
        text,
    )


def note_claim(store: ProjectStore, claim_id: str, note: str, reviewer: str) -> None:
    add_note(store, "claim", claim_id, note, reviewer)


def note_script_segment(store: ProjectStore, segment_id: str, note: str, reviewer: str) -> None:
    add_note(store, "script-segment", segment_id, note, reviewer)


def note_scene(store: ProjectStore, scene_id: str, note: str, reviewer: str) -> None:
    add_note(store, "scene", scene_id, note, reviewer)


def note_asset(store: ProjectStore, asset_id: str, note: str, reviewer: str) -> None:
    add_note(store, "asset-rights", asset_id, note, reviewer)
