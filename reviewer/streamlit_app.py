from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import streamlit as st
from pydantic import BaseModel

from techshort.alignment import cues_from_script, write_caption_files
from techshort.audio import active_audio, import_audio, probe_duration
from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    AssetManifest,
    ClaimsManifest,
    EvidenceManifest,
    QAReport,
    ReviewLog,
    ReviewStatus,
    ScriptManifest,
    SourceIndex,
    StoryboardManifest,
)
from techshort.domain.storage import ProjectStore, load_model, sanitize_filename
from techshort.export import export_project, generate_evidence_page
from techshort.qa import run_qa
from techshort.rendering import render_video
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
    edit_asset,
    edit_claim,
    edit_scene,
    edit_script_segment,
    final_review_hash,
    has_current_approval,
    note_asset,
    note_claim,
    note_scene,
    note_script_segment,
    reject_asset,
    reject_claim,
    reject_scene,
    reject_script_segment,
)

T = TypeVar("T", bound=BaseModel)
STEPS = (
    "1 Project",
    "2 Sources",
    "3 Claims and evidence",
    "4 Script",
    "5 Storyboard and assets",
    "6 Narration and captions",
    "7 Preview",
    "8 QA",
    "9 Export",
)
RIGHTS_STATUSES = (
    "original",
    "user-owned",
    "permissively-licensed",
    "citation-only",
    "unknown",
    "restricted",
)
AUDIO_RIGHTS_STATUSES = (
    "unknown",
    "user-owned",
    "original",
    "permissively-licensed",
    "citation-only",
    "restricted",
)

st.set_page_config(page_title="techshort reviewer", page_icon="TS", layout="wide")
st.title("techshort reviewer")
st.caption(
    "Local, evidence-linked review. Source and generated content is shown as inert text and "
    "is never executed."
)


def _load_if(store: ProjectStore, relative: str, model_type: type[T]) -> T | None:
    path = store.path(relative)
    return load_model(path, model_type) if path.is_file() else None


def _perform(
    label: str,
    key: str,
    callback: Callable[..., object],
    *args: object,
    disabled: bool = False,
) -> None:
    if not st.button(label, key=key, disabled=disabled, width="stretch"):
        return
    try:
        with st.spinner(f"{label}…"):
            callback(*args)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        st.error(f"{label} failed: {exc}")
        return
    st.success(f"Saved: {label}")
    st.rerun()


def _generate_captions(store: ProjectStore) -> tuple[Path, Path]:
    script = load_model(store.path("script/script.json"), ScriptManifest)
    narration = active_audio(store)
    narration_duration = probe_duration(narration) if narration else None
    cues = cues_from_script(script, target_duration=narration_duration)
    paths = (store.path("captions/captions.srt"), store.path("captions/captions.vtt"))
    old_hashes = {path.name: sha256_file(path) for path in paths if path.is_file()}
    srt, vtt = write_caption_files(store.path("captions"), cues)
    new_hashes = {srt.name: sha256_file(srt), vtt.name: sha256_file(vtt)}
    project = store.project()
    project.active_versions["captions"] = stable_hash(new_hashes)
    store.save_project(project)
    if old_hashes != new_hashes:
        store.invalidate_from("final", "captions regenerated")
    return srt, vtt


def _import_uploaded_audio(
    store: ProjectStore,
    uploaded_name: str,
    uploaded_bytes: bytes,
    rights_status: str,
) -> Path:
    if len(uploaded_bytes) > 200 * 1024 * 1024:
        raise ValueError("audio exceeds the 200 MiB limit")
    filename = sanitize_filename(uploaded_name)
    with tempfile.TemporaryDirectory(prefix="techshort-audio-") as temporary:
        staged = Path(temporary) / filename
        staged.write_bytes(uploaded_bytes)
        return import_audio(store, staged, rights_status)


def _edit_scene_from_json(
    store: ProjectStore,
    scene_id: str,
    on_screen_text: str,
    accessibility_description: str,
    evidence_label: str,
    visual_json: str,
    reviewer: str,
) -> object:
    visual = json.loads(visual_json)
    if not isinstance(visual, dict):
        raise ValueError("visual specification must be a JSON object")
    return edit_scene(
        store,
        scene_id,
        {
            "on_screen_text": on_screen_text,
            "accessibility_description": accessibility_description,
            "evidence_label": evidence_label.strip() or None,
            "visual": visual,
        },
        reviewer,
    )


def _edit_asset_metadata(
    store: ProjectStore,
    asset_id: str,
    origin: str,
    creator: str,
    source_url: str,
    license_name: str,
    attribution: str,
    rights_status: str,
    embedding_allowed: bool,
    reviewer: str,
) -> object:
    return edit_asset(
        store,
        asset_id,
        {
            "origin": origin,
            "creator": creator,
            "source_url": source_url.strip() or None,
            "license": license_name,
            "required_attribution": attribution.strip() or None,
            "rights_status": rights_status,
            "embedding_allowed": embedding_allowed,
        },
        reviewer,
    )


def _run_preview_qa(store: ProjectStore) -> QAReport:
    preview = store.path("renders/previews/preview.mp4")
    if not preview.is_file():
        raise ValueError("render a preview before running QA")
    return run_qa(store, preview)


def _render_final(store: ProjectStore) -> Path:
    project = store.project()
    if project.approvals.final != ReviewStatus.APPROVED:
        raise ValueError("approve the current preview before rendering the final")
    if not has_current_approval(store, "final", project.project_id):
        raise ValueError("final approval is missing or stale")
    if project.dependency_hashes.get("final_approval") != final_review_hash(store):
        raise ValueError("final approval no longer matches the reviewed preview")
    final = render_video(store, preview=False)
    report = run_qa(store, final, destination="renders/final/qa-report.json")
    if not report.passed:
        raise ValueError("final QA failed: " + "; ".join(report.export_blockers))
    return final


def _export_blockers(store: ProjectStore) -> list[str]:
    project = store.project()
    blockers = [
        f"{gate} gate is {getattr(project.approvals, gate)}"
        for gate in ("claims", "script", "storyboard", "rights", "final")
        if getattr(project.approvals, gate) != ReviewStatus.APPROVED
    ]
    blockers.extend(f"stale artifact: {item}" for item in project.stale_artifacts)
    qa = _load_if(store, "renders/previews/qa-report.json", QAReport)
    if qa is None:
        blockers.append("preview QA report is missing")
    elif not qa.passed:
        blockers.extend(f"preview QA: {item}" for item in qa.export_blockers)
    if project.approvals.final == ReviewStatus.APPROVED:
        try:
            if not has_current_approval(store, "final", project.project_id):
                blockers.append("final approval is stale")
            elif project.dependency_hashes.get("final_approval") != final_review_hash(store):
                blockers.append("final approval no longer matches the preview")
        except (OSError, ValueError):
            blockers.append("final approval cannot be revalidated")
    if not store.path("renders/final/final.mp4").is_file():
        blockers.append("final render is missing")
    return list(dict.fromkeys(blockers))


def _show_project(store: ProjectStore) -> None:
    project = store.project()
    st.subheader(project.title)
    left, middle, right = st.columns(3)
    left.metric("Target", f"{project.width}×{project.height}")
    middle.metric("Frame rate", f"{project.fps} fps")
    right.metric("Target duration", f"{project.target_duration_seconds:g} s")
    st.write(
        {
            "status": project.status,
            "content risk": project.content_risk,
            "active source": project.active_source_id or "none",
            "theme": project.theme,
        }
    )
    st.subheader("Human approval gates")
    st.dataframe(
        [
            {"gate": gate, "status": str(getattr(project.approvals, gate))}
            for gate in ("claims", "script", "storyboard", "rights", "final")
        ],
        hide_index=True,
        use_container_width=True,
    )
    if project.stale_artifacts:
        st.warning(
            "Upstream edits invalidated: " + ", ".join(project.stale_artifacts) + ". "
            "Regenerate or re-review these stages in order."
        )
    else:
        st.success("No artifacts are marked stale.")


def _show_sources(store: ProjectStore) -> None:
    sources = _load_if(store, "sources/source-index.json", SourceIndex)
    if sources is None:
        st.info("No source is ingested. Run `techshort ingest <project> <source>`.")
        return
    active = sources.active_source_id or store.project().active_source_id
    for source in sources.sources:
        with st.container(border=True):
            st.subheader(source.title)
            st.caption("Active source" if source.source_id == active else "Stored source")
            st.write(
                {
                    "source ID": source.source_id,
                    "filename": source.original_filename,
                    "type": source.source_type,
                    "SHA-256": source.content_hash,
                    "locations": source.page_or_section_count,
                    "rights": source.rights_status,
                    "OCR required": source.ocr_required,
                    "appears incomplete": source.appears_incomplete,
                }
            )
            for warning in source.extraction_warnings:
                st.warning(warning)


def _show_claims(store: ProjectStore, reviewer: str) -> None:
    claims = _load_if(store, "claims/claims.json", ClaimsManifest)
    evidence = _load_if(store, "evidence/evidence.json", EvidenceManifest)
    if claims is None or evidence is None:
        st.info("Generate claims after ingesting a source.")
        return
    evidence_map = {item.evidence_id: item for item in evidence.evidence}
    for claim in claims.claims:
        with st.container(border=True):
            claim_col, evidence_col = st.columns((1, 1))
            with claim_col:
                st.subheader(claim.claim_id)
                relationship_message = (
                    f"{claim.relationship.upper()} · {claim.evidence_label.upper()} · "
                    f"review: {claim.review_status} · confidence: {claim.confidence:.2f}"
                )
                if claim.relationship == "direct":
                    st.success(relationship_message)
                elif claim.relationship == "inferred":
                    st.warning(relationship_message)
                else:
                    st.info(relationship_message)
                edited = st.text_area(
                    "Claim text",
                    claim.text,
                    key=f"claim-text-{claim.claim_id}",
                )
                if claim.scope:
                    st.caption(f"Scope: {claim.scope}")
                if claim.reasoning:
                    st.caption(f"Reasoning: {claim.reasoning}")
                if claim.limitation:
                    st.caption(f"Limitation: {claim.limitation}")
                note = st.text_input("Review note", key=f"claim-note-{claim.claim_id}")
                first, second = st.columns(2)
                with first:
                    _perform(
                        "Approve claim",
                        f"claim-approve-{claim.claim_id}",
                        approve_claim,
                        store,
                        claim.claim_id,
                        reviewer,
                    )
                    _perform(
                        "Save claim edit",
                        f"claim-edit-{claim.claim_id}",
                        edit_claim,
                        store,
                        claim.claim_id,
                        edited,
                        reviewer,
                    )
                with second:
                    _perform(
                        "Reject claim",
                        f"claim-reject-{claim.claim_id}",
                        reject_claim,
                        store,
                        claim.claim_id,
                        reviewer,
                        note or "Rejected in local reviewer",
                    )
                    _perform(
                        "Add claim note",
                        f"claim-add-note-{claim.claim_id}",
                        note_claim,
                        store,
                        claim.claim_id,
                        note,
                        reviewer,
                    )
            with evidence_col:
                st.markdown("#### Exact evidence")
                for evidence_id in claim.evidence_span_ids:
                    span = evidence_map.get(evidence_id)
                    if span is None:
                        st.error(f"Missing evidence span: {evidence_id}")
                        continue
                    location = (
                        span.printed_page_label
                        or (
                            f"PDF page {span.page_index + 1}"
                            if span.page_index is not None
                            else None
                        )
                        or span.section_heading
                        or "source location"
                    )
                    st.caption(
                        f"{span.evidence_id} · {location} · chars {span.char_start}–"
                        f"{span.char_end} · {span.locator}"
                    )
                    st.code(span.excerpt, language=None, wrap_lines=True)
                    if span.context and span.context != span.excerpt:
                        with st.expander(f"Limited context for {span.evidence_id}"):
                            st.text(span.context)
                    for warning in span.warnings:
                        st.warning(warning)
    _perform(
        "Approve every current claim",
        "claims-approve-all",
        approve_claims,
        store,
        reviewer,
    )


def _show_script(store: ProjectStore, reviewer: str) -> None:
    script = _load_if(store, "script/script.json", ScriptManifest)
    if script is None:
        st.info("Generate a script after approving claims.")
        return
    words = sum(len(segment.text.split()) for segment in script.segments)
    first, second = st.columns(2)
    first.metric("Spoken words", words)
    second.metric("Selected angle", script.angle)
    for segment in script.segments:
        with st.container(border=True):
            st.subheader(segment.segment_id)
            st.caption(
                f"{segment.segment_type.upper()} · {segment.approximate_duration:g} s · "
                f"review: {segment.review_status}"
            )
            edited = st.text_area(
                "Narration clause",
                segment.text,
                key=f"segment-text-{segment.segment_id}",
            )
            st.caption("Approved claim links: " + (", ".join(segment.claim_ids) or "none"))
            if segment.pronunciation_notes:
                st.caption(f"Pronunciation: {segment.pronunciation_notes}")
            note = st.text_input("Review note", key=f"segment-note-{segment.segment_id}")
            first, second, third, fourth = st.columns(4)
            with first:
                _perform(
                    "Approve",
                    f"segment-approve-{segment.segment_id}",
                    approve_script_segment,
                    store,
                    segment.segment_id,
                    reviewer,
                )
            with second:
                _perform(
                    "Save edit",
                    f"segment-edit-{segment.segment_id}",
                    edit_script_segment,
                    store,
                    segment.segment_id,
                    edited,
                    reviewer,
                )
            with third:
                _perform(
                    "Reject",
                    f"segment-reject-{segment.segment_id}",
                    reject_script_segment,
                    store,
                    segment.segment_id,
                    reviewer,
                    note or "Rejected in local reviewer",
                )
            with fourth:
                _perform(
                    "Add note",
                    f"segment-add-note-{segment.segment_id}",
                    note_script_segment,
                    store,
                    segment.segment_id,
                    note,
                    reviewer,
                )
    _perform("Approve complete script", "script-approve-all", approve_script, store, reviewer)


def _show_storyboard_and_assets(store: ProjectStore, reviewer: str) -> None:
    storyboard = _load_if(store, "storyboard/storyboard.json", StoryboardManifest)
    assets = _load_if(store, "assets/asset-manifest.json", AssetManifest)
    st.subheader("Storyboard scenes")
    if storyboard is None:
        st.info("Generate a storyboard after approving the script.")
    else:
        for scene in storyboard.scenes:
            with st.container(border=True):
                st.subheader(f"{scene.order + 1}. {scene.primitive}")
                st.caption(
                    f"{scene.scene_id} · starts {scene.start_time:g} s · {scene.duration:g} s · "
                    f"{scene.transition} · review: {scene.review_status}"
                )
                on_screen = st.text_area(
                    "On-screen text",
                    scene.on_screen_text,
                    key=f"scene-text-{scene.scene_id}",
                )
                accessibility = st.text_area(
                    "Accessibility description",
                    scene.accessibility_description,
                    key=f"scene-accessibility-{scene.scene_id}",
                )
                evidence_label = st.text_input(
                    "Evidence label",
                    scene.evidence_label or "",
                    key=f"scene-evidence-label-{scene.scene_id}",
                )
                visual_json = st.text_area(
                    "Structured visual specification (validated JSON; never executed)",
                    json.dumps(scene.visual.model_dump(mode="json"), indent=2),
                    height=240,
                    key=f"scene-visual-{scene.scene_id}",
                )
                st.caption(
                    "Script segments: "
                    + ", ".join(scene.script_segment_ids)
                    + " · Claims: "
                    + (", ".join(scene.claim_ids) or "none")
                )
                note = st.text_input("Review note", key=f"scene-note-{scene.scene_id}")
                first, second, third, fourth = st.columns(4)
                with first:
                    _perform(
                        "Approve",
                        f"scene-approve-{scene.scene_id}",
                        approve_scene,
                        store,
                        scene.scene_id,
                        reviewer,
                    )
                with second:
                    _perform(
                        "Save edit",
                        f"scene-edit-{scene.scene_id}",
                        _edit_scene_from_json,
                        store,
                        scene.scene_id,
                        on_screen,
                        accessibility,
                        evidence_label,
                        visual_json,
                        reviewer,
                    )
                with third:
                    _perform(
                        "Reject",
                        f"scene-reject-{scene.scene_id}",
                        reject_scene,
                        store,
                        scene.scene_id,
                        reviewer,
                        note or "Rejected in local reviewer",
                    )
                with fourth:
                    _perform(
                        "Add note",
                        f"scene-add-note-{scene.scene_id}",
                        note_scene,
                        store,
                        scene.scene_id,
                        note,
                        reviewer,
                    )
        _perform(
            "Approve complete storyboard",
            "storyboard-approve-all",
            approve_storyboard,
            store,
            reviewer,
        )

    st.subheader("Embedded asset rights")
    st.caption(
        "Unknown, restricted, and citation-only assets cannot be embedded. Verify every field "
        "before approving."
    )
    if assets is None or not assets.assets:
        st.warning(
            "No assets are registered; generate a storyboard to register bundled font rights."
        )
        return
    for asset in assets.assets:
        with st.container(border=True):
            st.subheader(asset.asset_id)
            st.caption(
                f"{asset.asset_type} · review: {asset.review_status} · SHA-256 {asset.sha256}"
            )
            origin = st.text_input("Origin", asset.origin, key=f"asset-origin-{asset.asset_id}")
            creator = st.text_input("Creator", asset.creator, key=f"asset-creator-{asset.asset_id}")
            source_url = st.text_input(
                "Source URL (optional)",
                asset.source_url or "",
                key=f"asset-url-{asset.asset_id}",
            )
            license_name = st.text_input(
                "License", asset.license, key=f"asset-license-{asset.asset_id}"
            )
            attribution = st.text_input(
                "Required attribution (optional)",
                asset.required_attribution or "",
                key=f"asset-attribution-{asset.asset_id}",
            )
            rights_status = st.selectbox(
                "Rights status",
                RIGHTS_STATUSES,
                index=RIGHTS_STATUSES.index(asset.rights_status),
                key=f"asset-rights-status-{asset.asset_id}",
            )
            embedding_allowed = st.checkbox(
                "Embedding is allowed",
                value=asset.embedding_allowed,
                key=f"asset-embedding-{asset.asset_id}",
            )
            st.caption(f"Project-local path: {asset.local_path}")
            note = st.text_input("Review note", key=f"asset-note-{asset.asset_id}")
            first, second, third, fourth = st.columns(4)
            with first:
                _perform(
                    "Approve",
                    f"asset-approve-{asset.asset_id}",
                    approve_asset,
                    store,
                    asset.asset_id,
                    reviewer,
                )
            with second:
                _perform(
                    "Save edit",
                    f"asset-edit-{asset.asset_id}",
                    _edit_asset_metadata,
                    store,
                    asset.asset_id,
                    origin,
                    creator,
                    source_url,
                    license_name,
                    attribution,
                    rights_status,
                    embedding_allowed,
                    reviewer,
                )
            with third:
                _perform(
                    "Reject",
                    f"asset-reject-{asset.asset_id}",
                    reject_asset,
                    store,
                    asset.asset_id,
                    reviewer,
                    note or "Rejected in local reviewer",
                )
            with fourth:
                _perform(
                    "Add note",
                    f"asset-add-note-{asset.asset_id}",
                    note_asset,
                    store,
                    asset.asset_id,
                    note,
                    reviewer,
                )
    _perform("Approve all asset rights", "rights-approve-all", approve_rights, store, reviewer)


def _show_narration(store: ProjectStore) -> None:
    narration = None
    narration_error = None
    try:
        narration = active_audio(store)
    except (OSError, ValueError) as exc:
        narration_error = str(exc)
    if narration_error:
        st.error(narration_error)
    elif narration:
        duration = probe_duration(narration)
        st.success(
            f"Active narration: {narration.name}"
            + (f" · {duration:.2f} s" if duration is not None else " · duration unavailable")
        )
        st.audio(str(narration))
    else:
        st.info("No narration is imported. Deterministic script timing remains available.")
    uploaded = st.file_uploader(
        "Import user-recorded narration",
        type=["wav", "mp3", "m4a", "aac", "flac", "ogg", "opus"],
        key="narration-upload",
    )
    rights_status = st.selectbox(
        "Narration rights assertion",
        AUDIO_RIGHTS_STATUSES,
        help="Unknown blocks export. Choose user-owned only if you own this recording.",
        key="narration-rights-status",
    )
    if uploaded is not None:
        _perform(
            "Import narration",
            "narration-import",
            _import_uploaded_audio,
            store,
            uploaded.name,
            bytes(uploaded.getbuffer()),
            rights_status,
        )
    else:
        st.button(
            "Import narration",
            key="narration-import-disabled",
            disabled=True,
            width="stretch",
        )
    _perform("Generate caption sidecars", "captions-generate", _generate_captions, store)
    for extension in ("srt", "vtt"):
        path = store.path(f"captions/captions.{extension}")
        if path.is_file():
            st.download_button(
                f"Download {extension.upper()}",
                path.read_bytes(),
                file_name=path.name,
                mime="text/plain",
                key=f"caption-download-{extension}",
            )
        else:
            st.warning(f"{extension.upper()} captions are missing.")
    st.caption(
        "When narration duration is readable, deterministic caption and scene timing scales to "
        "that duration. Optional transcription/alignment is not required."
    )


def _show_preview(store: ProjectStore) -> None:
    st.caption("Every preview has a visible UNREVIEWED watermark, even after other gates pass.")
    _perform("Render review preview", "preview-render", render_video, store, True)
    preview = store.path("renders/previews/preview.mp4")
    if preview.is_file():
        st.video(str(preview))
        st.caption(
            f"{preview.relative_to(store.root).as_posix()} · {preview.stat().st_size:,} bytes"
        )
    else:
        st.info("No preview exists yet.")
    contact_sheet = store.path("renders/previews/contact-sheet.png")
    if contact_sheet.is_file():
        st.subheader("Representative frames")
        st.image(str(contact_sheet), caption="Deterministic six-frame contact sheet")


def _show_qa(store: ProjectStore) -> None:
    first, second = st.columns(2)
    with first:
        _perform("Run preview QA", "qa-run-preview", _run_preview_qa, store)
    with second:
        _perform(
            "Generate cited evidence page",
            "qa-generate-evidence",
            generate_evidence_page,
            store,
            store.path("renders/previews/evidence.html"),
        )
    report = _load_if(store, "renders/previews/qa-report.json", QAReport)
    if report is None:
        st.info("Render a preview, then run QA.")
        return
    for check in report.checks:
        message = f"{check.check_id}: {check.message}"
        if check.status == "pass":
            st.success(message)
        elif check.status == "warning":
            st.warning(message)
        else:
            st.error(message)
    if report.export_blockers:
        st.error("Export blockers:\n\n- " + "\n- ".join(report.export_blockers))
    else:
        st.success("Preview QA has no hard blockers. Watch it before final approval.")


def _show_export(store: ProjectStore, reviewer: str) -> None:
    project = store.project()
    blockers = _export_blockers(store)
    pre_final_blockers = [
        item
        for item in blockers
        if not item.startswith("final gate") and item != "final render is missing"
    ]
    if blockers:
        st.error("Export is blocked:\n\n- " + "\n- ".join(blockers))
    else:
        st.success("All gates, artifact hashes, media checks, and rights checks are current.")
    _perform(
        "Approve reviewed preview for final export",
        "final-approve",
        approve_final,
        store,
        reviewer,
        disabled=bool(pre_final_blockers),
    )
    project = store.project()
    final_is_current = False
    if project.approvals.final == ReviewStatus.APPROVED:
        try:
            final_is_current = has_current_approval(store, "final", project.project_id)
        except (OSError, ValueError):
            final_is_current = False
    _perform(
        "Render and QA unwatermarked final",
        "final-render",
        _render_final,
        store,
        disabled=not final_is_current,
    )
    _perform(
        "Create portable export",
        "final-export",
        export_project,
        store,
        disabled=bool(_export_blockers(store)),
    )
    final_video = store.path("renders/final/final.mp4")
    if final_video.is_file():
        st.subheader("Final render")
        st.video(str(final_video))
    exported = store.path("export")
    files = sorted(path.name for path in exported.iterdir() if path.is_file())
    if files:
        st.subheader("Portable export files")
        st.write(files)


projects_root = Path(os.getenv("TECHSHORT_PROJECTS_ROOT", "projects"))
slugs = (
    sorted(path.name for path in projects_root.iterdir() if (path / "project.json").is_file())
    if projects_root.is_dir()
    else []
)
if not slugs:
    st.error("No projects found. Run `techshort init <slug>` and ingest a source first.")
    st.stop()

slug = st.sidebar.selectbox("Project", slugs, key="project-selector")
reviewer = st.sidebar.text_input(
    "Reviewer identifier",
    os.getenv("TECHSHORT_REVIEWER_ID", "local-reviewer"),
    key="reviewer-identifier",
)
step = st.sidebar.radio("Review step", STEPS, key="review-step")
store = ProjectStore(projects_root, slug)

if not reviewer.strip():
    st.error("Enter a local reviewer identifier before recording decisions.")
    st.stop()

if step == "1 Project":
    _show_project(store)
elif step == "2 Sources":
    _show_sources(store)
elif step == "3 Claims and evidence":
    _show_claims(store, reviewer)
elif step == "4 Script":
    _show_script(store, reviewer)
elif step == "5 Storyboard and assets":
    _show_storyboard_and_assets(store, reviewer)
elif step == "6 Narration and captions":
    _show_narration(store)
elif step == "7 Preview":
    _show_preview(store)
elif step == "8 QA":
    _show_qa(store)
else:
    _show_export(store, reviewer)

with st.sidebar.expander("Append-only review history"):
    log = _load_if(store, "reviews/review-log.json", ReviewLog)
    if log is None or not log.reviews:
        st.caption("No review decisions recorded yet.")
    else:
        for decision in reversed(log.reviews[-30:]):
            suffix = (
                f" · invalidated: {decision.invalidation_reason}"
                if decision.invalidated_at is not None
                else ""
            )
            st.text(
                f"{decision.timestamp.isoformat()} · {decision.decision} · "
                f"{decision.object_type}/{decision.object_id}{suffix}"
            )
