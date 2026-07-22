from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    AssetManifest,
    ClaimsManifest,
    EvidenceManifest,
    RenderManifest,
    ReviewLog,
    ReviewStatus,
    ScriptManifest,
    SourceIndex,
    now_utc,
)
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_json,
    atomic_write_model,
    atomic_write_text,
    load_model,
)
from techshort.qa import run_qa
from techshort.review import (
    current_artifact_hashes,
    final_review_hash,
    has_current_approval,
)


def _source_authors(metadata: dict[str, str]) -> str | None:
    lowered = {key.lower(): value for key, value in metadata.items()}
    return lowered.get("author") or lowered.get("authors") or lowered.get("creator")


def build_evidence_ledger(store: ProjectStore) -> dict[str, Any]:
    project = store.project()
    sources = load_model(store.path("sources/source-index.json"), SourceIndex)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    review_log = load_model(store.path("reviews/review-log.json"), ReviewLog)
    evidence_by_id = {span.evidence_id: span for span in evidence.evidence}
    claim_by_id = {claim.claim_id: claim for claim in claims.claims}
    segments: list[dict[str, Any]] = []
    for segment in script.segments:
        citations: list[dict[str, Any]] = []
        for claim_id in segment.claim_ids:
            claim = claim_by_id[claim_id]
            for evidence_id in claim.evidence_span_ids:
                span = evidence_by_id[evidence_id]
                citations.append(
                    {
                        "claim_id": claim_id,
                        "evidence_id": evidence_id,
                        "source_id": span.source_id,
                        "evidence_label": claim.evidence_label,
                        "relationship": claim.relationship,
                        "page_index": span.page_index,
                        "printed_page_label": span.printed_page_label,
                        "section_heading": span.section_heading,
                        "locator": span.locator,
                        "excerpt": span.excerpt,
                    }
                )
        segments.append(
            {
                "segment_id": segment.segment_id,
                "type": segment.segment_type,
                "text": segment.text,
                "claim_ids": segment.claim_ids,
                "citations": citations,
            }
        )
    corrections = [
        {
            "timestamp": decision.timestamp.isoformat(),
            "object_type": decision.object_type,
            "object_id": decision.object_id,
            "decision": decision.decision,
        }
        for decision in review_log.reviews
        if decision.decision in {"edit", "reject"}
    ]
    return {
        "schema_version": "1.0.0",
        "project_id": project.project_id,
        "slug": project.slug,
        "title": project.title,
        "project_versions": project.active_versions,
        "generated_at": now_utc().isoformat(),
        "sources": [
            {
                "source_id": source.source_id,
                "title": source.title,
                "authors": _source_authors(source.metadata),
                "original_filename": source.original_filename,
                "content_hash": source.content_hash,
                "rights_status": source.rights_status,
            }
            for source in sources.sources
        ],
        "segments": segments,
        "limitations": [
            segment.text for segment in script.segments if segment.segment_type == "limitation"
        ],
        "assets": [
            {
                "asset_id": asset.asset_id,
                "type": asset.asset_type,
                "origin": asset.origin,
                "creator": asset.creator,
                "source_url": asset.source_url,
                "license": asset.license,
                "rights_status": asset.rights_status,
                "required_attribution": asset.required_attribution,
                "sha256": asset.sha256,
            }
            for asset in assets.assets
        ],
        "corrections": corrections,
    }


def _json_for_script(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def generate_evidence_page(store: ProjectStore, destination: Path) -> None:
    ledger = build_evidence_ledger(store)
    segments = ledger["segments"]
    sources = ledger["sources"]
    assets = ledger["assets"]
    limitations = ledger["limitations"]
    corrections = ledger["corrections"]
    assert isinstance(segments, list)
    assert isinstance(sources, list)
    assert isinstance(assets, list)
    assert isinstance(limitations, list)
    assert isinstance(corrections, list)
    summary_parts = [
        str(segment["text"])
        for segment in segments
        if isinstance(segment, dict) and segment.get("type") in {"hook", "factual"}
    ][:2]
    summary = " ".join(summary_parts)
    source_items = "".join(
        "<li><strong>{title}</strong>{authors}<br><span class='meta'>{filename} · "
        "SHA-256 {digest} · rights: {rights}</span></li>".format(
            title=html.escape(str(source["title"])),
            authors=(f" — {html.escape(str(source['authors']))}" if source.get("authors") else ""),
            filename=html.escape(str(source["original_filename"])),
            digest=html.escape(str(source["content_hash"])[:16]),
            rights=html.escape(str(source["rights_status"])),
        )
        for source in sources
        if isinstance(source, dict)
    )
    transcript_items: list[str] = []
    evidence_items: dict[str, str] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        citations = segment.get("citations", [])
        citation_links: list[str] = []
        if isinstance(citations, list):
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                evidence_id = str(citation["evidence_id"])
                citation_links.append(
                    f"<a href='#{html.escape(evidence_id)}'>{html.escape(evidence_id)}</a>"
                )
                locator = (
                    citation.get("printed_page_label")
                    or (
                        f"PDF page {int(citation['page_index']) + 1}"
                        if citation.get("page_index") is not None
                        else None
                    )
                    or citation.get("section_heading")
                    or "source location"
                )
                evidence_items[evidence_id] = (
                    f"<li id='{html.escape(evidence_id)}'><p><code>{html.escape(evidence_id)}</code> "
                    f"<span class='label'>{html.escape(str(citation['evidence_label']).upper())}</span> "
                    f"{html.escape(str(locator))}</p><blockquote>{html.escape(str(citation['excerpt']))}</blockquote>"
                    f"<p class='meta'>Claim {html.escape(str(citation['claim_id']))} · "
                    f"{html.escape(str(citation['relationship']))} · locator "
                    f"<code>{html.escape(str(citation['locator']))}</code></p></li>"
                )
        links = (
            f"<span class='citations'>Sources: {', '.join(citation_links)}</span>"
            if citation_links
            else ""
        )
        transcript_items.append(
            f"<li id='{html.escape(str(segment['segment_id']))}'><p>{html.escape(str(segment['text']))}</p>{links}</li>"
        )
    asset_items = (
        "".join(
            "<li><strong>{asset_id}</strong> — {creator}; {license}; {rights}. {attribution}</li>".format(
                asset_id=html.escape(str(asset["asset_id"])),
                creator=html.escape(str(asset["creator"])),
                license=html.escape(str(asset["license"])),
                rights=html.escape(str(asset["rights_status"])),
                attribution=html.escape(str(asset.get("required_attribution") or "")),
            )
            for asset in assets
            if isinstance(asset, dict)
        )
        or "<li>No external embedded assets.</li>"
    )
    correction_text = (
        f"{len(corrections)} edit or rejection event(s) are recorded in the local append-only review history."
        if corrections
        else "No corrections are recorded for this version."
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(str(ledger["title"]))} — evidence</title>
<style>
:root{{--ink:#172033;--muted:#4b5875;--paper:#fbfcff;--accent:#314bb8;--panel:#eef2ff}}
*{{box-sizing:border-box}}body{{max-width:56rem;margin:3rem auto;padding:0 1.2rem;font:18px/1.55 system-ui,sans-serif;color:var(--ink);background:var(--paper)}}
h1,h2{{line-height:1.15}}a{{color:var(--accent)}}code{{overflow-wrap:anywhere;background:#e5eaf8;padding:.12rem .3rem;border-radius:.2rem}}
blockquote{{border-left:4px solid var(--accent);margin-left:0;padding:.5rem 1rem;background:var(--panel)}}.meta{{color:var(--muted)}}
.label{{font-size:.78rem;font-weight:700;letter-spacing:.08em;background:#dfe6ff;padding:.2rem .35rem;border-radius:.2rem}}
.citations{{font-size:.9rem;color:var(--muted)}}li{{margin-bottom:1rem}}
</style></head><body>
<header><p class="meta">techshort evidence companion</p><h1>{html.escape(str(ledger["title"]))}</h1>
<p class="meta">Project {html.escape(str(ledger["project_id"]))} · storyboard version {html.escape(str(ledger["project_versions"].get("storyboard", "draft")))} · generated <time>{html.escape(str(ledger["generated_at"]))}</time></p></header>
<main><section><h2>Summary</h2><p>{html.escape(summary)}</p></section>
<section><h2>Transcript and segment sources</h2><ol>{"".join(transcript_items)}</ol></section>
<section><h2>Important limitation</h2>{"".join(f"<p>{html.escape(str(item))}</p>" for item in limitations)}</section>
<section><h2>Sources</h2><ul>{source_items}</ul></section>
<section><h2>Evidence ledger</h2><ol>{"".join(evidence_items.values())}</ol></section>
<section><h2>Asset rights and attribution</h2><ul>{asset_items}</ul></section>
<section><h2>Corrections and version information</h2><p>{html.escape(correction_text)}</p>
<p>This page contains short verification excerpts only; full source documents remain local.</p></section></main>
<script type="application/json" id="techshort-evidence">{_json_for_script(ledger)}</script>
</body></html>"""
    atomic_write_text(destination, page)
    atomic_write_json(destination.with_name("evidence-ledger.json"), ledger)


def _validate_final_gate(store: ProjectStore) -> None:
    project = store.project()
    if project.content_risk == "prohibited":
        raise ValueError("export blocked: prohibited content-risk classification")
    for gate in ("claims", "script", "storyboard", "rights", "final"):
        if getattr(project.approvals, gate) != ReviewStatus.APPROVED:
            raise ValueError(f"export blocked: {gate} gate is not approved")
    if not has_current_approval(store, "final", project.project_id):
        raise ValueError("export blocked: final approval record is missing or stale")
    expected = final_review_hash(store)
    if project.dependency_hashes.get("final_approval") != expected:
        raise ValueError("export blocked: final approval no longer matches the reviewed preview")


def export_project(store: ProjectStore) -> Path:
    _validate_final_gate(store)
    final_video = store.path("renders/final/final.mp4")
    if not final_video.is_file():
        raise ValueError("export blocked: render the final video first")
    final_report = run_qa(
        store,
        final_video,
        destination="renders/final/qa-report.json",
    )
    if not final_report.passed:
        raise ValueError(
            f"export blocked by final media QA: {'; '.join(final_report.export_blockers)}"
        )
    if final_report.artifact_hashes != current_artifact_hashes(store):
        raise ValueError("export blocked: final QA artifact snapshot is stale")
    if final_report.media_hash != sha256_file(final_video):
        raise ValueError("export blocked: final QA media hash is stale")

    required_inputs = {
        "srt": store.path("captions/captions.srt"),
        "vtt": store.path("captions/captions.vtt"),
        "cover": store.path("renders/final/cover.png"),
        "render-manifest": store.path("renders/final/render-manifest.json"),
    }
    missing = [name for name, path in required_inputs.items() if not path.is_file()]
    if missing:
        raise ValueError(f"export blocked: required output is missing: {missing[0]}")
    render_manifest = load_model(required_inputs["render-manifest"], RenderManifest)
    final_relative = final_video.relative_to(store.root).as_posix()
    if render_manifest.watermarked:
        raise ValueError("export blocked: final render manifest says the video is watermarked")
    if render_manifest.output_hashes.get(final_relative) != sha256_file(final_video):
        raise ValueError("export blocked: final render manifest does not match the video")

    out = store.path("export")
    out.mkdir(parents=True, exist_ok=True)
    allowed_names = {
        f"{store.slug}.mp4",
        f"{store.slug}.srt",
        f"{store.slug}.vtt",
        "cover.png",
        "transcript.txt",
        "evidence.html",
        "evidence-ledger.json",
        "asset-rights.json",
        "qa-report.json",
        "render-manifest.json",
    }
    unexpected = [path.name for path in out.iterdir() if path.name not in allowed_names]
    if unexpected:
        raise ValueError(
            f"export directory contains an unexpected file; move it before export: {unexpected[0]}"
        )

    _archive_existing_export(store, out, allowed_names)

    atomic_copy_file(final_video, out / f"{store.slug}.mp4")
    atomic_copy_file(required_inputs["srt"], out / f"{store.slug}.srt")
    atomic_copy_file(required_inputs["vtt"], out / f"{store.slug}.vtt")
    atomic_copy_file(required_inputs["cover"], out / "cover.png")
    script = load_model(store.path("script/script.json"), ScriptManifest)
    atomic_write_text(
        out / "transcript.txt",
        "\n".join(segment.text for segment in script.segments) + "\n",
    )
    generate_evidence_page(store, out / "evidence.html")
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    atomic_write_model(out / "asset-rights.json", assets)
    atomic_copy_file(store.path("renders/final/qa-report.json"), out / "qa-report.json")
    atomic_copy_file(required_inputs["render-manifest"], out / "render-manifest.json")

    produced = {path.name for path in out.iterdir() if path.is_file()}
    if produced != allowed_names:
        missing_outputs = sorted(allowed_names - produced)
        raise ValueError(f"export is incomplete: missing {missing_outputs[0]}")
    return out


def _archive_existing_export(
    store: ProjectStore, export_directory: Path, allowed_names: set[str]
) -> None:
    """Version a previous approved bundle before any atomic file is replaced."""

    existing = [
        path for path in export_directory.iterdir() if path.is_file() and path.name in allowed_names
    ]
    if not existing:
        return
    identity = stable_hash({path.name: sha256_file(path) for path in sorted(existing)})
    archive = store.path(f"export-history/{identity[:16]}")
    for source in existing:
        destination = archive / source.name
        if destination.is_file():
            if sha256_file(destination) != sha256_file(source):
                raise ValueError("export history contains a conflicting archived bundle")
            continue
        atomic_copy_file(source, destination)
