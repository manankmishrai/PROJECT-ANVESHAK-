"""Phase 6, Section E: large-file handling. The configured
MAX_PDF_PAGES cap must be honoured and must fail safely (a clear
ValueError, before any extraction is attempted) rather than processing
an unbounded number of pages."""
import pymupdf
import pytest

from services import pdf_service

ADMIN_ACTOR = {"username": "admin", "role": "admin"}


def _make_multi_page_pdf(num_pages):
    doc = pymupdf.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((50, 50), f"Page {i + 1}", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def test_extract_document_text_rejects_pdf_over_page_limit(monkeypatch):
    monkeypatch.setattr(pdf_service, "MAX_PDF_PAGES", 2)
    pdf_bytes = _make_multi_page_pdf(3)

    with pytest.raises(ValueError, match=r"(?i)page"):
        pdf_service.extract_document_text(pdf_bytes)


def test_extract_document_text_accepts_pdf_within_page_limit(monkeypatch):
    monkeypatch.setattr(pdf_service, "MAX_PDF_PAGES", 5)
    pdf_bytes = _make_multi_page_pdf(3)

    result = pdf_service.extract_document_text(pdf_bytes)
    assert result["page_count"] == 3


@pytest.fixture()
def wired_qr(temp_db, monkeypatch, tmp_path):
    import services.application_service as app_module
    import services.qr_service as qr_module
    import services.auth_service as auth_module
    import utils.file_safety as fs_module

    monkeypatch.setattr(app_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(qr_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(auth_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(fs_module, "UPLOAD_DIR", tmp_path / "uploads")
    return {"app": app_module, "qr": qr_module}


def test_qr_verification_respects_page_limit_without_crashing(wired_qr, monkeypatch):
    app_mod, qr_mod = wired_qr["app"], wired_qr["qr"]
    monkeypatch.setattr(qr_mod, "MAX_PDF_PAGES", 2)

    inst_id = app_mod.get_or_create_institution("QR Institute", "INST-QR")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")
    pdf_bytes = _make_multi_page_pdf(5)
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "multi.pdf", pdf_bytes)

    result = qr_mod.run_qr_verification(ADMIN_ACTOR, app_id)
    assert isinstance(result, list)