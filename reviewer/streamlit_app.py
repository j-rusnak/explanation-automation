from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar, cast

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from techshort.alignment import cues_from_script, write_caption_files
from techshort.audio import (
    active_audio,
    active_transcript,
    import_audio,
    import_transcript,
    probe_duration,
    set_narration_mode,
)
from techshort.domain.creative import EditorialCritique, VisualCritique
from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    AngleSelection,
    AnglesManifest,
    AssetManifest,
    ClaimCritiqueReport,
    ClaimsManifest,
    CoverCandidate,
    CoverManifest,
    CoverSelection,
    EvidenceManifest,
    QAReport,
    RenderManifest,
    ReviewLog,
    ReviewStatus,
    ScriptManifest,
    SourceIndex,
    StoryboardManifest,
)
from techshort.domain.storage import ProjectStore, load_model, sanitize_filename
from techshort.export import export_project, generate_evidence_page
from techshort.generation import select_angle
from techshort.generation.design import (
    generate_fixture_covers,
    select_cover,
    selected_cover_payload,
)
from techshort.generation.editorial import (
    build_rolling_shutter_beat_plan,
    build_rolling_shutter_brief,
    build_rolling_shutter_storyboard_guidance,
    critique_editorial,
    critique_visual,
)
from techshort.qa import run_qa
from techshort.qa.creative import (
    CreativeCoverInput,
    creative_input_from_manifests,
    evaluate_creative_quality,
)
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
THEMES = ("blueprint", "signal-lab", "technical-editorial")
NARRATION_MODES = ("narrated", "silent-reviewed")
LAYOUT_PRESETS = ("hero", "full-diagram", "split", "evidence", "numeric", "limitation")
MOTION_PRESETS = ("calm", "precise", "energetic")

ArtTheme = Literal["midnight", "blueprint", "signal-lab", "technical-editorial"]
NarrationMode = Literal["narrated", "silent-reviewed"]

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


def _set_project_theme(store: ProjectStore, theme: str) -> None:
    if theme not in THEMES:
        raise ValueError(f"unsupported art direction: {theme}")
    project = store.project()
    if project.theme == theme:
        return
    project = store.invalidate_from("storyboard", f"art direction changed to {theme}")
    project.theme = cast(ArtTheme, theme)
    store.save_project(project)


def _set_narration_mode(store: ProjectStore, mode: str) -> None:
    if mode not in NARRATION_MODES:
        raise ValueError(f"unsupported narration mode: {mode}")
    set_narration_mode(store, cast(NarrationMode, mode))


def _cover_preview(candidate: CoverCandidate) -> Image.Image:
    """Create a safe, deterministic reviewer still from validated cover data."""

    palettes = {
        "blueprint": {
            "background": "#071726",
            "surface": "#0F3046",
            "text": "#F3FAFF",
            "muted": "#A7C2D4",
            "accent": "#27D3E2",
            "signal": "#FFCA58",
        },
        "signal-lab": {
            "background": "#061916",
            "surface": "#10352D",
            "text": "#F0FFF9",
            "muted": "#A9D4C5",
            "accent": "#37E6A0",
            "signal": "#FFCF5B",
        },
        "technical-editorial": {
            "background": "#F2EBDD",
            "surface": "#FFF9EF",
            "text": "#18242B",
            "muted": "#5E6C70",
            "accent": "#D74E32",
            "signal": "#187A8C",
        },
    }
    colors = palettes[candidate.palette]
    image = Image.new("RGB", (360, 640), colors["background"])
    draw = ImageDraw.Draw(image)
    small = ImageFont.load_default(size=14)
    body = ImageFont.load_default(size=18)
    headline = ImageFont.load_default(size=31)

    draw.rounded_rectangle((22, 24, 338, 356), radius=22, fill=colors["surface"])
    draw.text((30, 38), candidate.palette.upper(), fill=colors["accent"], font=small)
    hero = candidate.hero
    if hero.kind == "scanline":
        draw.line((102, 96, 102, 310), fill=colors["muted"], width=5)
        for index in range(15):
            y = 94 + index * 14
            progress = index / 14
            shift = int(hero.distortion * progress * progress * 74)
            draw.line(
                (218 + shift, y, 278 + shift, y),
                fill=colors["signal"] if index % 3 == 0 else colors["accent"],
                width=7,
            )
        draw.line((46, 204, 160, 204), fill=colors["accent"], width=8)
        draw.text((40, 322), "STRAIGHT", fill=colors["muted"], font=small)
        draw.text((215, 322), "ROW SAMPLES", fill=colors["muted"], font=small)
    elif hero.kind == "comparison":
        draw.rounded_rectangle((42, 90, 172, 308), radius=14, outline=colors["muted"], width=2)
        draw.rounded_rectangle((188, 90, 318, 308), radius=14, outline=colors["accent"], width=3)
        draw.line((76, 120, 136, 278), fill=colors["text"], width=9)
        draw.line((205, 120, 292, 278), fill=colors["signal"], width=9)
        draw.text((54, 320), hero.before_label.upper(), fill=colors["muted"], font=small)
        draw.text((202, 320), hero.after_label.upper(), fill=colors["accent"], font=small)
    else:
        positions = {
            node.id: (int(40 + node.x * 280), int(78 + node.y * 226)) for node in hero.nodes
        }
        for edge in hero.edges:
            draw.line(
                (*positions[edge.source], *positions[edge.target]), fill=colors["muted"], width=3
            )
        for node in hero.nodes:
            x, y = positions[node.id]
            fill = colors["signal"] if node.state == "active" else colors["accent"]
            draw.ellipse((x - 22, y - 22, x + 22, y + 22), fill=fill)
            label = "\n".join(textwrap.wrap(node.label, width=12))
            draw.multiline_text(
                (x - 35, y + 28), label, fill=colors["text"], font=small, align="center"
            )

    y = 386
    for line in textwrap.wrap(candidate.headline, width=20):
        draw.text((28, y), line, fill=colors["text"], font=headline)
        y += 38
    if candidate.subheadline:
        y += 8
        for line in textwrap.wrap(candidate.subheadline, width=34)[:3]:
            draw.text((30, y), line, fill=colors["muted"], font=body)
            y += 24
    draw.text((30, 606), candidate.layout.upper(), fill=colors["accent"], font=small)
    return image


def _editorial_reviews(
    store: ProjectStore,
) -> tuple[EditorialCritique, VisualCritique] | None:
    claims = _load_if(store, "claims/claims.json", ClaimsManifest)
    angles = _load_if(store, "script/angles.json", AnglesManifest)
    selection = _load_if(store, "script/angle-selection.json", AngleSelection)
    script = _load_if(store, "script/script.json", ScriptManifest)
    if claims is None or angles is None or selection is None or script is None:
        return None
    brief = build_rolling_shutter_brief(claims, angles, selection)
    plan = build_rolling_shutter_beat_plan(brief)
    guidance = build_rolling_shutter_storyboard_guidance(brief, plan, script)
    return critique_editorial(brief, plan, script), critique_visual(brief, plan, guidance, script)


def _show_editorial_findings(store: ProjectStore, kind: Literal["editorial", "visual"]) -> None:
    try:
        reviews = _editorial_reviews(store)
    except (OSError, ValueError) as exc:
        st.warning(f"{kind.title()} critique unavailable: {exc}")
        return
    if reviews is None:
        st.info(f"{kind.title()} critique becomes available after angle and script generation.")
        return
    critique = reviews[0] if kind == "editorial" else reviews[1]
    st.subheader(f"{kind.title()} critique")
    st.caption("Deterministic production feedback; findings are advisory and never approval.")
    if not critique.findings:
        st.success(f"No {kind} critique findings for the current inputs.")
        return
    for finding in critique.findings:
        object_id = getattr(finding, "segment_id", None) or getattr(finding, "scene_key", None)
        message = f"{finding.category}: {finding.message}"
        if object_id:
            message += f" ({object_id})"
        if finding.severity == "error":
            st.error(message)
        else:
            st.warning(message)


def _show_cover_candidates(store: ProjectStore) -> None:
    st.subheader("Cover directions")
    st.caption(
        "Three evidence-linked directions are generated from the selected angle. The stills "
        "below are deterministic reviewer schematics; Remotion produces the export cover."
    )
    _perform(
        "Generate three cover directions",
        "covers-generate",
        generate_fixture_covers,
        store,
    )
    covers = _load_if(store, "storyboard/covers.json", CoverManifest)
    if covers is None:
        st.info("Generate a storyboard and choose an angle before creating cover directions.")
        return
    selected_id: str | None = None
    try:
        selected_id = cast(str, selected_cover_payload(store)["selected_candidate_id"])
    except (OSError, ValueError, KeyError):
        st.warning("Choose one current cover direction before storyboard approval.")
    columns = st.columns(3)
    for column, candidate in zip(columns, covers.candidates, strict=True):
        with column, st.container(border=True):
            st.image(
                _cover_preview(candidate),
                caption=candidate.accessibility_description,
                width="stretch",
            )
            st.markdown(f"#### {candidate.headline}")
            if candidate.subheadline:
                st.write(candidate.subheadline)
            st.caption(f"{candidate.layout} · {candidate.palette} · hero: {candidate.hero.kind}")
            st.caption(
                f"{len(candidate.claim_ids)} claim link(s) · "
                f"{len(candidate.evidence_ids)} evidence link(s)"
            )
            if selected_id == candidate.candidate_id:
                st.success("Selected cover direction")
            _perform(
                "Select this cover",
                f"cover-select-{candidate.candidate_id}",
                select_cover,
                store,
                candidate.candidate_id,
                disabled=selected_id == candidate.candidate_id,
            )
    st.warning(
        "Selecting or regenerating a cover invalidates storyboard and final review so the new "
        "visual direction is explicitly re-approved."
    )


def _show_creative_findings(store: ProjectStore) -> None:
    storyboard = _load_if(store, "storyboard/storyboard.json", StoryboardManifest)
    script = _load_if(store, "script/script.json", ScriptManifest)
    covers = _load_if(store, "storyboard/covers.json", CoverManifest)
    selection = _load_if(store, "storyboard/cover-selection.json", CoverSelection)
    if storyboard is None or script is None or covers is None or selection is None:
        st.info("Creative QA becomes available after script, storyboard, and cover selection.")
        return
    try:
        selected_cover_payload(store)
        candidate = next(
            item
            for item in covers.candidates
            if item.candidate_id == selection.selected_candidate_id
        )
        cover = CreativeCoverInput(
            cover_id=candidate.candidate_id,
            headline=candidate.headline,
            focal_visual=candidate.hero.kind,
            layout=candidate.layout,
            subtitle=candidate.subheadline,
            citation="Evidence-linked source receipt",
            factual=True,
        )
        snapshot = creative_input_from_manifests(
            storyboard,
            script,
            cues_from_script(script),
            cover,
            case_id=store.project().project_id,
            topic_kind="mechanism",
        )
        result = evaluate_creative_quality(snapshot)
    except (OSError, StopIteration, ValueError) as exc:
        st.warning(f"Creative QA unavailable: {exc}")
        return
    st.subheader("Creative quality review")
    st.metric("Creative QA score", f"{result.score}/100", result.status.upper())
    for check in result.checks:
        message = f"{check.category} · {check.message}"
        if check.remediation:
            message += f" Next: {check.remediation}"
        if check.status == "failure":
            st.error(message)
        elif check.status == "warning":
            st.warning(message)
        else:
            st.success(message)


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
    creator: str,
    license_name: str,
    source_url: str,
    required_attribution: str,
) -> Path:
    if len(uploaded_bytes) > 200 * 1024 * 1024:
        raise ValueError("audio exceeds the 200 MiB limit")
    filename = sanitize_filename(uploaded_name)
    with tempfile.TemporaryDirectory(prefix="techshort-audio-") as temporary:
        staged = Path(temporary) / filename
        staged.write_bytes(uploaded_bytes)
        return import_audio(
            store,
            staged,
            rights_status,
            creator=creator or None,
            license_name=license_name or None,
            source_url=source_url or None,
            required_attribution=required_attribution or None,
        )


def _import_uploaded_transcript(
    store: ProjectStore, uploaded_name: str, uploaded_bytes: bytes
) -> Path:
    if len(uploaded_bytes) > 128 * 1024:
        raise ValueError("narration transcript exceeds the 128 KiB safety limit")
    filename = sanitize_filename(uploaded_name)
    with tempfile.TemporaryDirectory(prefix="techshort-transcript-") as temporary:
        staged = Path(temporary) / filename
        staged.write_bytes(uploaded_bytes)
        return import_transcript(store, staged)


def _edit_scene_from_json(
    store: ProjectStore,
    scene_id: str,
    on_screen_text: str,
    accessibility_description: str,
    evidence_label: str,
    citation_label: str,
    layout: str,
    motion: str,
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
            "citation_label": citation_label.strip() or None,
            "layout": layout,
            "motion": motion,
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
            "narration mode": project.narration_mode,
        }
    )
    st.subheader("Art direction and delivery")
    st.caption(
        "Art direction controls the renderer's color, typography, and graphic language. "
        "Changing it invalidates storyboard approval because reviewers must see the result."
    )
    current_theme = project.theme if project.theme in THEMES else "blueprint"
    theme = st.selectbox(
        "Art direction",
        THEMES,
        index=THEMES.index(current_theme),
        key="project-theme",
        help=(
            "Blueprint emphasizes diagrams, Signal Lab emphasizes active measurements, and "
            "Technical Editorial uses a warmer publication-like treatment. Midnight is the "
            "legacy compatibility theme."
        ),
    )
    _perform(
        "Apply art direction",
        "project-theme-apply",
        _set_project_theme,
        store,
        theme,
        disabled=theme == project.theme,
    )
    narration_mode = st.selectbox(
        "Narration mode",
        NARRATION_MODES,
        index=NARRATION_MODES.index(project.narration_mode),
        key="project-narration-mode",
        help=(
            "Narrated requires reviewed imported audio. Silent-reviewed is an explicit human "
            "choice for caption-led output, not an automatic fallback for missing audio."
        ),
    )
    _perform(
        "Apply narration mode",
        "project-narration-mode-apply",
        _set_narration_mode,
        store,
        narration_mode,
        disabled=narration_mode == project.narration_mode,
    )
    if project.narration_mode == "silent-reviewed":
        st.warning("This project is explicitly configured for a human-reviewed silent export.")
    else:
        st.info("This project requires reviewed narration before final export.")
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
    critique = _load_if(store, "claims/critique.json", ClaimCritiqueReport)
    if critique is None:
        st.warning("The independent claim critique report is missing; regenerate claims.")
    else:
        with st.container(border=True):
            st.subheader("Independent critique")
            st.caption(
                f"{critique.provider} pass · {len(critique.issues)} candidate issue(s) · "
                "critique is not approval"
            )
            st.write(critique.summary)
            for issue in critique.issues:
                message = (
                    f"{issue.severity.upper()} · {issue.category} · {issue.claim_id}: "
                    f"{issue.message}"
                )
                if issue.severity == "warning":
                    st.warning(message)
                else:
                    st.error(message)
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
    angles = _load_if(store, "script/angles.json", AnglesManifest)
    selection = _load_if(store, "script/angle-selection.json", AngleSelection)
    st.subheader("Explainer angle")
    if angles is None:
        st.info(
            "Generate the three candidates with `techshort script angles <project>`, then "
            "select one before script generation."
        )
    else:
        project = store.project()
        if project.active_versions.get("angles") != angles.version_id:
            st.warning("These angle candidates are stale; regenerate them from current claims.")
        for candidate in angles.candidates:
            with st.container(border=True):
                st.markdown(f"#### {candidate.title}")
                st.caption(candidate.angle)
                st.write(candidate.rationale)
                st.caption("Central approved claims: " + ", ".join(candidate.central_claim_ids))
                is_selected = bool(
                    selection
                    and selection.angles_version_id == angles.version_id
                    and selection.selected_angle == candidate.angle
                    and project.active_versions.get("angle_selection") == selection.selection_id
                )
                if is_selected:
                    st.success("Selected for the current script")
                _perform(
                    "Select this angle",
                    f"angle-select-{candidate.angle}",
                    select_angle,
                    store,
                    candidate.angle,
                    disabled=is_selected
                    or project.active_versions.get("angles") != angles.version_id,
                )

    script = _load_if(store, "script/script.json", ScriptManifest)
    if script is None:
        st.info("Generate a script after approving claims.")
        return
    words = sum(len(segment.text.split()) for segment in script.segments)
    first, second = st.columns(2)
    first.metric("Spoken words", words)
    second.metric("Selected angle", script.angle)
    _show_editorial_findings(store, "editorial")
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
    preview_manifest = _load_if(
        store,
        "renders/previews/render-manifest.json",
        RenderManifest,
    )
    st.subheader("Storyboard scenes")
    if storyboard is None:
        st.info("Generate a storyboard after approving the script.")
    else:
        _show_cover_candidates(store)
        _show_editorial_findings(store, "visual")
        st.subheader("Scene review")
        for scene in storyboard.scenes:
            with st.container(border=True):
                st.subheader(f"{scene.order + 1}. {scene.primitive}")
                still = store.path(f"renders/previews/scene-still-{scene.scene_id}.png")
                still_relative = still.relative_to(store.root).as_posix()
                still_is_current = (
                    preview_manifest is not None
                    and preview_manifest.storyboard_hash == stable_hash(storyboard)
                    and still.is_file()
                    and preview_manifest.output_hashes.get(still_relative) == sha256_file(still)
                )
                if still_is_current:
                    st.image(
                        still,
                        caption=f"Representative frame from {scene.scene_id}",
                        width=270,
                    )
                else:
                    st.caption(
                        "Render a current preview to inspect this scene's representative still."
                    )
                st.caption(
                    f"{scene.scene_id} · starts {scene.start_time:g} s · {scene.duration:g} s · "
                    f"{scene.transition} · {scene.layout} layout · {scene.motion} motion · "
                    f"review: {scene.review_status}"
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
                citation_label = st.text_input(
                    "Human-readable citation label",
                    scene.citation_label or "",
                    key=f"scene-citation-label-{scene.scene_id}",
                    help="Use a short source or evidence description; keep internal IDs hidden.",
                )
                layout_col, motion_col = st.columns(2)
                layout = layout_col.selectbox(
                    "Layout preset",
                    LAYOUT_PRESETS,
                    index=LAYOUT_PRESETS.index(scene.layout),
                    key=f"scene-layout-{scene.scene_id}",
                )
                motion = motion_col.selectbox(
                    "Motion treatment",
                    MOTION_PRESETS,
                    index=MOTION_PRESETS.index(scene.motion),
                    key=f"scene-motion-{scene.scene_id}",
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
                        citation_label,
                        layout,
                        motion,
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
    project = store.project()
    st.subheader("Narration mode")
    selected_mode = st.selectbox(
        "Delivery mode",
        NARRATION_MODES,
        index=NARRATION_MODES.index(project.narration_mode),
        key="narration-step-mode",
    )
    _perform(
        "Apply delivery mode",
        "narration-step-mode-apply",
        _set_narration_mode,
        store,
        selected_mode,
        disabled=selected_mode == project.narration_mode,
    )
    if project.narration_mode == "silent-reviewed":
        st.warning(
            "Silent-reviewed is an explicit approval path. Captions and visual pacing still "
            "require review."
        )
    else:
        st.info("Narrated mode requires imported, rights-cleared narration for final export.")
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
    creator = st.text_input(
        "Narration creator",
        help="Required with an explicit license; recommended for every recording.",
        key="narration-creator",
    )
    license_name = st.text_input(
        "Narration license (required for permissively licensed audio)",
        key="narration-license",
    )
    source_url = st.text_input(
        "Narration source URL (optional)",
        key="narration-source-url",
    )
    required_attribution = st.text_input(
        "Narration required attribution (optional)",
        key="narration-attribution",
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
            creator,
            license_name,
            source_url,
            required_attribution,
        )
    else:
        st.button(
            "Import narration",
            key="narration-import-disabled",
            disabled=True,
            width="stretch",
        )
    transcript = None
    transcript_error = None
    if narration:
        try:
            transcript = active_transcript(store)
        except (OSError, ValueError) as exc:
            transcript_error = str(exc)
    if transcript_error:
        st.error(transcript_error)
    elif transcript:
        st.success(f"Hash-bound narration transcript: {transcript[1].name}")
        with st.expander("Review narration transcript"):
            st.text(transcript[0])
    transcript_upload = st.file_uploader(
        "Import a UTF-8 narration transcript",
        type=["txt"],
        key="narration-transcript-upload",
        help="The transcript is bound to the exact active audio hash and used for QA comparison.",
    )
    if narration is not None and transcript_upload is not None:
        _perform(
            "Import transcript",
            "narration-transcript-import",
            _import_uploaded_transcript,
            store,
            transcript_upload.name,
            bytes(transcript_upload.getbuffer()),
        )
    else:
        st.button(
            "Import transcript",
            key="narration-transcript-import-disabled",
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
        "that duration. A hash-bound transcript enables deterministic narration-to-script QA; "
        "otherwise final review must compare the recording manually."
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
    _show_creative_findings(store)
    st.subheader("Technical and export QA")
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
