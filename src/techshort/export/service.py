from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from techshort.domain.models import (
    AssetManifest,
    EvidenceManifest,
    QAReport,
    ReviewStatus,
    ScriptManifest,
    SourceIndex,
)
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model


def generate_evidence_page(store: ProjectStore, destination: Path) -> None:
    project = store.project()
    sources = load_model(store.path("sources/source-index.json"), SourceIndex)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    assets_path = store.path("assets/asset-manifest.json")
    assets = (
        load_model(assets_path, AssetManifest)
        if assets_path.exists()
        else AssetManifest(version_id="assets-empty")
    )
    ledger = {
        "project_id": project.project_id,
        "version": project.active_versions,
        "segments": [
            {"id": s.segment_id, "text": s.text, "claim_ids": s.claim_ids} for s in script.segments
        ],
        "evidence": [
            {
                "id": e.evidence_id,
                "source_id": e.source_id,
                "locator": e.locator,
                "excerpt": e.excerpt,
            }
            for e in evidence.evidence
        ],
    }
    limitations = [s.text for s in script.segments if s.segment_type == "limitation"]
    transcript = " ".join(s.text for s in script.segments)
    source_items = "".join(
        f"<li><strong>{html.escape(s.title)}</strong> — {html.escape(s.original_filename)} ({html.escape(s.content_hash[:12])})</li>"
        for s in sources.sources
    )
    evidence_items = "".join(
        f"<li id='{html.escape(e.evidence_id)}'><code>{html.escape(e.evidence_id)}</code> — {html.escape(e.section_heading or e.printed_page_label or 'source')}<blockquote>{html.escape(e.excerpt)}</blockquote></li>"
        for e in evidence.evidence
    )
    asset_items = (
        "".join(
            f"<li>{html.escape(a.asset_id)} — {html.escape(a.rights_status)}; {html.escape(a.required_attribution or 'no attribution required')}</li>"
            for a in assets.assets
        )
        or "<li>No external embedded assets.</li>"
    )
    page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>{html.escape(project.title)} — evidence</title><style>body{{max-width:52rem;margin:3rem auto;padding:0 1rem;font:18px/1.55 system-ui;color:#172033;background:#fbfcff}}h1,h2{{line-height:1.15}}code{{background:#e8edf8;padding:.15rem .35rem}}blockquote{{border-left:4px solid #5167d8;margin-left:0;padding-left:1rem}}.meta{{color:#4b5875}}</style></head><body><h1>{html.escape(project.title)}</h1><p class='meta'>Project {html.escape(project.project_id)} · version {html.escape(project.active_versions.get("storyboard", "draft"))}</p><h2>Summary and transcript</h2><p>{html.escape(transcript)}</p><h2>Important limitation</h2>{"".join(f"<p>{html.escape(x)}</p>" for x in limitations)}<h2>Sources</h2><ul>{source_items}</ul><h2>Evidence ledger</h2><ol>{evidence_items}</ol><h2>Asset rights and attribution</h2><ul>{asset_items}</ul><h2>Corrections</h2><p>This local export has no recorded corrections. Regenerate the export after any approved correction.</p><script type='application/json' id='techshort-evidence'>{html.escape(json.dumps(ledger, separators=(",", ":")))}</script></body></html>"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8", newline="\n")


def export_project(store: ProjectStore) -> Path:
    project = store.project()
    for gate in ("claims", "script", "storyboard", "rights", "final"):
        if getattr(project.approvals, gate) != ReviewStatus.APPROVED:
            raise ValueError(f"export blocked: {gate} gate is not approved")
    qa = load_model(store.path("renders/previews/qa-report.json"), QAReport)
    if not qa.passed:
        raise ValueError(f"export blocked by QA: {'; '.join(qa.export_blockers)}")
    source_video = store.path("renders/final/final.mp4")
    if not source_video.exists():
        raise ValueError("export blocked: render the final video first")
    out = store.path("export")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_video, out / f"{store.slug}.mp4")
    for suffix in ("srt", "vtt"):
        shutil.copyfile(store.path(f"captions/captions.{suffix}"), out / f"{store.slug}.{suffix}")
    script = load_model(store.path("script/script.json"), ScriptManifest)
    (out / "transcript.txt").write_text(
        "\n".join(s.text for s in script.segments) + "\n", encoding="utf-8"
    )
    generate_evidence_page(store, out / "evidence.html")
    # A standalone ledger mirrors the concise machine-readable page data.
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    (out / "evidence-ledger.json").write_text(
        json.dumps(evidence.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    assets_path = store.path("assets/asset-manifest.json")
    assets = (
        load_model(assets_path, AssetManifest)
        if assets_path.exists()
        else AssetManifest(version_id="assets-empty")
    )
    atomic_write_model(out / "asset-rights.json", assets)
    shutil.copyfile(store.path("renders/previews/qa-report.json"), out / "qa-report.json")
    shutil.copyfile(store.path("renders/final/render-manifest.json"), out / "render-manifest.json")
    cover = store.path("renders/final/cover.png")
    if cover.exists():
        shutil.copyfile(cover, out / "cover.png")
    return out
