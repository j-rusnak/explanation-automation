from __future__ import annotations

import re
import shutil
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from techshort.domain.hashing import sha256_file
from techshort.domain.models import SourceDocument, SourceIndex
from techshort.domain.storage import ProjectStore, atomic_write_model, sanitize_filename

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_PAGES = 250


def _normalize(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def ingest_source(store: ProjectStore, source: Path) -> SourceDocument:
    if not source.is_file():
        raise ValueError("source does not exist or is not a regular file")
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("source exceeds the 25 MiB limit")
    suffix = source.suffix.lower()
    if suffix not in {".pdf", ".md", ".markdown", ".txt"}:
        raise ValueError("supported source types are PDF, Markdown, and text")
    safe_name = sanitize_filename(source.name)
    digest = sha256_file(source)
    source_id = f"source-{digest[:12]}"
    destination = store.path(f"sources/originals/{source_id}-{safe_name}")
    if not destination.exists():
        shutil.copyfile(source, destination)

    warnings: list[str] = []
    incomplete = False
    ocr_required = False
    sections: list[tuple[str, str]] = []
    metadata: dict[str, str] = {}
    if suffix == ".pdf":
        try:
            reader = PdfReader(destination, strict=True)
            if reader.is_encrypted:
                raise ValueError("encrypted PDFs are unsupported")
            if len(reader.pages) > MAX_PAGES:
                raise ValueError("PDF exceeds the 250-page limit")
            metadata = {str(k).lstrip("/"): str(v) for k, v in (reader.metadata or {}).items() if v}
            for index, page in enumerate(reader.pages):
                text = _normalize(page.extract_text() or "")
                sections.append((f"Page {index + 1}", text))
            nonempty = sum(len(text) for _, text in sections)
            if nonempty < max(30, len(sections) * 10):
                ocr_required = True
                incomplete = True
                warnings.append(
                    "PDF has little extractable text; OCR is required but unsupported in V1"
                )
        except PdfReadError as exc:
            raise ValueError(f"malformed PDF: {exc}") from exc
    else:
        raw = destination.read_text(encoding="utf-8", errors="strict")
        if suffix in {".md", ".markdown"}:
            current = "Document"
            buffer: list[str] = []
            for line in raw.splitlines():
                if line.startswith("#"):
                    if buffer:
                        sections.append((current, _normalize("\n".join(buffer))))
                    current = line.lstrip("#").strip() or "Untitled section"
                    buffer = []
                else:
                    buffer.append(line)
            if buffer or not sections:
                sections.append((current, _normalize("\n".join(buffer))))
        else:
            sections = [("Document", _normalize(raw))]

    indexed_parts: list[str] = []
    offset = 0
    section_rows: list[dict[str, str | int]] = []
    for index, (heading, text) in enumerate(sections):
        marker = f"\n\n--- {heading} ---\n"
        start = offset + len(marker)
        indexed_parts.append(marker + text)
        offset += len(marker) + len(text)
        section_rows.append({"index": index, "heading": heading, "start": start, "end": offset})
    normalized = "".join(indexed_parts).lstrip("\n")
    # Recompute offsets after stripping the first two newlines.
    shift = 2 if indexed_parts else 0
    for row in section_rows:
        row["start"] = int(row["start"]) - shift
        row["end"] = int(row["end"]) - shift
    extracted_path = store.path(f"sources/extracted/{source_id}.txt")
    extracted_path.write_text(normalized, encoding="utf-8", newline="\n")
    index_path = store.path(f"sources/extracted/{source_id}.sections.json")
    index_path.write_text(__import__("json").dumps(section_rows, indent=2), encoding="utf-8")
    document = SourceDocument(
        source_id=source_id,
        source_type="pdf"
        if suffix == ".pdf"
        else "markdown"
        if suffix in {".md", ".markdown"}
        else "text",
        original_filename=safe_name,
        content_hash=digest,
        local_path=destination.relative_to(store.root).as_posix(),
        page_or_section_count=len(sections),
        title=metadata.get("Title", source.stem),
        metadata=metadata,
        extraction_warnings=warnings,
        appears_incomplete=incomplete,
        ocr_required=ocr_required,
    )
    index_file = store.path("sources/source-index.json")
    existing = SourceIndex(sources=[])
    if index_file.exists():
        existing = SourceIndex.model_validate_json(index_file.read_text(encoding="utf-8"))
    existing.sources = [item for item in existing.sources if item.source_id != source_id] + [
        document
    ]
    atomic_write_model(index_file, existing)
    project = store.project()
    if source_id not in project.source_ids:
        project.source_ids.append(source_id)
    project.dependency_hashes[source_id] = digest
    project.stale_artifacts = ["claims", "script", "storyboard", "rights", "final"]
    project.downstream_valid = False
    store.save_project(project)
    return document


def resolve_evidence_text(store: ProjectStore, source_id: str, start: int, end: int) -> str:
    text = store.path(f"sources/extracted/{source_id}.txt").read_text(encoding="utf-8")
    if start < 0 or end > len(text) or start >= end:
        raise ValueError("evidence locator is outside extracted source")
    return text[start:end]
