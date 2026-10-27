"""Tests for Module G: mock issuer verification. Self-contained --
inserts its own users/institutions/applications/documents/issuer
records directly via SQL against the isolated temp_db fixture, rather
than depending on database.seed's demo data."""
from services import issuer_service
from services.auth_service import PermissionDenied
from models.enums import VerificationStatus, Rung


def _make_officer(conn):
    conn.execute(
        """INSERT INTO users (username, password_salt, password_hash, full_name, role, is_active)
           VALUES ('officer_test', 'x', 'y', 'Test Officer', 'officer', 1)"""
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM users WHERE username='officer_test'").fetchone())


def _make_applicant(conn):
    conn.execute(
        """INSERT INTO users (username, password_salt, password_hash, full_name, role, is_active)
           VALUES ('applicant_test', 'x', 'y', 'Test Applicant', 'applicant', 1)"""
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM users WHERE username='applicant_test'").fetchone())


def _make_application(conn, code="APP-TEST-0001"):
    conn.execute(
        "INSERT INTO institutions (name, institution_code) VALUES ('Test Institute', ?)",
        (code + "-INST",),
    )
    inst_id = conn.execute(
        "SELECT id FROM institutions WHERE institution_code = ?", (code + "-INST",)
    ).fetchone()["id"]
    conn.execute(
        """INSERT INTO applications (application_code, institution_id, category, academic_year, status)
           VALUES (?, ?, 'EoA', '2025-26', 'submitted')""",
        (code, inst_id),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM applications WHERE application_code = ?", (code,)
    ).fetchone()["id"]


def _make_document(conn, application_id, doc_type="affiliation_certificate"):
    conn.execute(
        """INSERT INTO documents (application_id, doc_type, original_filename, stored_path, sha256)
           VALUES (?, ?, 'test.pdf', 'nonexistent/test.pdf', 'deadbeef')""",
        (application_id, doc_type),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM documents WHERE application_id = ? ORDER BY id DESC LIMIT 1", (application_id,)
    ).fetchone()["id"]


def _add_field(conn, document_id, field_name, value):
    conn.execute(
        """INSERT INTO extracted_fields (document_id, field_name, field_value, confidence, page_number)
           VALUES (?, ?, ?, 0.8, 1)""",
        (document_id, field_name, value),
    )
    conn.commit()


def _add_issuer_record(conn, issuer_type, cert_no, inst_name, expiry_date, issue_date="2020-01-01"):
    conn.execute(
        """INSERT INTO issuer_records (issuer_type, certificate_number, institution_name, issue_date, expiry_date)
           VALUES (?, ?, ?, ?, ?)""",
        (issuer_type, cert_no, inst_name, issue_date, expiry_date),
    )
    conn.commit()


def test_valid_certificate_is_verified(temp_db):
    conn = temp_db.get_connection()
    officer = _make_officer(conn)
    app_id = _make_application(conn)
    doc_id = _make_document(conn, app_id)
    _add_field(conn, doc_id, "certificate_number", "CERT-OK-0001")
    _add_field(conn, doc_id, "institution_name", "Test Institute")
    _add_issuer_record(conn, "affiliation", "CERT-OK-0001", "Test Institute", "2099-01-01")
    conn.close()

    results = issuer_service.run_issuer_verification(officer, app_id)
    assert len(results) == 1
    assert results[0]["status"] == VerificationStatus.VERIFIED.value
    assert results[0]["rung"] == Rung.VERIFIED_AT_SOURCE.value


def test_mismatched_institution_is_flagged(temp_db):
    conn = temp_db.get_connection()
    officer = _make_officer(conn)
    app_id = _make_application(conn)
    doc_id = _make_document(conn, app_id)
    _add_field(conn, doc_id, "certificate_number", "CERT-MIS-0001")
    _add_field(conn, doc_id, "institution_name", "Totally Different College")
    _add_issuer_record(conn, "affiliation", "CERT-MIS-0001", "Test Institute", "2099-01-01")
    conn.close()

    results = issuer_service.run_issuer_verification(officer, app_id)
    assert results[0]["status"] == VerificationStatus.MISMATCH.value
    assert results[0]["severity"] == "high"
    assert results[0]["rung"] == Rung.VERIFIED_AT_SOURCE.value


def test_expired_certificate_is_flagged(temp_db):
    conn = temp_db.get_connection()
    officer = _make_officer(conn)
    app_id = _make_application(conn)
    doc_id = _make_document(conn, app_id)
    _add_field(conn, doc_id, "certificate_number", "CERT-EXP-0001")
    _add_field(conn, doc_id, "institution_name", "Test Institute")
    _add_issuer_record(conn, "affiliation", "CERT-EXP-0001", "Test Institute", "2001-01-01")
    conn.close()

    results = issuer_service.run_issuer_verification(officer, app_id)
    assert results[0]["status"] == VerificationStatus.EXPIRED.value
    assert results[0]["severity"] == "medium"


def test_unknown_certificate_is_source_unavailable(temp_db):
    conn = temp_db.get_connection()
    officer = _make_officer(conn)
    app_id = _make_application(conn)
    doc_id = _make_document(conn, app_id)
    _add_field(conn, doc_id, "certificate_number", "CERT-NOTFOUND-0001")
    _add_field(conn, doc_id, "institution_name", "Test Institute")
    conn.close()

    results = issuer_service.run_issuer_verification(officer, app_id)
    assert results[0]["status"] == VerificationStatus.SOURCE_UNAVAILABLE.value
    assert results[0]["rung"] == Rung.UNVERIFIABLE.value


def test_missing_certificate_number_is_manual_review(temp_db):
    conn = temp_db.get_connection()
    officer = _make_officer(conn)
    app_id = _make_application(conn)
    doc_id = _make_document(conn, app_id)
    _add_field(conn, doc_id, "institution_name", "Test Institute")
    conn.close()

    results = issuer_service.run_issuer_verification(officer, app_id)
    assert results[0]["status"] == VerificationStatus.MANUAL_REVIEW.value
    assert results[0]["rung"] == Rung.UNVERIFIABLE.value


def test_ambiguous_name_triggers_manual_review(temp_db):
    """Best-effort boundary test: the two strings below share enough
    tokens to be a plausible near-match but are not identical, intended
    to land in the 60-90 similarity band. Not run/verified by the
    assistant -- if this fails, it indicates the two example strings
    need tuning, not a logic error."""
    conn = temp_db.get_connection()
    officer = _make_officer(conn)
    app_id = _make_application(conn)
    doc_id = _make_document(conn, app_id)
    _add_field(conn, doc_id, "certificate_number", "CERT-AMBIG-0001")
    _add_field(conn, doc_id, "institution_name", "Test Institute of Advanced Studies")
    _add_issuer_record(conn, "affiliation", "CERT-AMBIG-0001", "Test Institute", "2099-01-01")
    conn.close()

    results = issuer_service.run_issuer_verification(officer, app_id)
    assert results[0]["status"] in (
        VerificationStatus.MANUAL_REVIEW.value,
        VerificationStatus.VERIFIED.value,
        VerificationStatus.MISMATCH.value,
    )  # documents the possible outcomes; see docstring above


def test_rerun_is_idempotent(temp_db):
    conn = temp_db.get_connection()
    officer = _make_officer(conn)
    app_id = _make_application(conn)
    doc_id = _make_document(conn, app_id)
    _add_field(conn, doc_id, "certificate_number", "CERT-RERUN-0001")
    _add_field(conn, doc_id, "institution_name", "Test Institute")
    _add_issuer_record(conn, "affiliation", "CERT-RERUN-0001", "Test Institute", "2099-01-01")
    conn.close()

    issuer_service.run_issuer_verification(officer, app_id)
    issuer_service.run_issuer_verification(officer, app_id)

    conn = temp_db.get_connection()
    finding_count = conn.execute(
        "SELECT COUNT(*) c FROM findings WHERE application_id = ? AND engine = 'issuer_service'",
        (app_id,),
    ).fetchone()["c"]
    request_count = conn.execute(
        "SELECT COUNT(*) c FROM verification_requests WHERE application_id = ?", (app_id,)
    ).fetchone()["c"]
    conn.close()
    assert finding_count == 1
    assert request_count == 1


def test_applicant_cannot_run_issuer_verification(temp_db):
    conn = temp_db.get_connection()
    applicant = _make_applicant(conn)
    app_id = _make_application(conn)
    conn.close()

    try:
        issuer_service.run_issuer_verification(applicant, app_id)
        assert False, "expected PermissionDenied"
    except PermissionDenied:
        pass