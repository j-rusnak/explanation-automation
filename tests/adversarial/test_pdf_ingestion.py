from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from techshort.domain.storage import ProjectStore
from techshort.ingestion import ingest_source
from techshort.ingestion.service import MAX_FILE_BYTES


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
