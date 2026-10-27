"""
Seeds demo institutions, demo user accounts, synthetic demo
applications, and synthetic mock issuer records for local development
and demonstration purposes.

All seeded data is synthetic / for demo purposes only - no real
institution or personal data.

Idempotent: each of the three "if empty" seed functions below is gated
independently on its own table being empty, so re-running the app never
duplicates or resets demo data. Phase 7 adds reset_synthetic_demo_data(),
an admin-only action that removes ONLY rows flagged synthetic and then
re-seeds a fresh copy -- it never touches real user accounts,
institutions, or non-synthetic applications.
"""
import shutil
from datetime import date
from pathlib import Path

from dateutil.relativedelta import relativedelta

from database.db import get_connection
from utils.security import hash_password
from utils import audit


# (institution_code, name, address, state)
DEMO_INSTITUTIONS = [
    ("INST-001", "Shree Institute of Technology", "Pune", "Maharashtra"),
    ("INST-002", "Bharat College of Engineering", "Lucknow", "Uttar Pradesh"),
    ("INST-003", "National Polytechnic Institute", "Jaipur", "Rajasthan"),
]

# (username, password, full_name, role, email, institution_code_or_None)
DEMO_USERS = [
    ("admin", "Admin@123", "System Administrator", "admin", "admin@example.test", None),
    ("officer1", "Officer@123", "Officer A. Sharma", "officer", "officer1@example.test", None),
    ("officer2", "Officer@123", "Officer B. Iyer", "officer", "officer2@example.test", None),
    ("applicant1", "Applicant@123", "Applicant Demo User", "applicant",
     "applicant1@example.test", "INST-001"),
]


def _users_table_has_rows(conn) -> bool:
    cur = conn.execute("SELECT COUNT(*) AS c FROM users")
    row = cur.fetchone()
    return row["c"] > 0


def seed_if_empty():
    """
    Populate demo institutions and demo user accounts if the database
    has no users yet. Safe to call on every app startup.
    """
    conn = get_connection()
    try:
        if _users_table_has_rows(conn):
            return  # already seeded, do nothing

        # Seed institutions and remember code -> integer id mapping
        code_to_id = {}
        for code, name, address, state in DEMO_INSTITUTIONS:
            cur = conn.execute(
                """
                INSERT INTO institutions (name, institution_code, address, state)
                VALUES (?, ?, ?, ?)
                """,
                (name, code, address, state),
            )
            code_to_id[code] = cur.lastrowid

        # Seed users
        for username, password, full_name, role, email, inst_code in DEMO_USERS:
            salt_hex, hash_hex = hash_password(password)
            institution_id = code_to_id.get(inst_code) if inst_code else None
            conn.execute(
                """
                INSERT INTO users (
                    username, password_salt, password_hash,
                    full_name, role, institution_id, email, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (username, salt_hex, hash_hex, full_name, role, institution_id, email),
            )

        conn.commit()
    finally:
        conn.close()


def seed_demo_data():
    """Alias used by the test suite. Functionally identical to
    seed_if_empty() -- kept as a separate name so tests can call it
    without implying anything about app.py's idempotency behavior."""
    seed_if_empty()


# ---------------------------------------------------------------------
# Synthetic demo application scenarios (Module K)
#
# SCENARIO_CATALOG documents every synthetic scenario this project
# ships for demonstration purposes -- used by administration.py's
# "Demo Data" tab and referenced in the README/demo script so every
# scenario's intended outcome is written down in exactly one place.
# ---------------------------------------------------------------------

SCENARIO_CATALOG = [
    {"scenario_tag": "complete_consistent", "institution": "Shree Institute of Technology",
     "kind": "clean", "summary": "All documents complete, consistent, and within validity."},
    {"scenario_tag": "missing_document", "institution": "Bharat College of Engineering",
     "kind": "defective", "summary": "Fire NOC was never uploaded (RULE-001)."},
    {"scenario_tag": "expired_certificate", "institution": "National Polytechnic Institute",
     "kind": "defective", "summary": "Affiliation certificate is expired (RULE-003); "
                                       "issuer record also shows a name mismatch; e-stamp "
                                       "issuer record is absent (source unavailable)."},
    {"scenario_tag": "complete_consistent_2", "institution": "Vindhya College of Engineering",
     "kind": "clean", "summary": "A second clean, fully consistent example at a different institution."},
    {"scenario_tag": "institution_name_mismatch", "institution": "Vikas Engineering College",
     "kind": "defective", "summary": "Affiliation certificate and Fire NOC name two unrelated institutions (RULE-005)."},
    {"scenario_tag": "duplicate_certificate_number", "institution": "Deccan Institute of Science",
     "kind": "defective", "summary": "Affiliation certificate reuses Shree's exact certificate "
                                       "number (RULE-007); also resolves to Shree's issuer "
                                       "record under the wrong institution name."},
    {"scenario_tag": "conflicting_certificate_in_document", "institution": "Ganga Valley Institute",
     "kind": "defective", "summary": "The affiliation certificate itself states two different "
                                       "certificate numbers (RULE-008)."},
    {"scenario_tag": "duplicate_uploaded_file", "institution": "Himalayan College of Engineering",
     "kind": "defective", "summary": "The same PDF file is uploaded under two different document types (RULE-009)."},
    {"scenario_tag": "issuer_record_unavailable", "institution": "Coastal Polytechnic",
     "kind": "defective", "summary": "The affiliation certificate's number has no matching mock issuer record."},
    {"scenario_tag": "issuer_institution_mismatch", "institution": "Meridian Institute of Technology",
     "kind": "defective", "summary": "The affiliation certificate's mock issuer record exists under a different institution name."},
    {"scenario_tag": "qr_replay_demo", "institution": "Sundarbans College of Technology",
     "kind": "defective", "summary": "The fire NOC embeds the same QR code as the affiliation "
                                       "certificate, printing a different certificate number "
                                       "(QR replay). Requires the optional 'qrcode'/'pyzbar' "
                                       "libraries to demonstrate fully; degrades gracefully "
                                       "(disclosed, not fabricated) if unavailable."},
]


def _applications_table_has_rows(conn) -> bool:
    cur = conn.execute("SELECT COUNT(*) AS c FROM applications")
    row = cur.fetchone()
    return row["c"] > 0


def _create_all_demo_applications():
    """Creates all 11 synthetic demo applications (Module K) with
    generated synthetic PDFs attached. Not gated on table emptiness --
    callers decide when it is appropriate to call this (see
    seed_demo_applications_if_empty and reset_synthetic_demo_data)."""
    conn = get_connection()
    try:
        admin_row = conn.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
        if admin_row is None:
            return  # user seeding has not happened yet; nothing to do
        admin_actor = dict(admin_row)
    finally:
        conn.close()

    # Imported lazily so Phase 1 callers/tests that only need
    # user/institution seeding don't require PDF-generation dependencies.
    from services import application_service
    from sample_data import synthetic_pdfs
    from models.enums import ApplicationCategory, ApplicationStatus

    pdfs = synthetic_pdfs.generate_all()

    def _inst(code, name, address, state):
        return application_service.get_or_create_institution(name, code, address, state)

    shree_id = _inst("INST-001", "Shree Institute of Technology", "Pune", "Maharashtra")
    bharat_id = _inst("INST-002", "Bharat College of Engineering", "Lucknow", "Uttar Pradesh")
    national_id = _inst("INST-003", "National Polytechnic Institute", "Jaipur", "Rajasthan")
    vindhya_id = _inst("INST-004", "Vindhya College of Engineering", "Nagpur", "Maharashtra")
    vikas_id = _inst("INST-005", "Vikas Engineering College", "Bhopal", "Madhya Pradesh")
    deccan_id = _inst("INST-006", "Deccan Institute of Science", "Kochi", "Kerala")
    gangavalley_id = _inst("INST-007", "Ganga Valley Institute", "Patna", "Bihar")
    himalayan_id = _inst("INST-008", "Himalayan College of Engineering", "Chandigarh", "Punjab")
    coastal_id = _inst("INST-009", "Coastal Polytechnic", "Visakhapatnam", "Andhra Pradesh")
    meridian_id = _inst("INST-010", "Meridian Institute of Technology", "Guwahati", "Assam")
    sundarbans_id = _inst("INST-011", "Sundarbans College of Technology", "Kolkata", "West Bengal")

    def _create_app(inst_id, submission_date, scenario_tag):
        return application_service.create_application(
            admin_actor, inst_id, ApplicationCategory.EOA.value, "2025-26", submission_date,
            status=ApplicationStatus.SUBMITTED.value, is_synthetic=True, scenario_tag=scenario_tag,
        )

    def _upload(app_id, logical_name, doc_type):
        path = pdfs[logical_name]
        application_service.add_document(admin_actor, app_id, doc_type, path.name, path.read_bytes())

    # Scenario 1: complete and consistent
    app1 = _create_app(shree_id, "2025-06-01", "complete_consistent")
    _upload(app1, "shree_affiliation", "affiliation_certificate")
    _upload(app1, "shree_fire_noc", "fire_noc")
    _upload(app1, "shree_estamp", "e_stamp")

    # Scenario 2: missing mandatory document (Fire NOC withheld)
    app2 = _create_app(bharat_id, "2025-06-05", "missing_document")
    _upload(app2, "bharat_affiliation", "affiliation_certificate")

    # Scenario 3: expired certificate
    app3 = _create_app(national_id, "2025-06-10", "expired_certificate")
    _upload(app3, "national_affiliation_expired", "affiliation_certificate")
    _upload(app3, "national_fire_noc", "fire_noc")
    _upload(app3, "national_estamp", "e_stamp")

    # Scenario 4 (Phase 7): a second clean application
    app4 = _create_app(vindhya_id, "2025-06-12", "complete_consistent_2")
    _upload(app4, "vindhya_affiliation", "affiliation_certificate")
    _upload(app4, "vindhya_fire_noc", "fire_noc")
    _upload(app4, "vindhya_estamp", "e_stamp")

    # Scenario 5 (Phase 7): institution name mismatch across documents
    app5 = _create_app(vikas_id, "2025-06-14", "institution_name_mismatch")
    _upload(app5, "vikas_affiliation", "affiliation_certificate")
    _upload(app5, "vikas_fire_noc_mismatch", "fire_noc")

    # Scenario 6 (Phase 7): duplicate certificate number across applications
    app6 = _create_app(deccan_id, "2025-06-16", "duplicate_certificate_number")
    _upload(app6, "deccan_affiliation_dup", "affiliation_certificate")
    _upload(app6, "deccan_fire_noc", "fire_noc")
    _upload(app6, "deccan_estamp", "e_stamp")

    # Scenario 7 (Phase 7): conflicting certificate numbers in one document
    app7 = _create_app(gangavalley_id, "2025-06-18", "conflicting_certificate_in_document")
    _upload(app7, "gangavalley_affiliation_conflict", "affiliation_certificate")
    _upload(app7, "gangavalley_fire_noc", "fire_noc")
    _upload(app7, "gangavalley_estamp", "e_stamp")

    # Scenario 8 (Phase 7): duplicate uploaded file (same bytes, two doc types)
    app8 = _create_app(himalayan_id, "2025-06-20", "duplicate_uploaded_file")
    _upload(app8, "himalayan_shared", "affiliation_certificate")
    _upload(app8, "himalayan_shared", "fire_noc")
    _upload(app8, "himalayan_estamp", "e_stamp")

    # Scenario 9 (Phase 7): issuer record unavailable, isolated
    app9 = _create_app(coastal_id, "2025-06-22", "issuer_record_unavailable")
    _upload(app9, "coastal_affiliation_isolated", "affiliation_certificate")
    _upload(app9, "coastal_fire_noc", "fire_noc")
    _upload(app9, "coastal_estamp", "e_stamp")

    # Scenario 10 (Phase 7): issuer institution mismatch, isolated
    app10 = _create_app(meridian_id, "2025-06-24", "issuer_institution_mismatch")
    _upload(app10, "meridian_affiliation_mismatch", "affiliation_certificate")
    _upload(app10, "meridian_fire_noc", "fire_noc")
    _upload(app10, "meridian_estamp", "e_stamp")

    # Scenario 11 (Phase 7): QR replay demonstration
    app11 = _create_app(sundarbans_id, "2025-06-26", "qr_replay_demo")
    _upload(app11, "sundarbans_affiliation_qr", "affiliation_certificate")
    _upload(app11, "sundarbans_fire_noc_qr_replay", "fire_noc")
    _upload(app11, "sundarbans_estamp", "e_stamp")


def seed_demo_applications_if_empty():
    """Creates the full set of synthetic demo applications (Module K)
    if no application exists yet at all. Safe to call on every startup.
    """
    conn = get_connection()
    try:
        if _applications_table_has_rows(conn):
            return
    finally:
        conn.close()
    _create_all_demo_applications()


# ---------------------------------------------------------------------
# Phase 4 (Module G) addition: synthetic mock issuer records.
#
# Dates are computed RELATIVE to the real date at seed-time (via
# dateutil.relativedelta), not hardcoded calendar years -- this mirrors
# the same fix applied to sample_data/synthetic_pdfs.py and prevents the
# "clean" demo scenarios from silently becoming "expired" simply due to
# calendar drift between when this code was written and when it is run.
#
# All data here is FICTIONAL / SYNTHETIC. is_synthetic is always 1.
# ---------------------------------------------------------------------

_TODAY = date.today()
_VALID_ISSUE = (_TODAY - relativedelta(years=2)).isoformat()
_VALID_EXPIRY = (_TODAY + relativedelta(years=2)).isoformat()
_EXPIRED_ISSUE = (_TODAY - relativedelta(years=7)).isoformat()
_EXPIRED_EXPIRY = (_TODAY - relativedelta(years=3)).isoformat()

# (issuer_type, certificate_number, institution_name, issue_date, expiry_date)
DEMO_ISSUER_RECORDS = [
    # Shree Institute of Technology -- all three will VERIFY cleanly.
    ("affiliation", "CERT-AFF-2023-0001", "Shree Institute of Technology",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("fire_noc", "CERT-NOC-2023-0007", "Shree Institute of Technology",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("estamp", "ESTAMP-2023-0099", "Shree Institute of Technology",
     _VALID_ISSUE, _VALID_EXPIRY),

    # Bharat College of Engineering -- affiliation record present and
    # will VERIFY (fire NOC was deliberately never uploaded in the
    # missing_document scenario, so there is nothing to check it against).
    ("affiliation", "CERT-AFF-2022-0045", "Bharat College of Engineering",
     _VALID_ISSUE, _VALID_EXPIRY),

    # National Polytechnic Institute -- deliberately mixed outcomes:
    #   affiliation record exists under a DIFFERENT institution name
    #   than the document claims -> produces MISMATCH.
    ("affiliation", "CERT-AFF-2019-0012", "National Polytechnic College (Demo Records)",
     _EXPIRED_ISSUE, _EXPIRED_EXPIRY),
    #   fire NOC record matches cleanly -> VERIFIED.
    ("fire_noc", "CERT-NOC-2023-0051", "National Polytechnic Institute",
     _VALID_ISSUE, _VALID_EXPIRY),
    # Note: National's e-stamp (ESTAMP-2023-0150) is intentionally NOT
    # present here, so issuer verification for it will produce
    # SOURCE_UNAVAILABLE.

    # --- Phase 7 additions below ---

    # Vindhya College of Engineering -- clean, all verify.
    ("affiliation", "CERT-AFF-2024-0201", "Vindhya College of Engineering",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("fire_noc", "CERT-NOC-2024-0202", "Vindhya College of Engineering",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("estamp", "ESTAMP-2024-0203", "Vindhya College of Engineering",
     _VALID_ISSUE, _VALID_EXPIRY),

    # Vikas Engineering College -- the name-mismatch defect in this
    # scenario is a cross-document (RULE-005) finding, not an
    # issuer-record finding, so only the affiliation record is seeded
    # and verifies cleanly.
    ("affiliation", "CERT-AFF-2024-0301", "Vikas Engineering College",
     _VALID_ISSUE, _VALID_EXPIRY),

    # Deccan Institute of Science -- fire NOC and e-stamp verify
    # cleanly. Deliberately NO issuer record is added for
    # CERT-AFF-2023-0001 under Deccan's name, because that exact
    # (issuer_type, certificate_number) pair already belongs to Shree
    # above -- the duplicate certificate number will therefore resolve
    # to Shree's record, producing an institution-name MISMATCH in
    # addition to validation_engine's own RULE-007 finding. This is a
    # genuine emergent consequence of the duplicate, not a separately
    # engineered outcome.
    ("fire_noc", "CERT-NOC-DEC-0001", "Deccan Institute of Science",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("estamp", "ESTAMP-DEC-0001", "Deccan Institute of Science",
     _VALID_ISSUE, _VALID_EXPIRY),

    # Ganga Valley Institute -- fire NOC and e-stamp verify cleanly.
    # Deliberately NO issuer record for either of the two conflicting
    # affiliation certificate numbers: which of the two conflicting
    # extracted values would be used for an issuer lookup is not
    # guaranteed deterministically by this prototype's extraction
    # logic, so this scenario does not rely on a specific one being
    # picked -- affiliation will show SOURCE_UNAVAILABLE either way.
    ("fire_noc", "CERT-GV-FN-0001", "Ganga Valley Institute",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("estamp", "ESTAMP-GV-0001", "Ganga Valley Institute",
     _VALID_ISSUE, _VALID_EXPIRY),

    # Himalayan College of Engineering -- affiliation and fire NOC share
    # the SAME printed certificate number (CERT-HCE-0001) because they
    # are the same uploaded file reused under two doc types (RULE-009
    # demo); both issuer_type lookups are seeded to verify cleanly so
    # the scenario isolates to the duplicate-file-hash finding.
    ("affiliation", "CERT-HCE-0001", "Himalayan College of Engineering",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("fire_noc", "CERT-HCE-0001", "Himalayan College of Engineering",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("estamp", "ESTAMP-HCE-0001", "Himalayan College of Engineering",
     _VALID_ISSUE, _VALID_EXPIRY),

    # Coastal Polytechnic -- fire NOC and e-stamp verify cleanly. NO
    # issuer record exists for the affiliation certificate number at
    # all, so that single document's issuer verification will produce
    # SOURCE_UNAVAILABLE in isolation.
    ("fire_noc", "CERT-NOC-CP-0001", "Coastal Polytechnic",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("estamp", "ESTAMP-CP-0001", "Coastal Polytechnic",
     _VALID_ISSUE, _VALID_EXPIRY),

    # Meridian Institute of Technology -- fire NOC and e-stamp verify
    # cleanly. The affiliation record exists under a DIFFERENT
    # institution name, isolating this scenario to a single issuer
    # mismatch.
    ("affiliation", "CERT-AFF-MIT-0001", "Meridian Institute of Science (Demo Records)",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("fire_noc", "CERT-NOC-MIT-0002", "Meridian Institute of Technology",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("estamp", "ESTAMP-MIT-0003", "Meridian Institute of Technology",
     _VALID_ISSUE, _VALID_EXPIRY),

    # Sundarbans College of Technology -- all three issuer records
    # verify cleanly against each document's own PRINTED certificate
    # number. The QR replay defect lives entirely in the QR payload
    # embedded in the PDF image, not in these issuer records, so issuer
    # verification alone shows this application as clean -- the replay
    # is only visible via QR verification.
    ("affiliation", "CERT-SBC-0001", "Sundarbans College of Technology",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("fire_noc", "CERT-SBC-0002", "Sundarbans College of Technology",
     _VALID_ISSUE, _VALID_EXPIRY),
    ("estamp", "ESTAMP-SBC-0003", "Sundarbans College of Technology",
     _VALID_ISSUE, _VALID_EXPIRY),
]


def _issuer_records_table_has_rows(conn) -> bool:
    cur = conn.execute("SELECT COUNT(*) AS c FROM issuer_records")
    row = cur.fetchone()
    return row["c"] > 0


def _create_all_demo_issuer_records():
    """Inserts the full DEMO_ISSUER_RECORDS list. Not gated on table
    emptiness -- callers decide when it is appropriate to call this."""
    conn = get_connection()
    try:
        for issuer_type, certificate_number, institution_name, issue_date, expiry_date in DEMO_ISSUER_RECORDS:
            conn.execute(
                """
                INSERT INTO issuer_records (
                    issuer_type, certificate_number, institution_name,
                    issue_date, expiry_date, is_synthetic
                )
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (issuer_type, certificate_number, institution_name, issue_date, expiry_date),
            )
        conn.commit()
    finally:
        conn.close()


def seed_issuer_records_if_empty():
    """Populates the mock/synthetic issuer_records table if it is empty.
    Safe to call on every app startup; skipped entirely once any
    issuer_records row already exists.
    """
    conn = get_connection()
    try:
        if _issuer_records_table_has_rows(conn):
            return
    finally:
        conn.close()
    _create_all_demo_issuer_records()


# ---------------------------------------------------------------------
# Phase 7 (Section C): safe reset of synthetic demo data only.
# ---------------------------------------------------------------------

def _get_synthetic_application_ids(conn):
    rows = conn.execute("SELECT id FROM applications WHERE is_synthetic = 1").fetchall()
    return [r["id"] for r in rows]


def reset_synthetic_demo_data(actor):
    """Admin-only. Deletes ALL synthetic demo data (applications flagged
    is_synthetic=1, their documents/findings/checklist items/
    verification requests, and synthetic issuer_records), removes the
    corresponding on-disk upload folders, then re-seeds a fresh copy of
    the full synthetic demo scenario set.

    Scoped STRICTLY to rows flagged synthetic -- never touches real user
    accounts, institutions, or any application with is_synthetic=0.

    The audit log itself is append-only and is NEVER deleted from (doing
    so would break hash-chain verification for every subsequent entry);
    this reset instead records two new audit entries (stage "deleted"
    and stage "reseeded"), preserving a tamper-evident record that the
    reset occurred.

    Returns {"applications_removed": int, "issuer_records_removed": int}.
    """
    from services.auth_service import require_role
    require_role(actor, ("admin",))

    conn = get_connection()
    removed_app_count = 0
    removed_issuer_count = 0
    folders_to_remove = set()
    try:
        app_ids = _get_synthetic_application_ids(conn)
        removed_app_count = len(app_ids)

        if app_ids:
            placeholders = ",".join("?" for _ in app_ids)

            doc_rows = conn.execute(
                f"SELECT id, stored_path FROM documents WHERE application_id IN ({placeholders})",
                app_ids,
            ).fetchall()
            doc_ids = [r["id"] for r in doc_rows]
            for r in doc_rows:
                if r["stored_path"]:
                    folders_to_remove.add(Path(r["stored_path"]).resolve().parent)

            if doc_ids:
                doc_placeholders = ",".join("?" for _ in doc_ids)
                conn.execute(
                    f"DELETE FROM extracted_fields WHERE document_id IN ({doc_placeholders})",
                    doc_ids,
                )

            conn.execute(
                f"DELETE FROM verification_requests WHERE application_id IN ({placeholders})",
                app_ids,
            )
            conn.execute(
                f"DELETE FROM findings WHERE application_id IN ({placeholders})",
                app_ids,
            )
            conn.execute(
                f"DELETE FROM checklist_items WHERE application_id IN ({placeholders})",
                app_ids,
            )
            conn.execute(
                f"DELETE FROM documents WHERE application_id IN ({placeholders})",
                app_ids,
            )
            conn.execute(
                f"DELETE FROM applications WHERE id IN ({placeholders})",
                app_ids,
            )

        cur = conn.execute("DELETE FROM issuer_records WHERE is_synthetic = 1")
        removed_issuer_count = cur.rowcount

        conn.commit()

        audit.append_entry(
            conn, actor=actor["username"], action="DEMO_DATA_RESET",
            record_type="system", record_id="synthetic_demo_data",
            payload={
                "stage": "deleted",
                "applications_removed": removed_app_count,
                "issuer_records_removed": removed_issuer_count,
            },
        )
        conn.commit()
    finally:
        conn.close()

    for folder in folders_to_remove:
        shutil.rmtree(folder, ignore_errors=True)

    _create_all_demo_applications()
    _create_all_demo_issuer_records()

    conn = get_connection()
    try:
        audit.append_entry(
            conn, actor=actor["username"], action="DEMO_DATA_RESET",
            record_type="system", record_id="synthetic_demo_data",
            payload={"stage": "reseeded", "scenario_count": len(SCENARIO_CATALOG)},
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "applications_removed": removed_app_count,
        "issuer_records_removed": removed_issuer_count,
    }