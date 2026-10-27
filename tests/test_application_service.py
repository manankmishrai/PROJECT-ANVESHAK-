"""Tests for Module B: application intake, document upload, extraction
persistence, duplicate fingerprint detection and database relationships."""
import pymupdf
import pytest

from services.auth_service import PermissionDenied
from utils.file_safety import UploadValidationError


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


ADMIN_ACTOR = {"username": "admin", "role": "admin", "institution_id": None}
APPLICANT_ACTOR = {"username": "applicant1", "role": "applicant", "institution_id": None}


@pytest.fixture()
def wired(temp_db, monkeypatch, tmp_path):
    """Wires application_service onto the isolated temp_db and redirects
    uploaded-file storage to a throwaway temp directory."""
    import services.application_service as app_module
    import services.auth_service as auth_module
    import utils.file_safety as fs_module

    monkeypatch.setattr(app_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(auth_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(fs_module, "UPLOAD_DIR", tmp_path / "uploads")

    return app_module


def test_create_application_and_default_checklist(wired):
    inst_id = wired.get_or_create_institution("Test Institute", "INST-T01")
    app_id = wired.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    detail = wired.get_application_detail(ADMIN_ACTOR, app_id)
    assert detail["application"]["institution_id"] == inst_id
    doc_types = {c["doc_type"] for c in detail["checklist"]}
    assert "affiliation_certificate" in doc_types
    assert "fire_noc" in doc_types


def test_applicant_cannot_create_for_other_institution(wired):
    inst_id = wired.get_or_create_institution("Test Institute", "INST-T01")
    other_actor = dict(APPLICANT_ACTOR, institution_id=999)
    with pytest.raises(PermissionDenied):
        wired.create_application(other_actor, inst_id, "EoA", "2025-26", "2025-06-01")


def test_upload_valid_pdf_extracts_text_and_fields(wired):
    inst_id = wired.get_or_create_institution("Test Institute", "INST-T01")
    app_id = wired.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes = _make_pdf_bytes([
        "Institution Name: Test Institute",
        "Certificate No: CERT-0001",
        "Valid Until: 31-12-2030",
    ])
    result = wired.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "cert.pdf", pdf_bytes)

    assert result["extraction_status"] == "native"
    field_names = {f["field_name"] for f in result["fields_found"]}
    assert "institution_name" in field_names
    assert "certificate_number" in field_names
    assert result["duplicates"] == []


def test_upload_marks_checklist_item_satisfied(wired):
    inst_id = wired.get_or_create_institution("Test Institute", "INST-T01")
    app_id = wired.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")
    pdf_bytes = _make_pdf_bytes(["Certificate No: CERT-0001"])

    wired.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "cert.pdf", pdf_bytes)

    detail = wired.get_application_detail(ADMIN_ACTOR, app_id)
    item = next(c for c in detail["checklist"] if c["doc_type"] == "affiliation_certificate")
    assert item["satisfied"] == 1


def test_upload_rejects_invalid_file(wired):
    inst_id = wired.get_or_create_institution("Test Institute", "INST-T01")
    app_id = wired.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    with pytest.raises(UploadValidationError):
        wired.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "not_a_pdf.txt", b"hello world")


def test_duplicate_fingerprint_is_detected(wired):
    inst_id = wired.get_or_create_institution("Test Institute", "INST-T01")
    app_id = wired.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")
    pdf_bytes = _make_pdf_bytes(["Certificate No: DUPLICATE-0001"])

    wired.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "first.pdf", pdf_bytes)
    second_result = wired.add_document(ADMIN_ACTOR, app_id, "fire_noc", "second_copy.pdf", pdf_bytes)

    assert len(second_result["duplicates"]) == 1
    expected_code = wired.get_application_detail(ADMIN_ACTOR, app_id)["application"]["application_code"]
    assert second_result["duplicates"][0]["application_code"] == expected_code


def test_extracted_text_persists_and_reloads(wired):
    inst_id = wired.get_or_create_institution("Test Institute", "INST-T01")
    app_id = wired.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")
    pdf_bytes = _make_pdf_bytes(["Institution Name: Reload Test Institute"])

    wired.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "cert.pdf", pdf_bytes)

    # Simulate "revisiting after restart": fetch detail fresh, independent
    # of any in-memory state from the add_document() call above.
    detail = wired.get_application_detail(ADMIN_ACTOR, app_id)
    doc = detail["documents"][0]
    assert doc["pages_text"] is not None
    assert "Reload Test Institute" in doc["pages_text"][0]


def test_document_relationships_cascade_correctly(wired):
    inst_id = wired.get_or_create_institution("Test Institute", "INST-T01")
    app_id = wired.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")
    pdf_bytes = _make_pdf_bytes(["Certificate No: REL-0001"])

    wired.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "cert.pdf", pdf_bytes)
    detail = wired.get_application_detail(ADMIN_ACTOR, app_id)

    assert detail["application"]["id"] == app_id
    assert len(detail["documents"]) == 1
    assert detail["documents"][0]["application_id"] == app_id
    assert len(detail["documents"][0]["fields"]) >= 1
    assert detail["documents"][0]["fields"][0]["document_id"] == detail["documents"][0]["id"]


def test_applicant_cannot_view_other_institutions_application(wired):
    inst_a = wired.get_or_create_institution("Institute A", "INST-A01")
    inst_b = wired.get_or_create_institution("Institute B", "INST-B01")
    app_id = wired.create_application(ADMIN_ACTOR, inst_a, "EoA", "2025-26", "2025-06-01")

    outsider = dict(APPLICANT_ACTOR, institution_id=inst_b)
    with pytest.raises(PermissionDenied):
        wired.get_application_detail(outsider, app_id)