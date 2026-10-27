"""Module B: application intake, document upload orchestration.
Phase 5 adds Module J's application-level officer decision (approve/
reject) and a combined officer-action-history read. Phase 6 adds a
security fix restricting what duplicate-file information an applicant
may see.

All write operations are backend-permission-checked via
services.auth_service.require_role -- the Streamlit UI hiding pages
from certain roles is a convenience only, not the security boundary.
Applicants are further restricted to their own institution's
applications; this is also enforced here, not just in the UI.
"""
import json
import uuid
from pathlib import Path

from database.db import get_connection
from services.auth_service import require_role, PermissionDenied
from services.pdf_service import compute_sha256, extract_document_text
from services.field_extraction import extract_fields_from_pages
from utils.file_safety import validate_upload, safe_filename, build_storage_path
from utils import audit
from models.enums import (
    ApplicationCategory,
    ApplicationStatus,
    DEFAULT_CHECKLIST_BY_CATEGORY,
    APPLICATION_DECISIONS_REQUIRING_REMARKS,
)


# ---------------------------------------------------------------------
# Institutions
# ---------------------------------------------------------------------

def list_institutions():
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM institutions ORDER BY name")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_or_create_institution(name, institution_code, address=None, state=None):
    """Looks up an institution by institution_code; creates it if absent.
    Returns the integer institution id."""
    name = (name or "").strip()
    institution_code = (institution_code or "").strip()
    if not name or not institution_code:
        raise ValueError("Institution name and institution ID are both required.")

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM institutions WHERE institution_code = ?", (institution_code,)
        ).fetchone()
        if row:
            return row["id"]

        cur = conn.execute(
            "INSERT INTO institutions (name, institution_code, address, state) VALUES (?,?,?,?)",
            (name, institution_code, address, state),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------

def _generate_application_code(category: str, academic_year: str) -> str:
    token = uuid.uuid4().hex[:6].upper()
    return f"{category}-{academic_year}-{token}"


def create_application(actor, institution_id, category, academic_year, submission_date,
                        status="submitted", is_synthetic=False, scenario_tag=None):
    """Creates an application plus its default illustrative checklist.
    Returns the new application's integer id.

    NOTE: the checklist attached here (models.enums.DEFAULT_CHECKLIST_BY_CATEGORY)
    is illustrative/demonstration only, not a verified official AICTE/APH
    document list.
    """
    require_role(actor, ("applicant", "admin"))

    if category not in (c.value for c in ApplicationCategory):
        raise ValueError(f"Unsupported category '{category}'.")
    if not academic_year:
        raise ValueError("Academic year is required.")

    if actor["role"] == "applicant" and actor.get("institution_id") != institution_id:
        raise PermissionDenied("Applicants may only create applications for their own institution.")

    conn = get_connection()
    try:
        application_code = _generate_application_code(category, academic_year)
        for _ in range(5):
            clash = conn.execute(
                "SELECT 1 FROM applications WHERE application_code = ?", (application_code,)
            ).fetchone()
            if clash is None:
                break
            application_code = _generate_application_code(category, academic_year)

        cur = conn.execute(
            """INSERT INTO applications
               (application_code, institution_id, category, academic_year, submission_date,
                status, priority, created_by, is_synthetic, scenario_tag)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (application_code, institution_id, category, academic_year, submission_date,
             status, "P4", actor.get("id"), 1 if is_synthetic else 0, scenario_tag),
        )
        application_id = cur.lastrowid

        for doc_type in DEFAULT_CHECKLIST_BY_CATEGORY.get(category, []):
            conn.execute(
                "INSERT INTO checklist_items (application_id, doc_type, required, satisfied) "
                "VALUES (?,?,1,0)",
                (application_id, doc_type),
            )

        conn.commit()
        audit.append_entry(
            conn, actor=actor["username"], action="APPLICATION_CREATED",
            record_type="application", record_id=application_code,
            payload={"institution_id": institution_id, "category": category},
        )
        return application_id
    finally:
        conn.close()


def list_applications(actor):
    """Applicants see only applications belonging to their own
    institution; officers/admins see all. Authoritative filter --
    enforced here, not just by hiding rows in the UI."""
    conn = get_connection()
    try:
        if actor["role"] == "applicant":
            cur = conn.execute(
                """SELECT a.*, i.name AS institution_name, i.institution_code
                   FROM applications a JOIN institutions i ON i.id = a.institution_id
                   WHERE a.institution_id = ?
                   ORDER BY a.created_at DESC""",
                (actor.get("institution_id"),),
            )
        else:
            cur = conn.execute(
                """SELECT a.*, i.name AS institution_name, i.institution_code
                   FROM applications a JOIN institutions i ON i.id = a.institution_id
                   ORDER BY a.created_at DESC"""
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _assert_can_view_application(actor, application_row):
    if actor["role"] == "applicant" and application_row["institution_id"] != actor.get("institution_id"):
        raise PermissionDenied("You do not have access to this application.")


def get_application_detail(actor, application_id):
    """Returns {application, checklist, documents} where each document
    includes its extracted_fields rows and its cached extracted text
    (read back from disk, so this works identically after a restart).
    Raises PermissionDenied if this actor may not view it."""
    conn = get_connection()
    try:
        app_row = conn.execute(
            """SELECT a.*, i.name AS institution_name, i.institution_code
               FROM applications a JOIN institutions i ON i.id = a.institution_id
               WHERE a.id = ?""",
            (application_id,),
        ).fetchone()
        if app_row is None:
            raise ValueError(f"No application with id {application_id}.")
        app_row = dict(app_row)
        _assert_can_view_application(actor, app_row)

        checklist = [dict(r) for r in conn.execute(
            "SELECT * FROM checklist_items WHERE application_id = ? ORDER BY id", (application_id,)
        ).fetchall()]

        documents = [dict(r) for r in conn.execute(
            "SELECT * FROM documents WHERE application_id = ? ORDER BY upload_date", (application_id,)
        ).fetchall()]

        for doc in documents:
            doc["fields"] = [dict(r) for r in conn.execute(
                "SELECT * FROM extracted_fields WHERE document_id = ? ORDER BY page_number", (doc["id"],)
            ).fetchall()]
            doc["pages_text"] = _load_extracted_text(Path(doc["stored_path"]))

        return {"application": app_row, "checklist": checklist, "documents": documents}
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------

def _extracted_text_sidecar(storage_path: Path) -> Path:
    return storage_path.with_name(storage_path.name + ".pages.json")


def _save_extracted_text(storage_path: Path, pages_text: list):
    _extracted_text_sidecar(storage_path).write_text(
        json.dumps(pages_text, ensure_ascii=False), encoding="utf-8"
    )


def _load_extracted_text(storage_path: Path):
    sidecar = _extracted_text_sidecar(storage_path)
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def find_documents_by_sha256(sha256: str):
    """Looks up every stored document (system-wide) matching a SHA-256
    fingerprint, including each match's owning institution_id.

    SECURITY NOTE (Phase 6): this function is intentionally NOT
    institution-filtered -- officers/admins need the full, system-wide
    view to detect cross-institution document reuse (see
    services.validation_engine's duplicate_file_hash rule, which is
    officer/admin-only). Restricting what an APPLICANT caller may see
    from these results is the responsibility of the caller
    (add_document, below), not this function, so this stays a single
    source of truth for "does this file exist anywhere".
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """SELECT d.*, a.application_code, a.institution_id AS institution_id
               FROM documents d JOIN applications a ON a.id = d.application_id
               WHERE d.sha256 = ?""",
            (sha256,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def add_document(actor, application_id, doc_type, original_filename, file_bytes):
    """Validates, stores, fingerprints and extracts text/fields from an
    uploaded PDF, then attaches it to the given application.

    Returns a dict: document_id, sha256, extraction_status, warning,
    duplicates, fields_found, pages_text.

    SECURITY FIX (Phase 6): the `duplicates` list returned to an
    APPLICANT caller is filtered to same-institution matches only.
    Previously this leaked another institution's application_code and
    filename to any applicant who happened to upload a byte-identical
    file (e.g. a shared boilerplate template) -- a cross-institution
    information disclosure. Officers/admins still receive the full,
    system-wide duplicate list, since cross-institution reuse detection
    is a legitimate part of their review role.

    Raises UploadValidationError for rejected files, PermissionDenied
    for authorization failures, ValueError for a missing application,
    an unreadable PDF, or a PDF exceeding the configured page-count
    limit (MAX_PDF_PAGES). Never invents extracted field values --
    absent fields are simply omitted from fields_found.
    """
    require_role(actor, ("applicant", "officer", "admin"))
    validate_upload(original_filename, file_bytes)

    conn = get_connection()
    try:
        app_row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if app_row is None:
            raise ValueError(f"No application with id {application_id}.")
        app_row = dict(app_row)
        _assert_can_view_application(actor, app_row)
    finally:
        conn.close()

    sha256 = compute_sha256(file_bytes)
    duplicates = find_documents_by_sha256(sha256)

    if actor["role"] == "applicant":
        duplicates = [
            d for d in duplicates
            if d.get("institution_id") == actor.get("institution_id")
        ]

    safe_name = safe_filename(original_filename)
    storage_path = build_storage_path(app_row["application_code"], safe_name)
    storage_path.write_bytes(file_bytes)

    try:
        extraction = extract_document_text(file_bytes)
    except ValueError:
        storage_path.unlink(missing_ok=True)
        raise

    _save_extracted_text(storage_path, extraction["pages_text"])
    fields = extract_fields_from_pages(extraction["pages_text"])

    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO documents
               (application_id, doc_type, original_filename, stored_path, sha256, file_size,
                page_count, uploaded_by, extraction_status, is_native_text, ocr_used)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (application_id, doc_type, original_filename, str(storage_path), sha256, len(file_bytes),
             extraction["page_count"], actor.get("id"), extraction["extraction_status"],
             1 if extraction["is_native_text"] else 0, 1 if extraction["ocr_used"] else 0),
        )
        document_id = cur.lastrowid

        for field in fields:
            conn.execute(
                """INSERT INTO extracted_fields (document_id, field_name, field_value, confidence, page_number)
                   VALUES (?,?,?,?,?)""",
                (document_id, field["field_name"], field["field_value"],
                 field["confidence"], field["page_number"]),
            )

        conn.execute(
            "UPDATE checklist_items SET satisfied = 1 WHERE application_id = ? AND doc_type = ?",
            (application_id, doc_type),
        )

        conn.commit()
        audit.append_entry(
            conn, actor=actor["username"], action="DOCUMENT_UPLOADED",
            record_type="document", record_id=str(document_id),
            payload={"application_id": application_id, "doc_type": doc_type, "sha256": sha256},
        )
    finally:
        conn.close()

    return {
        "document_id": document_id,
        "sha256": sha256,
        "extraction_status": extraction["extraction_status"],
        "warning": extraction["warning"],
        "duplicates": duplicates,
        "fields_found": fields,
        "pages_text": extraction["pages_text"],
    }


# ---------------------------------------------------------------------
# Phase 5 additions (Module J: application-level officer decision)
# ---------------------------------------------------------------------

def record_application_decision(actor, application_id, decision, remarks=None):
    """Records a final officer decision (approve/reject) on an
    application as a whole. Rejecting an application is an adverse
    decision and REQUIRES non-empty remarks. Updates applications.status
    and is always hash-chain audited. Does not touch individual finding
    decisions -- see services.review_service for per-finding actions.
    """
    require_role(actor, ("officer", "admin"))

    allowed_decisions = {ApplicationStatus.APPROVED.value, ApplicationStatus.REJECTED.value}
    if decision not in allowed_decisions:
        raise ValueError(f"'{decision}' is not a valid final application decision.")

    remarks = (remarks or "").strip() or None
    if decision in APPLICATION_DECISIONS_REQUIRING_REMARKS and not remarks:
        raise ValueError(
            "Remarks are mandatory when rejecting an application -- an "
            "adverse decision must always carry a documented justification."
        )

    conn = get_connection()
    try:
        app_row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if app_row is None:
            raise ValueError(f"No application with id {application_id}.")
        app_row = dict(app_row)

        conn.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (decision, application_id),
        )
        conn.commit()

        audit.append_entry(
            conn, actor=actor["username"], action="APPLICATION_DECISION_RECORDED",
            record_type="application", record_id=str(application_id),
            payload={
                "application_code": app_row["application_code"],
                "decision": decision,
                "remarks": remarks,
            },
        )
        return True
    finally:
        conn.close()


def get_officer_action_history(actor, application_id):
    """Read-only: reconstructs the human-review history for an
    application by combining (a) per-finding officer decisions and
    (b) application-level decision audit entries. Used by the review
    workbench's 'previous officer actions' section.

    This is a convenience read for display only -- it does not replace
    or duplicate the authoritative tamper-evident audit log itself
    (see utils.audit / the Audit Logs page).
    """
    require_role(actor, ("officer", "admin"))

    conn = get_connection()
    try:
        app_row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if app_row is None:
            raise ValueError(f"No application with id {application_id}.")
        app_row = dict(app_row)

        finding_decisions = conn.execute(
            """SELECT f.id AS finding_id, f.rule_id, f.engine, f.officer_decision,
                      f.officer_remarks, f.decided_at, u.username AS decided_by_username
               FROM findings f
               LEFT JOIN users u ON u.id = f.decided_by
               WHERE f.application_id = ? AND f.officer_decision IS NOT NULL
               ORDER BY f.decided_at DESC""",
            (application_id,),
        ).fetchall()

        audit_rows = conn.execute(
            """SELECT * FROM audit_log
               WHERE action = 'APPLICATION_DECISION_RECORDED'
                 AND record_type = 'application'
                 AND record_id IN (?, ?)
               ORDER BY timestamp DESC""",
            (str(application_id), app_row["application_code"]),
        ).fetchall()

        history = []
        for r in finding_decisions:
            history.append({
                "kind": "finding_decision",
                "timestamp": r["decided_at"],
                "actor": r["decided_by_username"],
                "summary": f"Finding #{r['finding_id']} ({r['rule_id'] or r['engine']}): "
                           f"{r['officer_decision']}",
                "remarks": r["officer_remarks"],
            })
        for r in audit_rows:
            try:
                payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
            except (ValueError, TypeError):
                payload = {}
            history.append({
                "kind": "application_decision",
                "timestamp": r["timestamp"],
                "actor": r["actor"],
                "summary": f"Application decision: {payload.get('decision', '?')}",
                "remarks": payload.get("remarks"),
            })

        history.sort(key=lambda h: h["timestamp"] or "", reverse=True)
        return history
    finally:
        conn.close()