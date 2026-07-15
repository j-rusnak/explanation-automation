from __future__ import annotations

import json
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
MAX_EXTRACTED_OUTPUT_BYTES = 32 * 1024 * 1024
_SECTION_BASE_KEYS = {"index", "heading", "start", "end"}
_PDF_SECTION_KEYS = _SECTION_BASE_KEYS | {"page_index", "printed_page_label"}


def _output_limit_label() -> str:
    if MAX_EXTRACTED_OUTPUT_BYTES >= 1024 * 1024:
        return f"{MAX_EXTRACTED_OUTPUT_BYTES // (1024 * 1024)} MiB"
    return f"{MAX_EXTRACTED_OUTPUT_BYTES} bytes"


def _normalize(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _enforce_output_bound(payload: str, *, description: str) -> None:
    if len(payload.encode("utf-8")) > MAX_EXTRACTED_OUTPUT_BYTES:
        raise ValueError(
            f"{description} exceeds the {_output_limit_label()} extraction-output limit"
        )


def _validate_section_locations(
    value: object,
    extracted_text: str,
    *,
    source_type: str,
    expected_count: int,
) -> list[dict[str, object]]:
    """Validate section offsets against the exact normalized extraction.

    PDF page numbers are derived during ingestion and must correspond one-to-one
    with their zero-based page rows. Printed labels remain descriptive metadata,
    but are protected by the bound section-metadata hash.
    """

    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("source section-location metadata must be a list of objects")
    if len(value) != expected_count:
        raise ValueError("source section-location metadata count does not match the source")

    rows: list[dict[str, object]] = []
    previous_end = 0
    expected_keys = _PDF_SECTION_KEYS if source_type == "pdf" else _SECTION_BASE_KEYS
    for position, untyped_row in enumerate(value):
        row = dict(untyped_row)
        if set(row) != expected_keys:
            raise ValueError("source section-location metadata has unexpected or missing fields")
        index = row.get("index")
        start = row.get("start")
        end = row.get("end")
        heading = row.get("heading")
        if type(index) is not int or index != position:
            raise ValueError("source section-location metadata indices are not contiguous")
        if type(start) is not int or type(end) is not int:
            raise ValueError("source section-location metadata offsets must be integers")
        if not isinstance(heading, str) or not heading or "\n" in heading or "\r" in heading:
            raise ValueError("source section-location metadata heading is invalid")
        marker = ("" if position == 0 else "\n\n") + f"--- {heading} ---\n"
        expected_start = previous_end + len(marker)
        if start != expected_start or extracted_text[previous_end:start] != marker:
            raise ValueError("source section-location metadata does not match extracted text")
        if end < start or end > len(extracted_text):
            raise ValueError("source section-location metadata offsets are outside extracted text")

        if source_type == "pdf":
            page_index = row.get("page_index")
            printed_label = row.get("printed_page_label")
            if type(page_index) is not int or page_index != position:
                raise ValueError("PDF section metadata does not correspond to source pages")
            if heading != f"Page {position + 1}":
                raise ValueError("PDF section heading does not correspond to its source page")
            if printed_label is not None and (
                not isinstance(printed_label, str)
                or not printed_label
                or len(printed_label) > 256
                or any(character in printed_label for character in ("\x00", "\n", "\r"))
            ):
                raise ValueError("PDF printed page label is invalid")
        rows.append(row)
        previous_end = end

    if previous_end != len(extracted_text):
        raise ValueError("source section-location metadata does not cover extracted text")
    return rows


def _read_section_locations(
    path: Path,
    extracted_text: str,
    *,
    source_type: str,
    expected_count: int,
) -> list[dict[str, object]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("source section-location metadata is missing or invalid") from exc
    return _validate_section_locations(
        value,
        extracted_text,
        source_type=source_type,
        expected_count=expected_count,
    )


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
    raw_pdf_pages: list[dict[str, str | int | None]] = []
    metadata: dict[str, str] = {}
    if suffix == ".pdf":
        try:
            reader = PdfReader(destination, strict=True)
            if reader.is_encrypted:
                raise ValueError("encrypted PDFs are unsupported")
            if len(reader.pages) > MAX_PAGES:
                raise ValueError("PDF exceeds the 250-page limit")
            metadata = {str(k).lstrip("/"): str(v) for k, v in (reader.metadata or {}).items() if v}
            page_labels = reader.page_labels
            extracted_byte_count = 0
            for index, page in enumerate(reader.pages):
                raw_text = page.extract_text() or ""
                extracted_byte_count += len(raw_text.encode("utf-8"))
                if extracted_byte_count > MAX_EXTRACTED_OUTPUT_BYTES:
                    raise ValueError(
                        "PDF extracted text exceeds the "
                        f"{_output_limit_label()} extraction-output limit"
                    )
                printed_label = page_labels[index] if index < len(page_labels) else None
                raw_pdf_pages.append(
                    {
                        "page_index": index,
                        "printed_page_label": printed_label,
                        "text": raw_text,
                    }
                )
                text = _normalize(raw_text)
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
        _enforce_output_bound(raw, description="Source text")
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
    section_rows: list[dict[str, str | int | None]] = []
    for index, (heading, text) in enumerate(sections):
        marker = f"\n\n--- {heading} ---\n"
        start = offset + len(marker)
        indexed_parts.append(marker + text)
        offset += len(marker) + len(text)
        row: dict[str, str | int | None] = {
            "index": index,
            "heading": heading,
            "start": start,
            "end": offset,
        }
        if raw_pdf_pages:
            row["page_index"] = raw_pdf_pages[index]["page_index"]
            row["printed_page_label"] = raw_pdf_pages[index]["printed_page_label"]
        section_rows.append(row)
    normalized = "".join(indexed_parts).lstrip("\n")
    _enforce_output_bound(normalized, description="Normalized extracted text")
    # Recompute offsets after stripping the first two newlines.
    shift = 2 if indexed_parts else 0
    for row in section_rows:
        row_start = row["start"]
        row_end = row["end"]
        if not isinstance(row_start, int) or not isinstance(row_end, int):
            raise AssertionError("section offsets must be integers")
        row["start"] = row_start - shift
        row["end"] = row_end - shift
    extracted_path = store.path(f"sources/extracted/{source_id}.txt")
    previous_extracted_hash = sha256_file(extracted_path) if extracted_path.exists() else None
    extracted_hash = sha256_bytes(normalized.encode("utf-8"))
    raw_pages_payload: str | None = None
    if raw_pdf_pages:
        raw_pages_payload = (
            json.dumps(
                {"source_id": source_id, "pages": raw_pdf_pages},
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        _enforce_output_bound(raw_pages_payload, description="Raw PDF page extraction")
    atomic_write_text(extracted_path, normalized)
    if raw_pages_payload is not None:
        atomic_write_text(
            store.path(f"sources/extracted/{source_id}.raw-pages.json"), raw_pages_payload
        )
    index_path = store.path(f"sources/extracted/{source_id}.sections.json")
    previous_section_metadata_hash = sha256_file(index_path) if index_path.exists() else None
    _validate_section_locations(
        section_rows,
        normalized,
        source_type="pdf"
        if suffix == ".pdf"
        else "markdown"
        if suffix in {".md", ".markdown"}
        else "text",
        expected_count=len(sections),
    )
    atomic_write_json(index_path, section_rows)
    section_metadata_hash = sha256_file(index_path)
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
        section_metadata_hash=section_metadata_hash,
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
        and previous.section_metadata_hash == document.section_metadata_hash
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
    project.dependency_hashes[f"{source_id}:sections"] = section_metadata_hash
    project.dependency_hashes["active-source"] = digest
    project.dependency_hashes["active-source-extracted"] = extracted_hash
    project.dependency_hashes["active-source-sections"] = section_metadata_hash
    store.save_project(project)
    extracted_changed = previous_extracted_hash not in {None, extracted_hash}
    indexed_extraction_changed = previous is not None and previous.extracted_text_hash not in {
        None,
        extracted_hash,
    }
    section_metadata_changed = previous_section_metadata_hash not in {
        None,
        section_metadata_hash,
    }
    is_new_selection = previous is None or active_changed or ambiguous_selection
    if (
        is_new_selection
        or extracted_changed
        or indexed_extraction_changed
        or section_metadata_changed
        or original_was_repaired
    ):
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
    sections = store.path(f"sources/extracted/{document.source_id}.sections.json")
    if not sections.is_file():
        raise ValueError(f"section-location metadata is missing for source {document.source_id}")
    actual_section_metadata_hash = sha256_file(sections)
    if document.section_metadata_hash is None:
        raise ValueError(
            f"source {document.source_id} lacks a bound section-metadata hash; reingest it"
        )
    if actual_section_metadata_hash != document.section_metadata_hash:
        raise ValueError(
            f"section-location metadata for source {document.source_id} no longer matches its hash"
        )
    recorded_section_metadata_hash = project.dependency_hashes.get(
        f"{document.source_id}:sections"
    )
    if recorded_section_metadata_hash is None:
        raise ValueError(
            f"project lacks a bound section-metadata hash for {document.source_id}; reingest it"
        )
    if recorded_section_metadata_hash != actual_section_metadata_hash:
        raise ValueError(f"project section-metadata hash is stale for {document.source_id}")
    extracted_text = extracted.read_text(encoding="utf-8", errors="strict")
    _read_section_locations(
        sections,
        extracted_text,
        source_type=document.source_type,
        expected_count=document.page_or_section_count,
    )
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
