"""Module F (part 2): orchestrates per-document PDF forensics for an
application -- signature inspection (services.signature_service) and
lightweight PDF metadata inspection -- and persists the results as
findings, exactly like services.validation_engine does for Module D.

Scope note: hidden-text / rendered-content comparison ("does the
visible page match the underlying text layer") is NOT implemented in
this prototype -- flagged here honestly as a known gap, not silently
skipped. SHA-256 fingerprinting and duplicate-file detection were
already implemented in Phase 2/3 (services.pdf_service at upload time,
services.validation_engine's duplicate_file_hash rule) and are not
duplicated here.
"""
from datetime import datetime, timezone
from pathlib import Path

from database.db import get_connection
from services.auth_service import require_role
from services import signature_service, evidence_ladder
from utils import audit

ENGINE_NAME = "forensics_engine"


def inspect_metadata(pdf_path) -> dict:
    """Lightweight, honest PDF metadata inspection. Flags only one weak
    signal (possible incremental update after save, via multiple %%EOF
    markers) -- a common and often entirely legitimate occurrence, not
    inherently suspicious."""
    import fitz  # PyMuPDF
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    meta = doc.metadata or {}
    doc.close()
    with open(pdf_path, "rb") as f:
        raw = f.read()
    eof_count = raw.count(b"%%EOF")
    return {
        "producer": meta.get("producer"),
        "creator": meta.get("creator"),
        "author": meta.get("author"),
        "creation_date": meta.get("creationDate"),
        "mod_date": meta.get("modDate"),
        "eof_marker_count": eof_count,
        "possible_incremental_update": eof_count > 1,
    }


def _signature_finding_fields(sig_result: dict):
    status = sig_result["status"]
    rung, severity = signature_service.rung_and_severity_for_signature_status(status)

    S = signature_service
    if status == S.NO_SIGNATURE:
        description = "No digital signature was found on this document."
        reason = ("This document contains no embedded PDF digital signature. "
                   "Many legitimate documents (e.g. scanned paper certificates) "
                   "are never digitally signed -- absence alone is not evidence "
                   "of a problem.")
        extracted, expected = "no_signature", "N/A"
        action = ("If this document type is expected to be digitally signed "
                  "by its issuer, request a digitally signed copy.")
    elif status == S.UNAVAILABLE:
        description = "Signature verification could not be performed in this environment."
        reason = sig_result["limitation"]
        extracted, expected = "verification_unavailable", "a completed signature check"
        action = "Install/enable pyHanko to run signature verification, or treat authenticity as unverified by this tool."
    elif status == S.UNSUPPORTED:
        description = "This document could not be parsed for signature verification."
        reason = sig_result["limitation"]
        extracted, expected = "unsupported_format", "a parseable, standard PDF signature"
        action = "Manually inspect this document; automated signature verification was not possible."
    elif status == S.VALID_UNTRUSTED_CHAIN:
        description = "Digital signature is cryptographically intact, but certificate trust could not be established."
        reason = sig_result["limitation"]
        extracted, expected = "signature_valid_untrusted_chain", "a signature chaining to a configured trusted root"
        action = "No content tampering detected after signing. Configure a trust store if certificate-level trust is required."
    elif status == S.VALID_TRUSTED:
        description = "Digital signature is cryptographically intact and its certificate chain is trusted."
        reason = ("pyHanko confirmed the signed content has not changed since signing, "
                   "and the certificate chains to a configured trusted root. This does "
                   "NOT independently confirm the document's contents are factually accurate.")
        extracted, expected = "signature_valid_trusted", "N/A"
        action = "No action required for signature integrity; content accuracy must still be reviewed separately."
    elif status == S.INVALID:
        description = "Digital signature validation FAILED -- this document may have been modified after signing."
        reason = ("pyHanko detected that signed content does not match what was originally "
                   "signed, or the cryptographic signature itself does not validate. This is "
                   "a strong, reproducible technical finding.")
        extracted, expected = "signature_invalid", "a signature confirming unmodified content"
        action = ("Treat as requiring urgent manual review. This is strong technical evidence "
                   "of a problem, but a final determination of fraud still requires a human officer.")
    else:
        description, reason = "Unrecognised signature verification status.", str(sig_result)
        extracted, expected, action = status, "N/A", "Manually inspect this document."

    rule_id = f"SIG-{status.upper()}"
    return rule_id, severity, rung, description, reason, extracted, expected, action


def run_forensics(actor, application_id):
    """Runs signature + metadata forensics for every document on an
    application. Idempotent/rerun-safe: prior forensics_engine findings
    for this application are replaced, not accumulated, exactly like
    services.validation_engine.run_validation."""
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

        now = datetime.now(timezone.utc).isoformat()
        inserted_ids = []

        for doc in documents:
            path = Path(doc["stored_path"])
            if not path.exists():
                conn.execute(
                    """INSERT INTO findings (application_id, document_id, rule_id, engine,
                       severity, rung, status, description, reason, extracted_value,
                       expected_value, clause_ref, recommended_action, advisory, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (application_id, doc["id"], "FILE-MISSING", ENGINE_NAME, "low", 0,
                     "open", "Stored file could not be found on disk.",
                     "The database record for this document exists, but the file is "
                     "missing from storage, so no forensic checks could run.",
                     "file_not_found", "a readable file on disk",
                     "N/A (storage integrity check, not a rule-pack clause)",
                     "Re-upload this document.", 1, now),
                )
                continue

            sig_result = signature_service.inspect_signatures(path)
            rule_id, severity, rung, description, reason, extracted, expected, action = \
                _signature_finding_fields(sig_result)
            cur = conn.execute(
                """INSERT INTO findings (application_id, document_id, rule_id, engine,
                   severity, rung, status, description, reason, extracted_value,
                   expected_value, clause_ref, recommended_action, advisory, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (application_id, doc["id"], rule_id, ENGINE_NAME, severity, rung, "open",
                 description, reason, extracted, expected,
                 "N/A (technical forensic check, not a rule-pack clause)", action, 1, now),
            )
            inserted_ids.append(cur.lastrowid)

            try:
                meta = inspect_metadata(path)
            except Exception as exc:
                meta = None
                conn.execute(
                    """INSERT INTO findings (application_id, document_id, rule_id, engine,
                       severity, rung, status, description, reason, extracted_value,
                       expected_value, clause_ref, recommended_action, advisory, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (application_id, doc["id"], "META-UNAVAILABLE", ENGINE_NAME, "low", 0,
                     "open", "PDF metadata could not be inspected.", str(exc),
                     "metadata_unavailable", "readable PDF metadata",
                     "N/A", "Manually inspect this document if needed.", 1, now),
                )

            if meta and meta["possible_incremental_update"]:
                cur2 = conn.execute(
                    """INSERT INTO findings (application_id, document_id, rule_id, engine,
                       severity, rung, status, description, reason, extracted_value,
                       expected_value, clause_ref, recommended_action, advisory, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (application_id, doc["id"], "META-INCREMENTAL-UPDATE", ENGINE_NAME,
                     "low", 1, "open",
                     "This PDF appears to have been incrementally updated/re-saved after creation.",
                     f"Found {meta['eof_marker_count']} end-of-file markers in the raw file, "
                     "which can indicate the file was saved more than once. This is common and "
                     "often entirely legitimate (e.g. form filling, adding a signature) -- it is "
                     "not inherently suspicious on its own.",
                     str(meta["eof_marker_count"]), "a single end-of-file marker",
                     "N/A", "Consider in combination with other findings; not conclusive alone.",
                     1, now),
                )
                inserted_ids.append(cur2.lastrowid)

        conn.commit()
        audit.append_entry(
            conn, actor=actor["username"], action="FORENSICS_RUN",
            record_type="application", record_id=str(application_id),
            payload={"finding_count": len(inserted_ids),
                     "pyhanko_available": signature_service.PYHANKO_AVAILABLE},
        )
        evidence_ladder.recompute_and_store_priority(conn, application_id, actor["username"])
        return inserted_ids
    finally:
        conn.close()