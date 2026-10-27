"""Tests for Module C: SHA-256 fingerprinting and PDF text extraction."""
import pymupdf
import pytest

from services.pdf_service import compute_sha256, extract_document_text, get_page_count


def _make_pdf_bytes(lines):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 50
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 20
    data = doc.tobytes()
    doc.close()
    return data


def _make_blank_pdf_bytes():
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def test_compute_sha256_is_deterministic():
    data = _make_pdf_bytes(["Hello"])
    assert compute_sha256(data) == compute_sha256(data)


def test_compute_sha256_differs_for_different_content():
    a = _make_pdf_bytes(["Hello"])
    b = _make_pdf_bytes(["Goodbye"])
    assert compute_sha256(a) != compute_sha256(b)


def test_get_page_count():
    data = _make_pdf_bytes(["One page only"])
    assert get_page_count(data) == 1


def test_extract_native_text():
    data = _make_pdf_bytes(["Institution Name: Test Institute", "Certificate No: ABC-123"])
    result = extract_document_text(data)
    assert result["extraction_status"] == "native"
    assert result["is_native_text"] is True
    assert result["ocr_used"] is False
    assert "Test Institute" in result["pages_text"][0]


def test_extract_blank_pdf_does_not_crash():
    data = _make_blank_pdf_bytes()
    result = extract_document_text(data)
    # No native text; OCR may or may not be installed in this environment --
    # either way this must never raise or fabricate text.
    assert result["extraction_status"] in ("ocr", "ocr_unavailable", "ocr_failed", "empty")
    assert isinstance(result["pages_text"], list)


def test_extract_invalid_pdf_raises_value_error():
    with pytest.raises(ValueError):
        extract_document_text(b"this is not a pdf at all")