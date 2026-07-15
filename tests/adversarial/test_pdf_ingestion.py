from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from techshort.domain.hashing import sha256_file
from techshort.domain.storage import ProjectStore, atomic_write_json
from techshort.generation import generate_claims
from techshort.ingestion import ingest_source, verify_source_integrity
from techshort.ingestion.service import MAX_EXTRACTED_OUTPUT_BYTES, MAX_FILE_BYTES


def _store(tmp_path: Path, slug: str) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", slug)
    store.initialize(slug)
    return store


def _write_blank_pdf(path: Path, *, encrypted: bool = False) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("secret")
    with path.open("wb") as handle:
        writer.write(handle)


def _write_text_pdf(path: Path, text: str, *, printed_label: str = "sheet-7") -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.set_page_label(0, 0, prefix=printed_label)
    with path.open("wb") as handle:
        writer.write(handle)


def test_malformed_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "malformed.pdf"
    path.write_bytes(b"%PDF-1.7\nnot a valid object graph")
    with pytest.raises(ValueError, match="malformed PDF"):
        ingest_source(_store(tmp_path, "malformed"), path)


def test_encrypted_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    _write_blank_pdf(path, encrypted=True)
    with pytest.raises(ValueError, match="encrypted PDFs are unsupported"):
        ingest_source(_store(tmp_path, "encrypted"), path)


def test_image_only_or_empty_pdf_reports_ocr_required(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    _write_blank_pdf(path)
    document = ingest_source(_store(tmp_path, "scan"), path)
    assert document.ocr_required
    assert document.appears_incomplete
    assert any("OCR" in warning for warning in document.extraction_warnings)


def test_oversized_input_is_rejected_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "oversized.pdf"
    with path.open("wb") as handle:
        handle.seek(MAX_FILE_BYTES)
        handle.write(b"x")
    with pytest.raises(ValueError, match="25 MiB"):
        ingest_source(_store(tmp_path, "oversized"), path)


def test_text_pdf_preserves_raw_page_and_printed_label_separately(tmp_path: Path) -> None:
    path = tmp_path / "labeled.pdf"
    _write_text_pdf(
        path,
        "Rolling shutter samples rows at different times.",
        printed_label="appendix-A",
    )
    store = _store(tmp_path, "labeled")

    document = ingest_source(store, path)

    assert document.source_type == "pdf"
    assert not document.ocr_required
    extracted_dir = store.path("sources/extracted")
    raw_pages = json.loads(
        (extracted_dir / f"{document.source_id}.raw-pages.json").read_text(encoding="utf-8")
    )
    assert raw_pages["source_id"] == document.source_id
    assert raw_pages["pages"][0]["page_index"] == 0
    assert raw_pages["pages"][0]["printed_page_label"] == "appendix-A"
    assert "Rolling shutter samples rows" in raw_pages["pages"][0]["text"]
    sections = json.loads(
        (extracted_dir / f"{document.source_id}.sections.json").read_text(encoding="utf-8")
    )
    assert sections[0]["page_index"] == 0
    assert sections[0]["printed_page_label"] == "appendix-A"
    normalized = (extracted_dir / f"{document.source_id}.txt").read_text(encoding="utf-8")
    assert "--- Page 1 ---" in normalized
    assert document.section_metadata_hash == sha256_file(
        extracted_dir / f"{document.source_id}.sections.json"
    )
    verify_source_integrity(store, document)


def test_pdf_section_metadata_tampering_blocks_evidence_generation(tmp_path: Path) -> None:
    path = tmp_path / "tampered-label.pdf"
    _write_text_pdf(path, "A row-exposure fact with enough text for deterministic evidence.")
    store = _store(tmp_path, "tampered-label")
    document = ingest_source(store, path)
    sections_path = store.path(f"sources/extracted/{document.source_id}.sections.json")
    sections = json.loads(sections_path.read_text(encoding="utf-8"))
    sections[0]["printed_page_label"] = "fabricated-label"
    atomic_write_json(sections_path, sections)

    with pytest.raises(ValueError, match="section-location metadata.*hash"):
        generate_claims(store, "manual")


def test_pdf_section_rows_must_correspond_to_source_pages_even_if_hash_is_rebound(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bad-page-row.pdf"
    _write_text_pdf(path, "A page-correspondence fact with enough text for evidence.")
    store = _store(tmp_path, "bad-page-row")
    document = ingest_source(store, path)
    sections_path = store.path(f"sources/extracted/{document.source_id}.sections.json")
    sections = json.loads(sections_path.read_text(encoding="utf-8"))
    sections[0]["page_index"] = 7
    atomic_write_json(sections_path, sections)
    rebound_hash = sha256_file(sections_path)
    rebound_document = document.model_copy(update={"section_metadata_hash": rebound_hash})
    project = store.project()
    project.dependency_hashes[f"{document.source_id}:sections"] = rebound_hash
    project.dependency_hashes["active-source-sections"] = rebound_hash
    store.save_project(project)

    with pytest.raises(ValueError, match="does not correspond to source pages"):
        verify_source_integrity(store, rebound_document)


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_text_extraction_output_is_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, suffix: str
) -> None:
    monkeypatch.setattr("techshort.ingestion.service.MAX_EXTRACTED_OUTPUT_BYTES", 64)
    path = tmp_path / f"large{suffix}"
    path.write_text("# Heading\n" + "x" * 100, encoding="utf-8")

    with pytest.raises(ValueError, match="extraction-output limit"):
        ingest_source(_store(tmp_path, f"bounded-{suffix[1:]}"), path)


def test_pdf_extraction_output_is_bounded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("techshort.ingestion.service.MAX_EXTRACTED_OUTPUT_BYTES", 64)
    path = tmp_path / "large-extraction.pdf"
    _write_text_pdf(path, "x" * 100)

    with pytest.raises(ValueError, match="PDF extracted text.*extraction-output limit"):
        ingest_source(_store(tmp_path, "bounded-pdf"), path)


def test_default_extraction_output_bound_is_finite() -> None:
    assert 0 < MAX_EXTRACTED_OUTPUT_BYTES <= 64 * 1024 * 1024
