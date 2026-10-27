"""Tests for Module D's QR verification addition. Parsing and replay
detection are tested independently of whether pyzbar is actually
installed; one optional end-to-end test skips cleanly if qrcode/pyzbar
are unavailable rather than failing."""
import pytest

from services import qr_service
from services.auth_service import PermissionDenied
from models.enums import Rung, VerificationStatus


def test_parse_qr_payload_allowlisted_host():
    payload = "https://verify.mock-issuer.test/verify?issuer_type=affiliation&certificate_number=CERT-0001"
    parsed = qr_service.parse_qr_payload(payload)
    assert parsed["host_allowlisted"] is True
    assert parsed["certificate_number"] == "CERT-0001"
    assert parsed["issuer_type"] == "affiliation"


def test_parse_qr_payload_non_allowlisted_host():
    payload = "https://some-random-site.example/verify?certificate_number=CERT-0001"
    parsed = qr_service.parse_qr_payload(payload)
    assert parsed["host_allowlisted"] is False


def test_parse_qr_payload_non_url_text_returns_none():
    parsed = qr_service.parse_qr_payload("this is not a url at all")
    assert parsed is None


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


def _make_application(conn, code):
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


def _make_document(conn, application_id):
    conn.execute(
        """INSERT INTO documents (application_id, doc_type, original_filename, stored_path, sha256)
           VALUES (?, 'affiliation_certificate', 'test.pdf', 'nonexistent/test.pdf', 'deadbeef')""",
        (application_id,),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM documents WHERE application_id = ? ORDER BY id DESC LIMIT 1", (application_id,)
    ).fetchone()["id"]


def _add_field(conn, document_id, field_name, value):
    conn.execute(
        """INSERT INTO extracted_fields (document_id, field_name, field_value, confidence, page_number)
           VALUES (?, ?, ?, 1.0, 1)""",
        (document_id, field_name, value),
    )
    conn.commit()


def test_qr_replay_detection_flags_shared_payload_different_certs(temp_db):
    conn = temp_db.get_connection()
    app_a = _make_application(conn, "APP-QR-A")
    app_b = _make_application(conn, "APP-QR-B")
    doc_a = _make_document(conn, app_a)
    doc_b = _make_document(conn, app_b)

    shared_payload = "https://verify.mock-issuer.test/verify?issuer_type=affiliation&certificate_number=CERT-ORIGINAL"
    _add_field(conn, doc_a, "qr_payload", shared_payload)
    _add_field(conn, doc_a, "certificate_number", "CERT-ORIGINAL")
    _add_field(conn, doc_b, "qr_payload", shared_payload)
    _add_field(conn, doc_b, "certificate_number", "CERT-DIFFERENT")
    conn.commit()

    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    inserted = qr_service._detect_qr_replay(conn, app_b, now)
    conn.commit()
    assert len(inserted) == 1

    row = conn.execute(
        "SELECT * FROM findings WHERE id = ?", (inserted[0],)
    ).fetchone()
    assert row["rule_id"] == "QR-REPLAY-DETECTED"
    assert row["rung"] == Rung.CONSISTENT.value
    assert row["severity"] == "high"
    conn.close()


def test_qr_replay_not_flagged_when_certificate_numbers_match(temp_db):
    conn = temp_db.get_connection()
    app_a = _make_application(conn, "APP-QR-C")
    app_b = _make_application(conn, "APP-QR-D")
    doc_a = _make_document(conn, app_a)
    doc_b = _make_document(conn, app_b)

    shared_payload = "https://verify.mock-issuer.test/verify?issuer_type=affiliation&certificate_number=CERT-SAME"
    _add_field(conn, doc_a, "qr_payload", shared_payload)
    _add_field(conn, doc_a, "certificate_number", "CERT-SAME")
    _add_field(conn, doc_b, "qr_payload", shared_payload)
    _add_field(conn, doc_b, "certificate_number", "CERT-SAME")
    conn.commit()

    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    inserted = qr_service._detect_qr_replay(conn, app_b, now)
    conn.close()
    assert inserted == []


def test_run_qr_verification_requires_officer_or_admin(temp_db):
    conn = temp_db.get_connection()
    applicant = _make_applicant(conn)
    app_id = _make_application(conn, "APP-QR-RBAC")
    conn.close()

    try:
        qr_service.run_qr_verification(applicant, app_id)
        assert False, "expected PermissionDenied"
    except PermissionDenied:
        pass


def test_run_qr_verification_handles_missing_file_gracefully(temp_db):
    conn = temp_db.get_connection()
    officer = _make_officer(conn)
    app_id = _make_application(conn, "APP-QR-MISSING")
    _make_document(conn, app_id)  # stored_path points nowhere real
    conn.close()

    # Must not raise even though the file does not exist on disk.
    result = qr_service.run_qr_verification(officer, app_id)
    assert isinstance(result, list)


def test_round_trip_generate_and_decode_qr(tmp_path):
    """Best-effort, honest end-to-end test: skips cleanly (not a
    failure) if qrcode/pyzbar are not installed in this environment."""
    qrcode = pytest.importorskip("qrcode")
    pytest.importorskip("pyzbar")
    pymupdf = pytest.importorskip("pymupdf")

    img = qrcode.make(
        "https://verify.mock-issuer.test/verify?issuer_type=affiliation&certificate_number=CERT-RT-0001"
    )
    img_path = tmp_path / "qr.png"
    img.save(str(img_path))

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(50, 50, 250, 250), filename=str(img_path))
    pdf_path = tmp_path / "qr_test.pdf"
    doc.save(str(pdf_path))
    doc.close()

    assert qr_service.QR_DECODE_AVAILABLE is True
    hits = qr_service.extract_qr_payloads_from_pdf(pdf_path)
    assert len(hits) == 1
    parsed = qr_service.parse_qr_payload(hits[0]["payload"])
    assert parsed["host_allowlisted"] is True
    assert parsed["certificate_number"] == "CERT-RT-0001"