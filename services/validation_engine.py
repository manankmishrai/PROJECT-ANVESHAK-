"""Module D: deterministic validation rules engine.

Executes a validated, versioned YAML rule pack (see
services.rule_pack_loader) against the stored data for one
application: its checklist, uploaded documents, and extracted fields.

All checks here are deterministic and explainable -- no ML, no
probabilistic fraud scoring. Every produced finding states what was
expected, what was observed, and why, and is traceable back to a
specific rule_id and rule-pack version.

IMPORTANT (binding project rule): these findings are advisory only.
No finding produced here may be treated as proof of fraud or forgery.
Signature-related findings explicitly distinguish "not yet verified"
from an actual cryptographic verification result -- real signature
verification now exists in services.forensics_engine (Phase 4).
Final adverse decisions always require a human officer (Module J,
Phase 5).
"""
from datetime import datetime, timezone
from pathlib import Path

from database.db import get_connection
from services.auth_service import require_role
from services.rule_pack_loader import load_rule_pack, register_rule_pack
from services import evidence_ladder
from models.enums import RuleType, Rung

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RULE_PACK_PATH = ROOT_DIR / "rules" / "eoa_illustrative_v1.yaml"


# ---------------------------------------------------------------------
# Rule handlers: each takes (rule: dict, ctx: dict) and returns a list
# of raw finding dicts (without id/application_id/rule_id/severity/etc,
# which the orchestrator fills in uniformly below).
# ---------------------------------------------------------------------

def _normalize(value):
    if value is None:
        return None
    return " ".join(str(value).strip().split()).lower()


def _parse_date(value):
    if not value:
        return None
    from dateutil import parser as dateutil_parser
    try:
        return dateutil_parser.parse(str(value), dayfirst=True, fuzzy=True).date()
    except (ValueError, TypeError, OverflowError):
        return None


def _check_missing_required_document(rule, ctx):
    findings = []
    for item in ctx["checklist"]:
        if item["required"] and not item["satisfied"]:
            findings.append({
                "document_id": None,
                "description": f"Required document type '{item['doc_type']}' has not been uploaded.",
                "reason": "The application checklist marks this document type as required, "
                          "but no matching document has been uploaded yet.",
                "extracted_value": "not uploaded",
                "expected_value": item["doc_type"],
                "page_number": None,
                "recommended_action": f"Request the applicant to upload a valid '{item['doc_type']}' document.",
            })
    return findings


def _check_missing_required_field(rule, ctx):
    findings = []
    applicable_types = rule.get("applicable_doc_types") or []
    required_fields = rule.get("required_fields") or []
    if not required_fields:
        return findings
    for doc in ctx["documents"]:
        if applicable_types and doc["doc_type"] not in applicable_types:
            continue
        present_fields = {f["field_name"] for f in doc["fields"]}
        for field_name in required_fields:
            if field_name not in present_fields:
                findings.append({
                    "document_id": doc["id"],
                    "description": f"Required field '{field_name}' could not be extracted from this document.",
                    "reason": "This field was not found by text/field extraction. It has not "
                              "been guessed or fabricated -- it may be present but unreadable, "
                              "or genuinely absent from the document.",
                    "extracted_value": None,
                    "expected_value": field_name,
                    "page_number": None,
                    "recommended_action": f"Manually inspect the document for '{field_name}' "
                                           "or request a clearer copy from the applicant.",
                })
    return findings


def _check_expired_certificate(rule, ctx):
    findings = []
    applicable_types = rule.get("applicable_doc_types") or []
    today = datetime.now().date()
    for doc in ctx["documents"]:
        if applicable_types and doc["doc_type"] not in applicable_types:
            continue
        for f in doc["fields"]:
            if f["field_name"] != "expiry_date":
                continue
            expiry_date = _parse_date(f["field_value"])
            if expiry_date is None:
                continue
            if expiry_date < today:
                findings.append({
                    "document_id": doc["id"],
                    "description": "Certificate appears to have expired.",
                    "reason": f"Extracted expiry date '{f['field_value']}' (parsed as "
                              f"{expiry_date.isoformat()}) is before today's date "
                              f"({today.isoformat()}).",
                    "extracted_value": f["field_value"],
                    "expected_value": f"expiry date on or after {today.isoformat()}",
                    "page_number": f["page_number"],
                    "recommended_action": "Request a renewed/valid certificate from the applicant.",
                })
    return findings


def _check_invalid_date_range(rule, ctx):
    findings = []
    applicable_types = rule.get("applicable_doc_types") or []
    for doc in ctx["documents"]:
        if applicable_types and doc["doc_type"] not in applicable_types:
            continue
        issue_vals = [f for f in doc["fields"] if f["field_name"] == "issue_date"]
        expiry_vals = [f for f in doc["fields"] if f["field_name"] == "expiry_date"]
        if not issue_vals or not expiry_vals:
            continue
        issue_date = _parse_date(issue_vals[0]["field_value"])
        expiry_date = _parse_date(expiry_vals[0]["field_value"])
        if issue_date is None or expiry_date is None:
            continue
        if expiry_date <= issue_date:
            findings.append({
                "document_id": doc["id"],
                "description": "Expiry date is not after the issue date.",
                "reason": f"Issue date '{issue_vals[0]['field_value']}' and expiry date "
                          f"'{expiry_vals[0]['field_value']}' form an invalid range.",
                "extracted_value": f"issue={issue_vals[0]['field_value']}, "
                                    f"expiry={expiry_vals[0]['field_value']}",
                "expected_value": "expiry date after issue date",
                "page_number": issue_vals[0]["page_number"],
                "recommended_action": "Verify the correct dates with the applicant/issuer; "
                                       "this may indicate a data entry or OCR error rather than fraud.",
            })
    return findings


def _check_cross_document_field_mismatch(rule, ctx):
    field_name = rule.get("params", {}).get("field_name")
    fuzzy = bool(rule.get("params", {}).get("fuzzy", False))
    if not field_name:
        return []

    doc_values = []
    for doc in ctx["documents"]:
        matches = [f for f in doc["fields"] if f["field_name"] == field_name]
        if matches:
            doc_values.append((doc, matches[0]))
    if len(doc_values) < 2:
        return []

    findings = []
    baseline_doc, baseline_field = doc_values[0]
    baseline_value = baseline_field["field_value"]
    baseline_norm = _normalize(baseline_value)

    for doc, field in doc_values[1:]:
        candidate_norm = _normalize(field["field_value"])
        if fuzzy:
            from rapidfuzz import fuzz
            similarity = fuzz.ratio(baseline_norm or "", candidate_norm or "")
            mismatch = similarity < 85  # disclosed heuristic threshold, not a regulatory figure
        else:
            mismatch = candidate_norm != baseline_norm
        if mismatch:
            findings.append({
                "document_id": doc["id"],
                "description": f"'{field_name}' does not match the value found in an earlier "
                                f"document of this application.",
                "reason": f"Baseline value \"{baseline_value}\" (from "
                          f"{baseline_doc['original_filename']}) differs from "
                          f"\"{field['field_value']}\" (from {doc['original_filename']}).",
                "extracted_value": field["field_value"],
                "expected_value": baseline_value,
                "page_number": field["page_number"],
                "recommended_action": "Confirm the correct details with the applicant; a "
                                       "mismatch alone does not prove forgery and requires "
                                       "manual review.",
            })
    return findings


def _check_duplicate_certificate_number(rule, ctx):
    findings = []
    conn = ctx["conn"]
    this_app_id = ctx["application"]["id"]
    seen_values = {
        f["field_value"]
        for doc in ctx["documents"] for f in doc["fields"]
        if f["field_name"] == "certificate_number" and f["field_value"]
    }
    for value in seen_values:
        rows = conn.execute(
            """SELECT d.id AS document_id, a.application_code
               FROM extracted_fields ef
               JOIN documents d ON d.id = ef.document_id
               JOIN applications a ON a.id = d.application_id
               WHERE ef.field_name = 'certificate_number' AND ef.field_value = ?
                 AND d.application_id != ?""",
            (value, this_app_id),
        ).fetchall()
        if not rows:
            continue
        this_doc = next(
            (doc for doc in ctx["documents"]
             for f in doc["fields"] if f["field_name"] == "certificate_number" and f["field_value"] == value),
            None,
        )
        other_codes = ", ".join(sorted({r["application_code"] for r in rows}))
        findings.append({
            "document_id": this_doc["id"] if this_doc else None,
            "description": "Certificate number also appears on a different application.",
            "reason": f"Certificate number '{value}' was also found on application(s): {other_codes}.",
            "extracted_value": value,
            "expected_value": "a certificate number unique to this application",
            "page_number": None,
            "recommended_action": "Investigate whether this certificate has been reused across "
                                   "institutions. This alone is not proof of fraud.",
        })
    return findings


def _check_conflicting_field_values(rule, ctx):
    findings = []
    fields_to_check = rule.get("params", {}).get("fields") or rule.get("required_fields") or []
    for doc in ctx["documents"]:
        for field_name in fields_to_check:
            matches = [f for f in doc["fields"] if f["field_name"] == field_name]
            distinct_values = {_normalize(m["field_value"]) for m in matches if m["field_value"]}
            if len(distinct_values) > 1:
                raw_values = sorted({m["field_value"] for m in matches if m["field_value"]})
                findings.append({
                    "document_id": doc["id"],
                    "description": f"Multiple conflicting values were extracted for "
                                    f"'{field_name}' within the same document.",
                    "reason": f"Found distinct values on this document: {raw_values}.",
                    "extracted_value": "; ".join(raw_values),
                    "expected_value": "a single consistent value",
                    "page_number": matches[0]["page_number"] if matches else None,
                    "recommended_action": "Manually inspect the document; this may indicate OCR "
                                           "noise or genuinely conflicting information.",
                })
    return findings


def _check_duplicate_file_hash(rule, ctx):
    findings = []
    conn = ctx["conn"]
    for doc in ctx["documents"]:
        rows = conn.execute(
            """SELECT d.id AS document_id, d.original_filename, a.application_code
               FROM documents d JOIN applications a ON a.id = d.application_id
               WHERE d.sha256 = ? AND d.id != ?""",
            (doc["sha256"], doc["id"]),
        ).fetchall()
        for row in rows:
            findings.append({
                "document_id": doc["id"],
                "description": "This uploaded file is byte-for-byte identical to another "
                                "uploaded document.",
                "reason": f"SHA-256 fingerprint matches document "
                          f"'{row['original_filename']}' on application {row['application_code']}.",
                "extracted_value": doc["sha256"],
                "expected_value": "a unique file per document",
                "page_number": None,
                "recommended_action": "Confirm whether this is an intentional resubmission; "
                                       "not inherently proof of wrongdoing.",
            })
    return findings


def _check_missing_signature_info(rule, ctx):
    findings = []
    applicable_types = rule.get("applicable_doc_types") or []
    for doc in ctx["documents"]:
        if applicable_types and doc["doc_type"] not in applicable_types:
            continue
        findings.append({
            "document_id": doc["id"],
            "description": "Digital signature status has not yet been verified for this document.",
            "reason": "This finding only records that services.forensics_engine (Phase 4) has "
                      "not yet run for this document, or was not re-run since this field was "
                      "extracted -- it must never be read as 'signature missing' or 'invalid'. "
                      "See the signature finding from forensics_engine for the real result.",
            "extracted_value": "signature_status=not_yet_checked",
            "expected_value": "a completed signature verification result",
            "page_number": None,
            "recommended_action": "Run 'Run signature & metadata checks' (Module F) for a real result.",
        })
    return findings


RULE_HANDLERS = {
    RuleType.MISSING_REQUIRED_DOCUMENT.value: _check_missing_required_document,
    RuleType.MISSING_REQUIRED_FIELD.value: _check_missing_required_field,
    RuleType.EXPIRED_CERTIFICATE.value: _check_expired_certificate,
    RuleType.INVALID_DATE_RANGE.value: _check_invalid_date_range,
    RuleType.CROSS_DOCUMENT_FIELD_MISMATCH.value: _check_cross_document_field_mismatch,
    RuleType.DUPLICATE_CERTIFICATE_NUMBER.value: _check_duplicate_certificate_number,
    RuleType.CONFLICTING_FIELD_VALUES.value: _check_conflicting_field_values,
    RuleType.DUPLICATE_FILE_HASH.value: _check_duplicate_file_hash,
    RuleType.MISSING_SIGNATURE_INFO.value: _check_missing_signature_info,
}


# ---------------------------------------------------------------------
# Context building + orchestration
# ---------------------------------------------------------------------

def _build_context(conn, application_id):
    app_row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    if app_row is None:
        raise ValueError(f"No application with id {application_id}.")

    checklist = [dict(r) for r in conn.execute(
        "SELECT * FROM checklist_items WHERE application_id = ? ORDER BY id", (application_id,)
    ).fetchall()]

    documents = [dict(r) for r in conn.execute(
        "SELECT * FROM documents WHERE application_id = ? ORDER BY upload_date, id", (application_id,)
    ).fetchall()]
    for doc in documents:
        doc["fields"] = [dict(r) for r in conn.execute(
            "SELECT * FROM extracted_fields WHERE document_id = ? ORDER BY page_number, id", (doc["id"],)
        ).fetchall()]

    return {
        "application": dict(app_row),
        "checklist": checklist,
        "documents": documents,
        "conn": conn,
    }


def run_validation(actor, application_id, rule_pack_path=DEFAULT_RULE_PACK_PATH):
    """Runs every enabled rule in the given rule pack against the stored
    data for one application, persists the resulting findings, and
    returns the list of inserted finding ids.

    Idempotent / reproducible: findings previously generated by the
    rule engine for this application are replaced (not accumulated) on
    each run, so re-running validation never produces uncontrolled
    duplicate records.
    """
    require_role(actor, ("officer", "admin"))

    rule_pack = load_rule_pack(rule_pack_path)
    register_rule_pack(actor, rule_pack)

    conn = get_connection()
    try:
        ctx = _build_context(conn, application_id)

        raw_findings = []
        for rule in rule_pack["rules"]:
            if not rule.get("enabled", True):
                continue
            handler = RULE_HANDLERS.get(rule["rule_type"])
            if handler is None:
                continue
            for raw in handler(rule, ctx):
                raw_findings.append((rule, raw))

        conn.execute(
            "DELETE FROM findings WHERE application_id = ? AND engine = 'rule_engine'",
            (application_id,),
        )

        now = datetime.now(timezone.utc).isoformat()
        inserted_ids = []
        for rule, raw in raw_findings:
            cur = conn.execute(
                """INSERT INTO findings
                   (application_id, document_id, rule_id, rule_pack_version, engine, severity,
                    rung, status, description, reason, extracted_value, expected_value,
                    page_number, clause_ref, recommended_action, advisory, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    application_id, raw.get("document_id"), rule["rule_id"], rule_pack["version"],
                    "rule_engine", rule["severity"], Rung.ANOMALY.value, "open",
                    raw["description"], raw["reason"], raw.get("extracted_value"),
                    raw.get("expected_value"), raw.get("page_number"), rule.get("clause_ref"),
                    raw.get("recommended_action"), 1, now,
                ),
            )
            inserted_ids.append(cur.lastrowid)

        conn.commit()
        from utils import audit
        audit.append_entry(
            conn, actor=actor["username"], action="VALIDATION_RUN",
            record_type="application", record_id=str(application_id),
            payload={"rule_pack": f"{rule_pack['name']}:{rule_pack['version']}",
                     "finding_count": len(inserted_ids)},
        )
        evidence_ladder.recompute_and_store_priority(conn, application_id, actor["username"])
        return inserted_ids
    finally:
        conn.close()


def list_findings(actor, application_id=None, severity=None, rule_id=None, status=None):
    """Read-only findings listing with optional filters. Available to
    officers and admins; applicant-facing simplified views are deferred
    to a later phase (Module I: applicants see completeness/consistency
    feedback only, not raw rule-engine internals)."""
    require_role(actor, ("officer", "admin"))

    conn = get_connection()
    try:
        query = """
            SELECT f.*, a.application_code, a.institution_id, i.name AS institution_name,
                   d.original_filename, d.doc_type
            FROM findings f
            JOIN applications a ON a.id = f.application_id
            JOIN institutions i ON i.id = a.institution_id
            LEFT JOIN documents d ON d.id = f.document_id
            WHERE 1=1
        """
        params = []
        if application_id is not None:
            query += " AND f.application_id = ?"
            params.append(application_id)
        if severity:
            query += " AND f.severity = ?"
            params.append(severity)
        if rule_id:
            query += " AND f.rule_id = ?"
            params.append(rule_id)
        if status:
            query += " AND f.status = ?"
            params.append(status)
        query += " ORDER BY f.created_at DESC"

        cur = conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()