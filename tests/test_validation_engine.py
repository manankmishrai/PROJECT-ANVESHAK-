"""Tests for Module D: the deterministic validation rules engine.

Covers: a clean application passing applicable checks, each defective
scenario producing the expected finding, deterministic/reproducible
reruns, and permission enforcement.
"""
import pymupdf
import pytest

from services.auth_service import PermissionDenied

REAL_RULE_PACK_PATH = "rules/eoa_illustrative_v1.yaml"

ADMIN_ACTOR = {"username": "admin", "role": "admin"}
APPLICANT_ACTOR = {"username": "applicant1", "role": "applicant", "institution_id": None}


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


@pytest.fixture()
def wired(temp_db, monkeypatch, tmp_path):
    import services.application_service as app_module
    import services.validation_engine as ve_module
    import services.rule_pack_loader as loader_module
    import utils.file_safety as fs_module

    monkeypatch.setattr(app_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(ve_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(loader_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(fs_module, "UPLOAD_DIR", tmp_path / "uploads")

    return {"app": app_module, "ve": ve_module}


def _by_rule(findings, rule_id):
    return [f for f in findings if f["rule_id"] == rule_id]


def test_clean_application_has_no_findings_besides_signature_notice(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Clean Institute", "INST-CLEAN")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    common = [
        "Institution Name: Clean Institute",
        "Institution ID: INST-CLEAN",
        "Issued By: Test Issuer",
        "Date of Issue: 01-01-2023",
        "Valid Until: 31-12-2030",
    ]
    for doc_type, cert_no in [
        ("affiliation_certificate", "AFF-0001"),
        ("fire_noc", "NOC-0001"),
        ("e_stamp", "EST-0001"),
    ]:
        pdf_bytes = _make_pdf_bytes(common + [f"Certificate No: {cert_no}"])
        app_mod.add_document(ADMIN_ACTOR, app_id, doc_type, f"{doc_type}.pdf", pdf_bytes)

    finding_ids = ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)
    assert len(finding_ids) == len(findings)

    non_signature_findings = [f for f in findings if f["rule_id"] != "RULE-010"]
    assert non_signature_findings == []

    # RULE-010 fires for every applicable document -- it is informational
    # only ("not yet verified"), never "missing" or "invalid".
    signature_findings = _by_rule(findings, "RULE-010")
    assert len(signature_findings) == 3
    for f in signature_findings:
        assert f["severity"] == "low"
        assert "not yet" in f["reason"].lower()


def test_missing_required_document_is_flagged(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Partial Institute", "INST-PARTIAL")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes = _make_pdf_bytes(["Institution Name: Partial Institute", "Certificate No: AFF-0002"])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "aff.pdf", pdf_bytes)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)

    missing_doc_findings = _by_rule(findings, "RULE-001")
    flagged_types = {f["expected_value"] for f in missing_doc_findings}
    assert "fire_noc" in flagged_types
    assert "e_stamp" in flagged_types


def test_missing_required_field_is_flagged(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Vague Institute", "INST-VAGUE")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes = _make_pdf_bytes(["This document has no recognisable labelled fields at all."])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "vague.pdf", pdf_bytes)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)

    missing_field_findings = _by_rule(findings, "RULE-002")
    flagged_fields = {f["expected_value"] for f in missing_field_findings}
    assert "institution_name" in flagged_fields
    assert "certificate_number" in flagged_fields


def test_expired_certificate_is_flagged(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Expired Institute", "INST-EXP")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes = _make_pdf_bytes([
        "Institution Name: Expired Institute",
        "Certificate No: AFF-0003",
        "Date of Issue: 01-01-2015",
        "Valid Until: 01-01-2020",
    ])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "expired.pdf", pdf_bytes)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)

    expired_findings = _by_rule(findings, "RULE-003")
    assert len(expired_findings) == 1
    assert expired_findings[0]["severity"] == "high"


def test_invalid_date_range_is_flagged(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Backwards Institute", "INST-BACK")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    # Expiry (01-01-2030) is before issue (01-06-2030), but still in the
    # future relative to "today" so RULE-003 (expired) does not also fire,
    # keeping this test isolated to RULE-004.
    pdf_bytes = _make_pdf_bytes([
        "Institution Name: Backwards Institute",
        "Certificate No: AFF-0004",
        "Date of Issue: 01-06-2030",
        "Valid Until: 01-01-2030",
    ])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "backwards.pdf", pdf_bytes)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)

    range_findings = _by_rule(findings, "RULE-004")
    assert len(range_findings) == 1
    expired_findings = _by_rule(findings, "RULE-003")
    assert expired_findings == []


def test_institution_name_mismatch_is_flagged(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Alpha Institute", "INST-ALPHA")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf1 = _make_pdf_bytes(["Institution Name: Alpha Institute of Technology", "Certificate No: AFF-0005"])
    pdf2 = _make_pdf_bytes(["Institution Name: Zebra College of Arts", "Certificate No: NOC-0005"])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "aff.pdf", pdf1)
    app_mod.add_document(ADMIN_ACTOR, app_id, "fire_noc", "noc.pdf", pdf2)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)

    mismatch_findings = _by_rule(findings, "RULE-005")
    assert len(mismatch_findings) == 1
    assert "Zebra" in mismatch_findings[0]["extracted_value"]


def test_institution_id_mismatch_is_flagged(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("ID Institute", "INST-IDTEST")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf1 = _make_pdf_bytes(["Institution ID: INST-001", "Certificate No: AFF-0006"])
    pdf2 = _make_pdf_bytes(["Institution ID: INST-999", "Certificate No: NOC-0006"])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "aff.pdf", pdf1)
    app_mod.add_document(ADMIN_ACTOR, app_id, "fire_noc", "noc.pdf", pdf2)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)

    mismatch_findings = _by_rule(findings, "RULE-006")
    assert len(mismatch_findings) == 1
    assert mismatch_findings[0]["extracted_value"] == "INST-999"


def test_duplicate_certificate_number_across_applications_is_flagged(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_a = app_mod.get_or_create_institution("Institute A", "INST-A")
    inst_b = app_mod.get_or_create_institution("Institute B", "INST-B")
    app_a = app_mod.create_application(ADMIN_ACTOR, inst_a, "EoA", "2025-26", "2025-06-01")
    app_b = app_mod.create_application(ADMIN_ACTOR, inst_b, "EoA", "2025-26", "2025-06-02")

    pdf_a = _make_pdf_bytes(["Institution Name: Institute A", "Certificate No: DUP-999"])
    pdf_b = _make_pdf_bytes(["Institution Name: Institute B", "Certificate No: DUP-999"])
    app_mod.add_document(ADMIN_ACTOR, app_a, "affiliation_certificate", "a.pdf", pdf_a)
    app_mod.add_document(ADMIN_ACTOR, app_b, "affiliation_certificate", "b.pdf", pdf_b)

    ve_mod.run_validation(ADMIN_ACTOR, app_b, REAL_RULE_PACK_PATH)
    findings_b = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_b)

    dup_findings = _by_rule(findings_b, "RULE-007")
    assert len(dup_findings) == 1
    assert "DUP-999" == dup_findings[0]["extracted_value"]


def test_conflicting_field_values_within_document_is_flagged(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Conflicted Institute", "INST-CONF")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes = _make_pdf_bytes([
        "Institution Name: Conflicted Institute",
        "Certificate No: AAA-111",
        "Some unrelated line of text",
        "Certificate No: BBB-222",
    ])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "conflict.pdf", pdf_bytes)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)

    conflict_findings = _by_rule(findings, "RULE-008")
    assert len(conflict_findings) == 1
    assert "AAA-111" in conflict_findings[0]["extracted_value"]
    assert "BBB-222" in conflict_findings[0]["extracted_value"]


def test_duplicate_uploaded_file_is_flagged(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Repeat Institute", "INST-REPEAT")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes = _make_pdf_bytes(["Institution Name: Repeat Institute", "Certificate No: REP-0001"])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "first.pdf", pdf_bytes)
    app_mod.add_document(ADMIN_ACTOR, app_id, "fire_noc", "second_copy.pdf", pdf_bytes)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)

    dup_file_findings = _by_rule(findings, "RULE-009")
    assert len(dup_file_findings) == 2  # one finding per document, each pointing at the other


def test_validation_is_deterministic_and_rerun_safe(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Stable Institute", "INST-STABLE")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes = _make_pdf_bytes(["Certificate No: STABLE-0001"])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "stable.pdf", pdf_bytes)

    first_ids = ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    second_ids = ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)

    assert len(first_ids) == len(second_ids)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)
    assert len(findings) == len(second_ids)  # no duplicate accumulation


def test_rule_pack_version_is_recorded_on_findings(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Versioned Institute", "INST-VER")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")
    pdf_bytes = _make_pdf_bytes(["Certificate No: VER-0001"])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "ver.pdf", pdf_bytes)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)

    assert all(f["rule_pack_version"] == "0.1.0" for f in findings)


def test_list_findings_filters_by_severity(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Filter Institute", "INST-FILTER")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")
    pdf_bytes = _make_pdf_bytes(["Certificate No: FILTER-0001"])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "filter.pdf", pdf_bytes)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)

    high_only = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id, severity="high")
    assert all(f["severity"] == "high" for f in high_only)
    low_only = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id, severity="low")
    assert all(f["severity"] == "low" for f in low_only)


def test_run_validation_requires_officer_or_admin(wired):
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Guarded Institute", "INST-GUARD")
    applicant_actor = dict(APPLICANT_ACTOR, institution_id=inst_id)
    app_id = app_mod.create_application(applicant_actor, inst_id, "EoA", "2025-26", "2025-06-01")

    with pytest.raises(PermissionDenied):
        ve_mod.run_validation(applicant_actor, app_id, REAL_RULE_PACK_PATH)


def test_list_findings_requires_officer_or_admin(wired):
    ve_mod = wired["ve"]
    with pytest.raises(PermissionDenied):
        ve_mod.list_findings(APPLICANT_ACTOR)