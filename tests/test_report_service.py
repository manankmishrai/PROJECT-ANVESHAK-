"""Tests for Module I: downloadable PDF/CSV reports and the backend-
enforced applicant-feedback restriction (Phase 6).

Findings are inserted directly via SQL in most tests here, rather than
through validation_engine/forensics_engine, so these tests exercise
report_service's own rendering and filtering logic in isolation with
full control over engine names, severities and officer fields.
"""
import csv
import io
import json

import pymupdf
import pytest

from services.auth_service import PermissionDenied

ADMIN_ACTOR = {"username": "admin", "role": "admin"}
OFFICER_ACTOR = {"username": "officer1", "role": "officer"}


def _applicant_actor(institution_id):
    return {"username": "applicant1", "role": "applicant", "institution_id": institution_id}


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


def _pdf_text(pdf_bytes):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        raw = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    return " ".join(raw.split())


@pytest.fixture()
def wired(temp_db, monkeypatch, tmp_path):
    import services.application_service as app_module
    import services.report_service as report_module
    import services.auth_service as auth_module
    import utils.file_safety as fs_module

    monkeypatch.setattr(app_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(report_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(auth_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(fs_module, "UPLOAD_DIR", tmp_path / "uploads")

    return {"app": app_module, "report": report_module}


def _insert_finding(temp_db, application_id, document_id=None, rule_id="TEST-RULE",
                     engine="rule_engine", severity="high", rung=1, status="open",
                     description="Test finding description", reason="Test reason",
                     extracted_value=None, expected_value=None, recommended_action="Fix it.",
                     officer_decision=None, officer_remarks=None):
    conn = temp_db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO findings
               (application_id, document_id, rule_id, rule_pack_version, engine, severity, rung,
                status, description, reason, extracted_value, expected_value, recommended_action,
                officer_decision, officer_remarks)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (application_id, document_id, rule_id, "0.1.0", engine, severity, rung,
             status, description, reason, extracted_value, expected_value, recommended_action,
             officer_decision, officer_remarks),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------

def test_generate_officer_pdf_report_requires_officer_or_admin(wired):
    with pytest.raises(PermissionDenied):
        wired["report"].generate_officer_pdf_report(_applicant_actor(1), 99999)


def test_generate_findings_csv_requires_officer_or_admin(wired):
    with pytest.raises(PermissionDenied):
        wired["report"].generate_findings_csv(_applicant_actor(1), 99999)


def test_generate_applicant_pdf_report_rejects_unknown_role(wired):
    bad_actor = {"username": "x", "role": "guest"}
    with pytest.raises(PermissionDenied):
        wired["report"].generate_applicant_pdf_report(bad_actor, 1)


# ---------------------------------------------------------------------
# Malformed / missing input handling
# ---------------------------------------------------------------------

def test_generate_officer_pdf_report_unknown_application_raises(wired):
    report = wired["report"]
    with pytest.raises(report.ReportUnavailableError):
        report.generate_officer_pdf_report(ADMIN_ACTOR, 99999)


def test_generate_applicant_pdf_report_unknown_application_raises(wired):
    report = wired["report"]
    with pytest.raises(report.ReportUnavailableError):
        report.generate_applicant_pdf_report(ADMIN_ACTOR, 99999)


def test_generate_officer_pdf_report_with_malformed_application_id_fails_safely(wired):
    report = wired["report"]
    with pytest.raises(report.ReportUnavailableError):
        report.generate_officer_pdf_report(ADMIN_ACTOR, "not-a-real-id")


# ---------------------------------------------------------------------
# Basic generation + empty states
# ---------------------------------------------------------------------

def test_generate_officer_pdf_report_produces_valid_pdf_with_findings(wired, temp_db):
    app_mod, report_mod = wired["app"], wired["report"]
    inst_id = app_mod.get_or_create_institution("Report Institute", "INST-REPORT")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")
    pdf_bytes = _make_pdf_bytes(["Certificate No: REPORT-0001"])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "cert.pdf", pdf_bytes)
    _insert_finding(temp_db, app_id, engine="rule_engine", rule_id="RULE-001",
                     severity="high", rung=1, description="Missing fire NOC.")

    pdf_bytes_out = report_mod.generate_officer_pdf_report(OFFICER_ACTOR, app_id)
    assert pdf_bytes_out.startswith(b"%PDF")

    text = _pdf_text(pdf_bytes_out)
    assert "Missing fire NOC" in text
    assert "SYNTHETIC / MOCK VERIFICATION DATA" in text


def test_officer_pdf_report_with_no_findings_does_not_crash(wired):
    app_mod, report_mod = wired["app"], wired["report"]
    inst_id = app_mod.get_or_create_institution("Empty Institute", "INST-EMPTY")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes_out = report_mod.generate_officer_pdf_report(ADMIN_ACTOR, app_id)
    text = _pdf_text(pdf_bytes_out)
    assert "No findings are currently on record" in text


def test_applicant_pdf_report_with_no_findings_does_not_crash(wired):
    app_mod, report_mod = wired["app"], wired["report"]
    inst_id = app_mod.get_or_create_institution("Empty Institute2", "INST-EMPTY2")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes_out = report_mod.generate_applicant_pdf_report(_applicant_actor(inst_id), app_id)
    assert pdf_bytes_out.startswith(b"%PDF")


# ---------------------------------------------------------------------
# Access restrictions (Section B -- applicant feedback restriction)
# ---------------------------------------------------------------------

def test_generate_applicant_pdf_report_enforces_institution_access(wired):
    app_mod, report_mod = wired["app"], wired["report"]
    inst_a = app_mod.get_or_create_institution("Institute A", "INST-RA")
    inst_b = app_mod.get_or_create_institution("Institute B", "INST-RB")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_a, "EoA", "2025-26", "2025-06-01")

    outsider = _applicant_actor(inst_b)
    with pytest.raises(PermissionDenied):
        report_mod.generate_applicant_pdf_report(outsider, app_id)


def test_applicant_report_excludes_restricted_content(wired, temp_db):
    app_mod, report_mod = wired["app"], wired["report"]
    inst_a = app_mod.get_or_create_institution("Visible Institute", "INST-VIS")
    app_mod.get_or_create_institution("Secret Other Institute", "INST-SEC")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_a, "EoA", "2025-26", "2025-06-01")

    _insert_finding(temp_db, app_id, engine="rule_engine", rule_id="RULE-002",
                     severity="medium", rung=1,
                     description="A routine completeness finding visible to the applicant.")
    _insert_finding(temp_db, app_id, engine="forensics_engine", rule_id="SIG-INVALID",
                     severity="critical", rung=3,
                     description="Signature forensic detail that must stay internal.")
    _insert_finding(temp_db, app_id, engine="rule_engine", rule_id="RULE-009",
                     severity="high", rung=0,
                     description="This file hash also appears on an application from "
                                 "Secret Other Institute.")
    _insert_finding(temp_db, app_id, engine="rule_engine", rule_id="RULE-003",
                     severity="high", rung=1, description="Expired certificate finding.",
                     officer_decision="dismissed",
                     officer_remarks="Internal note not for applicant.")

    applicant_text = _pdf_text(
        report_mod.generate_applicant_pdf_report(_applicant_actor(inst_a), app_id)
    )
    assert "routine completeness finding" in applicant_text
    assert "Signature forensic detail" not in applicant_text
    assert "Secret Other Institute" not in applicant_text
    assert "Expired certificate finding" in applicant_text
    assert "Internal note not for applicant" not in applicant_text

    officer_text = _pdf_text(
        report_mod.generate_officer_pdf_report(OFFICER_ACTOR, app_id)
    )
    assert "routine completeness finding" in officer_text
    assert "Signature forensic detail" in officer_text
    assert "Secret Other Institute" in officer_text
    assert "Internal note not for applicant" in officer_text


# ---------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------

def test_generate_findings_csv_contains_all_findings(wired, temp_db):
    app_mod, report_mod = wired["app"], wired["report"]
    inst_id = app_mod.get_or_create_institution("CSV Institute", "INST-CSV")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")
    _insert_finding(temp_db, app_id, rule_id="RULE-CSV-1", description="First finding")
    _insert_finding(temp_db, app_id, rule_id="RULE-CSV-2", description="Second finding")

    csv_bytes = report_mod.generate_findings_csv(ADMIN_ACTOR, app_id)
    text = csv_bytes.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    assert rows[0][0] == "id"
    data_rows = rows[1:]
    assert len(data_rows) == 2
    descriptions = {row[6] for row in data_rows}  # index 6 == "description" column
    assert "First finding" in descriptions
    assert "Second finding" in descriptions


# ---------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------

def test_report_generation_is_audited(wired, temp_db):
    app_mod, report_mod = wired["app"], wired["report"]
    inst_id = app_mod.get_or_create_institution("Audit Institute", "INST-AUD")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    report_mod.generate_officer_pdf_report(ADMIN_ACTOR, app_id)

    conn = temp_db.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE action = 'REPORT_GENERATED'"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["report_type"] == "officer_pdf"