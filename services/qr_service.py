"""Module D (Phase 4 addition): QR code extraction and verification.

Extracts QR codes embedded as images in uploaded PDF pages, decodes their
payload, and -- ONLY if the payload's host is on an explicit allowlist --
treats the payload as a reference for mock issuer-record lookup
(services.issuer_service's record store). This module NEVER fetches,
opens, or follows any URL found in an uploaded document; it only parses
strings already decoded locally from a QR image.

QR replay detection: the same QR *payload* (the exact string decoded from
the QR image) appearing on two different documents that claim different
certificate numbers is flagged as a strong, reproducible technical
finding -- it means a QR image was copied from one certificate onto a
document claiming to be a different certificate.

Evidence-ladder mapping: both the QR-vs-printed consistency check and QR
replay detection are Rung 2 ("internally consistent" -- a completed
deterministic cross-check between concrete extracted values), never Rung
3/4, since no cryptographic signature or external verified source is
involved. Per the documented escalation policy this means QR findings
alone can reach at most P2, never P1.

Known limitations (disclose in README):
  - QR decoding depends on the optional `pyzbar` library (and Pillow),
    which in turn depends on a native zbar library. If unavailable, every
    QR check reports an explicit QR-UNAVAILABLE finding rather than
    silently skipping or guessing.
  - "Allowlisted host" only means "recognised format for mock
    issuer-record lookup" -- it does NOT mean the host is trusted,
    fetched, or contacted. No network request is ever made by this
    module.
  - Page-count capping (Phase 6): rendering every PDF page to an image to
    search for QR codes is comparatively expensive. This module caps
    itself to MAX_PDF_PAGES as a second, independent safeguard -- the
    primary enforcement point is upload time in services.pdf_service.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from database.db import get_connection
from services.auth_service import require_role
from services import evidence_ladder
from utils import audit
from utils.config import MAX_PDF_PAGES
from models.enums import Rung, VerificationStatus

ENGINE_NAME = "qr_service"

# Synthetic, demo-only hostname. Not a real government or AICTE domain.
ALLOWLISTED_HOSTS = {"verify.mock-issuer.test"}

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    from PIL import Image
    QR_DECODE_AVAILABLE = True
except Exception:
    QR_DECODE_AVAILABLE = False


def extract_qr_payloads_from_pdf(pdf_path, dpi=200):
    """Renders each page of the PDF to an image and attempts to decode any
    QR codes present. Returns a list of {page_number, payload} dicts, one
    per QR code found. Never raises; returns [] if decoding is
    unavailable or the file cannot be processed.

    Capped at MAX_PDF_PAGES pages (Phase 6 hardening, defense in depth --
    see module docstring) rather than processing an unbounded number of
    pages.
    """
    if not QR_DECODE_AVAILABLE:
        return []
    import fitz  # PyMuPDF
    results = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return []
    try:
        page_limit = min(len(doc), MAX_PDF_PAGES)
        for page_index in range(page_limit):
            page = doc[page_index]
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            for d in pyzbar_decode(img):
                try:
                    payload = d.data.decode("utf-8", errors="replace")
                except Exception:
                    payload = repr(d.data)
                results.append({"page_number": page_index + 1, "payload": payload})
    finally:
        doc.close()
    return results


def extract_qr_payloads_from_bytes(pdf_bytes, dpi=200):
    """Bytes-based convenience wrapper around extract_qr_payloads_from_pdf,
    for callers (e.g. the upload page) that only have in-memory PDF bytes
    rather than a path to a file already on disk.

    Writes the bytes to a private temporary file, delegates entirely to
    extract_qr_payloads_from_pdf (so page-count capping, decoder
    availability handling, and error handling are identical to the
    path-based entry point), and always removes the temporary file
    afterwards regardless of outcome. Never raises; returns [] on any
    failure, consistent with extract_qr_payloads_from_pdf's contract.
    """
    import tempfile
    import os

    if not QR_DECODE_AVAILABLE:
        return []

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pdf_bytes)
        return extract_qr_payloads_from_pdf(tmp_path, dpi=dpi)
    except Exception:
        return []
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def parse_qr_payload(payload):
    """Parses a decoded QR string as a URL. Returns None if it is not a
    well-formed http(s) URL at all. Otherwise returns a dict describing
    whether the host is allowlisted and, if so, the parsed query
    parameters. NEVER makes a network request."""
    try:
        parsed = urlparse(payload)
    except Exception:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.hostname not in ALLOWLISTED_HOSTS:
        return {"host_allowlisted": False, "host": parsed.hostname}
    params = parse_qs(parsed.query)
    return {
        "host_allowlisted": True,
        "host": parsed.hostname,
        "issuer_type": (params.get("issuer_type") or [None])[0],
        "certificate_number": (params.get("certificate_number") or [None])[0],
    }


def _first_or_none(conn, document_id, field_name):
    row = conn.execute(
        "SELECT field_value FROM extracted_fields WHERE document_id = ? AND field_name = ? LIMIT 1",
        (document_id, field_name),
    ).fetchone()
    return row["field_value"] if row else None


def _detect_qr_replay(conn, application_id, now):
    """Finds QR payloads on this application's documents that are
    byte-identical to a QR payload on a DIFFERENT document anywhere in the
    system whose own printed certificate number differs -- i.e. the same
    QR image appears to have been reused across two differently-claimed
    certificates."""
    this_app_rows = [dict(r) for r in conn.execute(
        """SELECT ef.document_id, ef.field_value AS payload
           FROM extracted_fields ef
           JOIN documents d ON d.id = ef.document_id
           WHERE d.application_id = ? AND ef.field_name = 'qr_payload'""",
        (application_id,),
    ).fetchall()]

    inserted = []
    seen_payloads = set()
    for row in this_app_rows:
        payload = row["payload"]
        if payload in seen_payloads:
            continue
        seen_payloads.add(payload)

        other_docs = [dict(r) for r in conn.execute(
            """SELECT ef.document_id, d.application_id
               FROM extracted_fields ef
               JOIN documents d ON d.id = ef.document_id
               WHERE ef.field_name = 'qr_payload' AND ef.field_value = ?
                 AND ef.document_id != ?""",
            (payload, row["document_id"]),
        ).fetchall()]
        if not other_docs:
            continue

        this_cert = _first_or_none(conn, row["document_id"], "certificate_number")
        for other in other_docs:
            other_cert = _first_or_none(conn, other["document_id"], "certificate_number")
            if this_cert and other_cert and this_cert.strip().lower() != other_cert.strip().lower():
                cur = conn.execute(
                    """INSERT INTO findings (application_id, document_id, rule_id, engine,
                       severity, rung, status, description, reason, extracted_value,
                       expected_value, clause_ref, recommended_action, advisory, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (application_id, row["document_id"], "QR-REPLAY-DETECTED", ENGINE_NAME,
                     "high", Rung.CONSISTENT.value, VerificationStatus.MISMATCH.value,
                     "QR code reuse detected across documents claiming different certificate numbers.",
                     (f"This document's QR code is identical to a QR code found on document "
                      f"id {other['document_id']} (application id {other['application_id']}), "
                      f"but that document claims certificate number '{other_cert}' while this "
                      f"one claims '{this_cert}'. A legitimate QR code should not be shared "
                      f"between two different certificates."),
                     this_cert, other_cert,
                     "N/A (synthetic QR replay cross-check, not a rule-pack clause)",
                     ("Treat as requiring urgent manual review -- this is a strong, "
                      "reproducible indicator of QR reuse/tampering, but confirmation "
                      "still requires a human officer."),
                     1, now),
                )
                inserted.append(cur.lastrowid)
    return inserted


def run_qr_verification(actor, application_id):
    """Runs QR extraction + verification for every document on an
    application. Idempotent/rerun-safe for findings (prior qr_service
    findings for this application are replaced, not accumulated)."""
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
                continue  # FILE-MISSING already reported by forensics_engine

            if not QR_DECODE_AVAILABLE:
                cur = conn.execute(
                    """INSERT INTO findings (application_id, document_id, rule_id, engine,
                       severity, rung, status, description, reason, extracted_value,
                       expected_value, clause_ref, recommended_action, advisory, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (application_id, doc["id"], "QR-UNAVAILABLE", ENGINE_NAME, "low", 0, "open",
                     "QR code verification could not run in this environment.",
                     "The optional pyzbar/Pillow QR-decoding dependency is not installed or failed to import.",
                     "qr_decode_unavailable", "a working QR decoder", "N/A",
                     "Install pyzbar/Pillow to enable QR verification, or inspect any QR codes manually.",
                     1, now),
                )
                inserted_ids.append(cur.lastrowid)
                continue

            # Clear stale qr_payload rows for this document only now that
            # we are actually about to re-extract.
            conn.execute(
                "DELETE FROM extracted_fields WHERE document_id = ? AND field_name = 'qr_payload'",
                (doc["id"],),
            )
            qr_hits = extract_qr_payloads_from_pdf(path)
            if not qr_hits:
                continue  # no QR found -- not inherently suspicious, no finding

            for hit in qr_hits:
                conn.execute(
                    """INSERT INTO extracted_fields (document_id, field_name, field_value, confidence, page_number)
                       VALUES (?,?,?,?,?)""",
                    (doc["id"], "qr_payload", hit["payload"], 1.0, hit["page_number"]),
                )

            parsed = parse_qr_payload(qr_hits[0]["payload"])
            printed_cert = _first_or_none(conn, doc["id"], "certificate_number")

            if parsed is None:
                description = "A QR code was found but its content is not a recognisable URL."
                reason = f"Decoded QR payload: {qr_hits[0]['payload'][:200]!r}"
                rung, severity, status = Rung.UNVERIFIABLE.value, "low", VerificationStatus.MANUAL_REVIEW.value
                action = "Manually inspect this QR code if relevant."
            elif not parsed["host_allowlisted"]:
                description = "A QR code was found, but it points to a host not on this prototype's verification allowlist."
                reason = (f"QR destination host '{parsed['host']}' is not in the allowlist "
                          f"{sorted(ALLOWLISTED_HOSTS)}. This tool NEVER automatically visits "
                          f"URLs found in uploaded documents.")
                rung, severity, status = Rung.UNVERIFIABLE.value, "low", VerificationStatus.MANUAL_REVIEW.value
                action = "If verification against this issuer is required, do so manually and separately -- this tool will not fetch the URL."
            else:
                qr_cert = parsed.get("certificate_number")
                if not qr_cert:
                    description = "QR code resolved to an allowlisted host, but no certificate number could be parsed from it."
                    reason = f"Decoded QR payload: {qr_hits[0]['payload'][:200]!r}"
                    rung, severity, status = Rung.UNVERIFIABLE.value, "low", VerificationStatus.MANUAL_REVIEW.value
                    action = "Manually inspect this QR code."
                elif printed_cert is None:
                    description = "QR-encoded certificate number could not be compared -- no printed certificate number was extracted from this document."
                    reason = f"QR encodes certificate number '{qr_cert}'; no comparable printed value was found."
                    rung, severity, status = Rung.UNVERIFIABLE.value, "low", VerificationStatus.MANUAL_REVIEW.value
                    action = "Manually compare the QR-encoded value against the printed document."
                elif qr_cert.strip().lower() == printed_cert.strip().lower():
                    description = "QR-encoded certificate number matches the printed certificate number on this document."
                    reason = f"Both QR and printed text give certificate number '{printed_cert}'."
                    rung, severity, status = Rung.CONSISTENT.value, "low", VerificationStatus.VERIFIED.value
                    action = "No action required from this check alone."
                else:
                    description = "QR-encoded certificate number does NOT match the printed certificate number on this document."
                    reason = (f"QR code encodes certificate number '{qr_cert}', but the "
                              f"document's printed/extracted certificate number is "
                              f"'{printed_cert}'.")
                    rung, severity, status = Rung.CONSISTENT.value, "high", VerificationStatus.MISMATCH.value
                    action = "Treat as requiring urgent manual review -- a QR code and its document's printed details should always agree."

            cur = conn.execute(
                """INSERT INTO findings (application_id, document_id, rule_id, engine,
                   severity, rung, status, description, reason, extracted_value,
                   expected_value, clause_ref, recommended_action, advisory, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (application_id, doc["id"], f"QR-{status.upper()}", ENGINE_NAME, severity, rung,
                 status, description, reason, qr_hits[0]["payload"][:200], printed_cert or "N/A",
                 "N/A (synthetic QR cross-check, not a rule-pack clause)", action, 1, now),
            )
            inserted_ids.append(cur.lastrowid)

        inserted_ids.extend(_detect_qr_replay(conn, application_id, now))

        conn.commit()
        audit.append_entry(
            conn, actor=actor["username"], action="QR_VERIFICATION_RUN",
            record_type="application", record_id=str(application_id),
            payload={"finding_count": len(inserted_ids), "qr_decode_available": QR_DECODE_AVAILABLE},
        )
        evidence_ladder.recompute_and_store_priority(conn, application_id, actor["username"])
        return inserted_ids
    finally:
        conn.close()