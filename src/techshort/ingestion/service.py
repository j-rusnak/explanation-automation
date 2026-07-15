from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from techshort.domain.hashing import sha256_bytes, sha256_file
from techshort.domain.models import SourceDocument, SourceIndex
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_json,
    atomic_write_model,
    atomic_write_text,
    load_model,
    sanitize_filename,
)

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
    index_file = store.path("sources/source-index.json")
    existing_index = (
        load_model(index_file, SourceIndex) if index_file.exists() else SourceIndex(sources=[])
    )
    project = store.project()
    previous_active_source_id = existing_index.active_source_id or project.active_source_id
    previous = next((item for item in existing_index.sources if item.source_id == source_id), None)
    destination = store.path(
        previous.local_path
        if previous is not None
        else f"sources/originals/{source_id}-{safe_name}"
    )
    original_was_repaired = destination.exists() and sha256_file(destination) != digest
    if not destination.exists() or original_was_repaired:
        atomic_copy_file(source, destination)

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
        try:
            raw = destination.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("text sources must be valid UTF-8") from exc
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
    previous_extracted_hash = sha256_file(extracted_path) if extracted_path.exists() else None
    extracted_hash = sha256_bytes(normalized.encode("utf-8"))
    atomic_write_text(extracted_path, normalized)
    index_path = store.path(f"sources/extracted/{source_id}.sections.json")
    atomic_write_json(index_path, section_rows)
    document = SourceDocument(
        source_id=source_id,
        source_type="pdf"
        if suffix == ".pdf"
        else "markdown"
        if suffix in {".md", ".markdown"}
        else "text",
        original_filename=safe_name,
        content_hash=digest,
        extracted_text_hash=extracted_hash,
        local_path=destination.relative_to(store.root).as_posix(),
        page_or_section_count=len(sections),
        title=metadata.get("Title", source.stem),
        metadata=metadata,
        extraction_warnings=warnings,
        appears_incomplete=incomplete,
        ocr_required=ocr_required,
    )
    if (
        previous is not None
        and previous.content_hash == document.content_hash
        and previous.extracted_text_hash == document.extracted_text_hash
        and previous.local_path == document.local_path
    ):
        document = previous
    sources = [document if item.source_id == source_id else item for item in existing_index.sources]
    if previous is None:
        sources.append(document)
    active_changed = previous_active_source_id not in {None, source_id}
    ambiguous_selection = previous_active_source_id is None and len(existing_index.sources) > 1
    source_index = SourceIndex(sources=sources, active_source_id=source_id)
    atomic_write_model(index_file, source_index)
    if source_id not in project.source_ids:
        project.source_ids.append(source_id)
    project.active_source_id = source_id
    project.dependency_hashes[source_id] = digest
    project.dependency_hashes[f"{source_id}:extracted"] = extracted_hash
    project.dependency_hashes["active-source"] = digest
    project.dependency_hashes["active-source-extracted"] = extracted_hash
    store.save_project(project)
    extracted_changed = previous_extracted_hash not in {None, extracted_hash}
    indexed_extraction_changed = previous is not None and previous.extracted_text_hash not in {
        None,
        extracted_hash,
    }
    is_new_selection = previous is None or active_changed or ambiguous_selection
    if is_new_selection or extracted_changed or indexed_extraction_changed or original_was_repaired:
        reason = (
            f"active source selected: {source_id}"
            if is_new_selection
            else f"source integrity changed: {source_id}"
        )
        store.invalidate_from("claims", reason)
    return document


def get_source(store: ProjectStore, source_id: str) -> SourceDocument:
    index = load_model(store.path("sources/source-index.json"), SourceIndex)
    source = next((item for item in index.sources if item.source_id == source_id), None)
    if source is None:
        raise ValueError(f"source is not indexed: {source_id}")
    return source


def get_active_source(store: ProjectStore) -> SourceDocument:
    index = load_model(store.path("sources/source-index.json"), SourceIndex)
    project = store.project()
    selected = index.active_source_id or project.active_source_id
    if (
        index.active_source_id is not None
        and project.active_source_id is not None
        and index.active_source_id != project.active_source_id
    ):
        raise ValueError("project and source index disagree about the active source")
    if selected is None:
        if len(index.sources) != 1:
            raise ValueError("select an active source before generating evidence")
        selected = index.sources[0].source_id
    if selected not in project.source_ids:
        raise ValueError("active source is not declared by the project manifest")
    return get_source(store, selected)


def verify_source_integrity(store: ProjectStore, source: SourceDocument | str) -> SourceDocument:
    document = get_source(store, source) if isinstance(source, str) else source
    original = store.path(document.local_path)
    if not original.is_file() or sha256_file(original) != document.content_hash:
        raise ValueError(f"source {document.source_id} no longer matches its content hash")
    extracted = store.path(f"sources/extracted/{document.source_id}.txt")
    if not extracted.is_file():
        raise ValueError(f"extracted text is missing for source {document.source_id}")
    actual_extracted_hash = sha256_file(extracted)
    if (
        document.extracted_text_hash is not None
        and actual_extracted_hash != document.extracted_text_hash
    ):
        raise ValueError(
            f"extracted text for source {document.source_id} no longer matches its hash"
        )
    project = store.project()
    recorded_source_hash = project.dependency_hashes.get(document.source_id)
    if recorded_source_hash is not None and recorded_source_hash != document.content_hash:
        raise ValueError(f"project source hash is stale for {document.source_id}")
    recorded_extracted_hash = project.dependency_hashes.get(f"{document.source_id}:extracted")
    if recorded_extracted_hash is not None and recorded_extracted_hash != actual_extracted_hash:
        raise ValueError(f"project extracted-source hash is stale for {document.source_id}")
    return document


def resolve_evidence_text(
    store: ProjectStore,
    source_id: str,
    start: int,
    end: int,
    *,
    expected_source_hash: str | None = None,
    expected_extracted_hash: str | None = None,
) -> str:
    document = verify_source_integrity(store, source_id)
    if expected_source_hash is not None and document.content_hash != expected_source_hash:
        raise ValueError("evidence source hash does not match the indexed source")
    if (
        expected_extracted_hash is not None
        and document.extracted_text_hash != expected_extracted_hash
    ):
        raise ValueError("evidence extracted-text hash does not match the indexed source")
    text = store.path(f"sources/extracted/{source_id}.txt").read_text(encoding="utf-8")
    if start < 0 or end > len(text) or start >= end:
        raise ValueError("evidence locator is outside extracted source")
    return text[start:end]
