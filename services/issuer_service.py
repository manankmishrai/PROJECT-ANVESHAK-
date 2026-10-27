"""Module G: mock issuer verification service.

Backed entirely by the local SQLite `issuer_records` / `verification_requests`
tables (see database/schema.sql). This is a SYNTHETIC, LOCAL ADAPTER ONLY.
It never represents, and must never be described as, a real government,
AICTE, fire department, or university verification service. Every record
in `issuer_records` is fictional demonstration data (is_synthetic=1).

Six supported outcomes (models.enums.VerificationStatus):
  verification_pending   -- transient DB state while a request is processed
  verified               -- certificate number + institution name matched a
                             known (synthetic) issuer record with no problem
  mismatch_detected      -- certificate number matched a known record, but
                             the institution name is materially different
  expired                -- certificate number + institution matched, but
                             the record's expiry date has passed
  source_unavailable     -- no matching record exists in the mock issuer
                             database for this certificate number. The mock
                             dataset is small and intentionally incomplete --
                             this status does NOT claim the certificate is
                             fake, only that this tool could not confirm it.
  manual_review_required -- a situation this tool cannot confidently resolve
                             automatically (ambiguous name similarity, no
                             certificate number extracted, conflicting
                             extracted values, unparseable date)

Evidence-ladder mapping (see services.evidence_ladder's documented policy):
  verified / expired / mismatch_detected -> Rung 4 (matched an issuer
      record -- the strongest evidence this prototype can produce)
  source_unavailable / manual_review_required -> Rung 0 (no conclusive
      check could be completed). These can NEVER escalate priority alone.

Severity mapping (deliberately conservative):
  verified          -> low      (no concern)
  expired           -> medium   (matches evidence_ladder's documented P2 case)
  mismatch_detected -> high     (reproducible discrepancy vs a MATCHED
                                  record -- the only Module G outcome
                                  capable of reaching P1)
  source_unavailable-> low      (absence of information is not evidence)
  manual_review_required -> low (deliberately inconclusive)
"""
import json
from datetime import date, datetime, timezone

from rapidfuzz import fuzz
from dateutil import parser as dateutil_parser

from database.db import get_connection
from services.auth_service import require_role
from services import evidence_ladder
from utils import audit
from models.enums import Rung, VerificationStatus, DocType, IssuerType

ENGINE_NAME = "issuer_service"

# Illustrative demo thresholds only -- not calibrated, not official.
NAME_MISMATCH_THRESHOLD = 60   # similarity below this -> confident mismatch
NAME_VERIFIED_THRESHOLD = 90   # similarity at/above this -> confident match
# Between the two thresholds: inconclusive -> manual_review_required.

DOC_TYPE_TO_ISSUER_TYPE = {
    DocType.AFFILIATION_CERTIFICATE.value: IssuerType.AFFILIATION.value,
    DocType.FIRE_NOC.value: IssuerType.FIRE_NOC.value,
    DocType.ESTAMP.value: IssuerType.ESTAMP.value,
    # Other doc types (land_document, building_safety_certificate, other)
    # have no mock issuer registry in this prototype and are skipped.
}


def _parse_date(value):
    if not value:
        return None
    try:
        return dateutil_parser.parse(str(value), dayfirst=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


def _name_similarity(a, b) -> float:
    if not a or not b:
        return 0.0
    return fuzz.token_sort_ratio(str(a).strip().lower(), str(b).strip().lower())


def lookup_issuer_record(conn, issuer_type, certificate_number):
    row = conn.execute(
        "SELECT * FROM issuer_records WHERE issuer_type = ? AND certificate_number = ?",
        (issuer_type, certificate_number),
    ).fetchone()
    return dict(row) if row else None


def _get_distinct_field_values(conn, document_id, field_name):
    rows = conn.execute(
        """SELECT DISTINCT field_value FROM extracted_fields
           WHERE document_id = ? AND field_name = ?
             AND field_value IS NOT NULL AND TRIM(field_value) != ''""",
        (document_id, field_name),
    ).fetchall()
    return [r["field_value"] for r in rows]


def verify_certificate(conn, issuer_type, certificate_number, claimed_institution_name) -> dict:
    """Pure-ish lookup+comparison (reads issuer_records only; no writes).
    Returns {status, rung, severity, reason, matched_record}."""
    record = lookup_issuer_record(conn, issuer_type, certificate_number)

    if record is None:
        return {
            "status": VerificationStatus.SOURCE_UNAVAILABLE.value,
            "rung": Rung.UNVERIFIABLE.value,
            "severity": "low",
            "reason": (
                f"No record for certificate number '{certificate_number}' exists in the "
                f"mock {issuer_type} issuer database. This mock dataset is small and "
                f"intentionally incomplete -- absence here does NOT mean the certificate "
                f"is fake."
            ),
            "matched_record": None,
        }

    if not claimed_institution_name:
        return {
            "status": VerificationStatus.MANUAL_REVIEW.value,
            "rung": Rung.UNVERIFIABLE.value,
            "severity": "low",
            "reason": (
                "A matching certificate number was found in the mock issuer database, "
                "but no institution name could be extracted from the document to "
                "compare against it."
            ),
            "matched_record": dict(record),
        }

    similarity = _name_similarity(claimed_institution_name, record["institution_name"])

    if similarity < NAME_MISMATCH_THRESHOLD:
        return {
            "status": VerificationStatus.MISMATCH.value,
            "rung": Rung.VERIFIED_AT_SOURCE.value,
            "severity": "high",
            "reason": (
                f"Certificate number '{certificate_number}' is recorded in the mock "
                f"{issuer_type} issuer database under institution "
                f"'{record['institution_name']}', which does not match the institution "
                f"name claimed on this document ('{claimed_institution_name}')."
            ),
            "matched_record": dict(record),
        }

    if similarity < NAME_VERIFIED_THRESHOLD:
        return {
            "status": VerificationStatus.MANUAL_REVIEW.value,
            "rung": Rung.UNVERIFIABLE.value,
            "severity": "low",
            "reason": (
                f"Certificate number '{certificate_number}' matched a mock issuer "
                f"record, but the institution-name similarity ({similarity:.0f}%) is "
                f"too close to call automatically -- requires manual comparison."
            ),
            "matched_record": dict(record),
        }

    expiry = _parse_date(record.get("expiry_date"))
    if expiry is not None and expiry < date.today():
        return {
            "status": VerificationStatus.EXPIRED.value,
            "rung": Rung.VERIFIED_AT_SOURCE.value,
            "severity": "medium",
            "reason": (
                f"Certificate number '{certificate_number}' matched a mock issuer "
                f"record for '{record['institution_name']}', but its recorded expiry "
                f"date ({record['expiry_date']}) has passed."
            ),
            "matched_record": dict(record),
        }

    return {
        "status": VerificationStatus.VERIFIED.value,
        "rung": Rung.VERIFIED_AT_SOURCE.value,
        "severity": "low",
        "reason": (
            f"Certificate number '{certificate_number}' matched a mock issuer record "
            f"for '{record['institution_name']}' with no detected problems."
        ),
        "matched_record": dict(record),
    }


def _status_description(status):
    return {
        VerificationStatus.VERIFIED.value: "Certificate verified against the mock issuer database.",
        VerificationStatus.MISMATCH.value: "Certificate details do not match the mock issuer database record.",
        VerificationStatus.EXPIRED.value: "Certificate matched a mock issuer record, but it has expired.",
        VerificationStatus.SOURCE_UNAVAILABLE.value: "No matching record found in the mock issuer database.",
        VerificationStatus.MANUAL_REVIEW.value: "Automated issuer verification was inconclusive; manual review required.",
    }.get(status, "Unrecognised verification status.")


def _status_action(status):
    return {
        VerificationStatus.VERIFIED.value: "No action required from this check alone.",
        VerificationStatus.MISMATCH.value: "Treat as requiring urgent manual review; contact the claimed issuing authority if possible.",
        VerificationStatus.EXPIRED.value: "Request a current, unexpired certificate from the applicant.",
        VerificationStatus.SOURCE_UNAVAILABLE.value: "Treat as unverified by this tool; consider manual verification through the real issuing authority if required.",
        VerificationStatus.MANUAL_REVIEW.value: "An officer should manually compare the document against the applicant's other submissions and, if needed, the real issuing authority.",
    }.get(status, "Manually review this finding.")


def run_issuer_verification(actor, application_id):
    """Runs mock issuer verification for every document on an application
    whose doc_type has a corresponding mock issuer registry. Idempotent/
    rerun-safe: prior issuer_service findings and verification_requests
    for this application are replaced, not accumulated.

    Design simplification (disclosed): this prototype keeps only the
    latest verification result per application run. A production system
    might retain a full verification-request history instead.
    """
    require_role(actor, ("officer", "admin"))

    conn = get_connection()
    try:
        documents = [dict(r) for r in conn.execute(
            "SELECT * FROM documents WHERE application_id = ?", (application_id,)
        ).fetchall()]

        conn.execute(
            "DELETE FROM findings WHERE application_id = ? AND engine = ?",
            (application_id, ENGINE_NAME),
        )
        conn.execute(
            "DELETE FROM verification_requests WHERE application_id = ? AND source = ?",
            (application_id, ENGINE_NAME),
        )

        now = datetime.now(timezone.utc).isoformat()
        results = []

        for doc in documents:
            issuer_type = DOC_TYPE_TO_ISSUER_TYPE.get(doc["doc_type"])
            if issuer_type is None:
                continue  # no mock registry for this document type

            cert_values = _get_distinct_field_values(conn, doc["id"], "certificate_number")
            name_values = _get_distinct_field_values(conn, doc["id"], "institution_name")

            cur = conn.execute(
                """INSERT INTO verification_requests
                   (application_id, document_id, issuer_type, certificate_number,
                    status, source, requested_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (application_id, doc["id"], issuer_type,
                 cert_values[0] if len(cert_values) == 1 else None,
                 VerificationStatus.PENDING.value, ENGINE_NAME, now),
            )
            request_id = cur.lastrowid

            if len(cert_values) == 0:
                result = {
                    "status": VerificationStatus.MANUAL_REVIEW.value,
                    "rung": Rung.UNVERIFIABLE.value, "severity": "low",
                    "reason": ("No certificate number could be extracted from this "
                               "document to verify against the mock issuer database."),
                    "matched_record": None,
                }
            elif len(cert_values) > 1:
                result = {
                    "status": VerificationStatus.MANUAL_REVIEW.value,
                    "rung": Rung.UNVERIFIABLE.value, "severity": "low",
                    "reason": (f"Multiple conflicting certificate numbers were extracted "
                               f"from this document ({', '.join(cert_values)}); cannot "
                               f"determine which to verify automatically."),
                    "matched_record": None,
                }
            else:
                claimed_name = name_values[0] if len(name_values) == 1 else None
                result = verify_certificate(conn, issuer_type, cert_values[0], claimed_name)
                if len(name_values) > 1 and result["status"] == VerificationStatus.VERIFIED.value:
                    result = {
                        "status": VerificationStatus.MANUAL_REVIEW.value,
                        "rung": Rung.UNVERIFIABLE.value, "severity": "low",
                        "reason": ("Multiple conflicting institution names were extracted "
                                   "from this document; cannot automatically confirm the "
                                   "issuer match."),
                        "matched_record": result.get("matched_record"),
                    }

            responded_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE verification_requests SET status=?, responded_at=?, response_json=? WHERE id=?",
                (result["status"], responded_at, json.dumps({
                    "status": result["status"],
                    "reason": result["reason"],
                    "matched_record": result["matched_record"],
                }), request_id),
            )

            matched_name = (result["matched_record"] or {}).get("institution_name", "N/A") \
                if result["matched_record"] else "N/A"

            cur2 = conn.execute(
                """INSERT INTO findings (application_id, document_id, rule_id, engine,
                   severity, rung, status, description, reason, extracted_value,
                   expected_value, clause_ref, recommended_action, advisory, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (application_id, doc["id"], f"ISSUER-{result['status'].upper()}", ENGINE_NAME,
                 result["severity"], result["rung"], result["status"],
                 _status_description(result["status"]), result["reason"],
                 cert_values[0] if cert_values else "N/A", matched_name,
                 "N/A (synthetic mock-issuer lookup, not a rule-pack clause)",
                 _status_action(result["status"]), 1, now),
            )
            results.append({"document_id": doc["id"], "finding_id": cur2.lastrowid, **result})

        conn.commit()
        audit.append_entry(
            conn, actor=actor["username"], action="ISSUER_VERIFICATION_RUN",
            record_type="application", record_id=str(application_id),
            payload={"result_count": len(results)},
        )
        evidence_ladder.recompute_and_store_priority(conn, application_id, actor["username"])
        return results
    finally:
        conn.close()
def list_verification_requests(actor, application_id):
    """Read-only: lists all verification_requests rows for an application,
    most recent first, joined with each request's document type for
    display purposes. Officer/admin only -- this reveals verification
    outcomes, which is reviewer-facing information, same gating as
    running verification itself.
    """
    require_role(actor, ("officer", "admin"))
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT vr.*, d.doc_type AS document_doc_type
               FROM verification_requests vr
               JOIN documents d ON d.id = vr.document_id
               WHERE vr.application_id = ?
               ORDER BY vr.requested_at DESC""",
            (application_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def record_manual_verification_note(actor, verification_request_id, manual_notes, resolved_status=None):
    """Lets an officer/admin attach manual-review notes to a
    verification_requests row and, optionally, record a manually-resolved
    status (e.g. after contacting the issuing authority out-of-band, or
    manually comparing documents).

    This function NEVER fabricates an automated verification result -- it
    only records what a human officer attests to have done or found. If
    resolved_status is provided it must be one of the six recognised
    VerificationStatus values; this does not re-run any automated check.
    """
    require_role(actor, ("officer", "admin"))
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM verification_requests WHERE id = ?",
            (verification_request_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No verification request with id {verification_request_id}.")

        if resolved_status is not None:
            valid_statuses = {s.value for s in VerificationStatus}
            if resolved_status not in valid_statuses:
                raise ValueError(f"'{resolved_status}' is not a recognised verification status.")
            conn.execute(
                "UPDATE verification_requests SET manual_notes = ?, status = ? WHERE id = ?",
                (manual_notes, resolved_status, verification_request_id),
            )
        else:
            conn.execute(
                "UPDATE verification_requests SET manual_notes = ? WHERE id = ?",
                (manual_notes, verification_request_id),
            )
        conn.commit()

        audit.append_entry(
            conn, actor=actor["username"], action="ISSUER_MANUAL_NOTE_RECORDED",
            record_type="verification_request", record_id=str(verification_request_id),
            payload={"manual_notes": manual_notes, "resolved_status": resolved_status},
        )
        return True
    finally:
        conn.close()        