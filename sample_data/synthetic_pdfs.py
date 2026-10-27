"""Generates small, clearly-labelled synthetic demo PDFs using
PyMuPDF, used to seed demonstration applications (Module K).

These are NOT real certificates and contain no real institution or
government data. Every generated page carries a visible synthetic-data
banner.

Dates used in these documents are computed RELATIVE to the real date
at the time this module runs (via dateutil.relativedelta), not hardcoded
calendar years. This is a deliberate correction: an earlier version used
fixed years like "2023"/"2026", which silently drifted into producing an
incorrectly "expired" result for the clean demo scenario once enough
real time had passed. Computing dates relative to "today" means the
demo's intended outcomes (valid vs. expired) remain correct indefinitely.

Phase 7 (Section C) addition: 8 further synthetic scenarios covering
institution-name mismatch, duplicate certificate numbers, conflicting
certificate numbers within one document, duplicate uploaded files,
an issuer record that does not exist (source unavailable), an issuer
record under the wrong institution name, and a QR-code replay
demonstration. The QR replay scenario requires the optional `qrcode`
library to actually embed a scannable QR image; if it is not
installed, the same documents are generated without QR images and the
PDF text says so explicitly -- this prototype never silently
fabricates or skips a check without saying so.
"""
from datetime import date
from pathlib import Path

import pymupdf
from dateutil.relativedelta import relativedelta

GENERATED_DIR = Path(__file__).resolve().parent / "generated"

SYNTHETIC_BANNER = "SYNTHETIC DEMONSTRATION DOCUMENT -- NOT A REAL CERTIFICATE"

_TODAY = date.today()

try:
    import qrcode
    QRCODE_AVAILABLE = True
except Exception:
    QRCODE_AVAILABLE = False


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


# "Valid" certificates: issued 2 years ago, expiring 2 years from now --
# comfortably within validity regardless of when this demo is run.
_VALID_ISSUE = _fmt(_TODAY - relativedelta(years=2))
_VALID_EXPIRY = _fmt(_TODAY + relativedelta(years=2))

# "Expired" certificate (National's affiliation -- the deliberate
# expired_certificate demo scenario): issued 7 years ago, expired 3
# years ago. This stays robustly, unambiguously expired far into the
# future, rather than drifting back to "valid" or ambiguous.
_EXPIRED_ISSUE = _fmt(_TODAY - relativedelta(years=7))
_EXPIRED_EXPIRY = _fmt(_TODAY - relativedelta(years=3))


def _write_pdf(filename: str, lines: list) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / filename

    doc = pymupdf.open()
    page = doc.new_page()
    y = 50
    page.insert_text((50, y), SYNTHETIC_BANNER, fontsize=10, color=(0.7, 0, 0))
    y += 30
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 22
    doc.save(str(path))
    doc.close()
    return path


def _write_pdf_with_qr(filename: str, lines: list, qr_payload: str) -> Path:
    """Like _write_pdf, but also embeds a QR code image encoding
    qr_payload, IF the optional `qrcode` library is installed in this
    environment. If not, the document is still generated (with all its
    text lines) but without a QR image, and an explicit note is printed
    on the page saying so -- never silently skipped without disclosure.
    """
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / filename

    doc = pymupdf.open()
    page = doc.new_page()
    y = 50
    page.insert_text((50, y), SYNTHETIC_BANNER, fontsize=10, color=(0.7, 0, 0))
    y += 30
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 22

    y += 10
    if QRCODE_AVAILABLE:
        import io
        img = qrcode.make(qr_payload)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page.insert_image(pymupdf.Rect(50, y, 200, y + 150), stream=buf.getvalue())
        y += 160
        page.insert_text(
            (50, y), "QR code embedded (synthetic demonstration).",
            fontsize=9, color=(0, 0, 0.6),
        )
    else:
        page.insert_text(
            (50, y),
            "QR code NOT embedded -- 'qrcode' library is not installed "
            "in this environment. This is a disclosed limitation, not a "
            "fabricated result.",
            fontsize=9, color=(0.5, 0.5, 0.5),
        )

    doc.save(str(path))
    doc.close()
    return path


def generate_all() -> dict:
    """Generates (or overwrites) the fixed set of synthetic demo PDFs.
    Returns {logical_name: Path}."""
    files = {}

    # ------------------------------------------------------------------
    # Scenario 1: complete_consistent -- Shree Institute of Technology
    # ------------------------------------------------------------------
    files["shree_affiliation"] = _write_pdf(
        "shree_affiliation_certificate.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Shree Institute of Technology",
            "Institution ID: INST-001",
            "Certificate No: CERT-AFF-2023-0001",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["shree_fire_noc"] = _write_pdf(
        "shree_fire_noc.pdf",
        [
            "Fire NOC (SYNTHETIC)",
            "Institution Name: Shree Institute of Technology",
            "Institution ID: INST-001",
            "Certificate No: CERT-NOC-2023-0007",
            "Issued By: Synthetic Fire Department (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["shree_estamp"] = _write_pdf(
        "shree_estamp.pdf",
        [
            "E-Stamp Certificate (SYNTHETIC)",
            "Institution Name: Shree Institute of Technology",
            "Institution ID: INST-001",
            "Certificate No: ESTAMP-2023-0099",
            "Issued By: Synthetic e-Stamping Authority (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    # ------------------------------------------------------------------
    # Scenario 2: missing_document -- Bharat College of Engineering
    # ------------------------------------------------------------------
    files["bharat_affiliation"] = _write_pdf(
        "bharat_affiliation_certificate.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Bharat College of Engineering",
            "Institution ID: INST-002",
            "Certificate No: CERT-AFF-2022-0045",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    # Fire NOC intentionally NOT generated -- demonstrates "missing
    # mandatory document".

    # ------------------------------------------------------------------
    # Scenario 3: expired_certificate -- National Polytechnic Institute
    # ------------------------------------------------------------------
    files["national_affiliation_expired"] = _write_pdf(
        "national_affiliation_certificate_expired.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: National Polytechnic Institute",
            "Institution ID: INST-003",
            "Certificate No: CERT-AFF-2019-0012",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_EXPIRED_ISSUE}",
            f"Valid Until: {_EXPIRED_EXPIRY}",
        ],
    )
    files["national_fire_noc"] = _write_pdf(
        "national_fire_noc.pdf",
        [
            "Fire NOC (SYNTHETIC)",
            "Institution Name: National Polytechnic Institute",
            "Institution ID: INST-003",
            "Certificate No: CERT-NOC-2023-0051",
            "Issued By: Synthetic Fire Department (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["national_estamp"] = _write_pdf(
        "national_estamp.pdf",
        [
            "E-Stamp Certificate (SYNTHETIC)",
            "Institution Name: National Polytechnic Institute",
            "Institution ID: INST-003",
            "Certificate No: ESTAMP-2023-0150",
            "Issued By: Synthetic e-Stamping Authority (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    # ------------------------------------------------------------------
    # Scenario 4 (Phase 7): complete_consistent_2 -- Vindhya College
    # ------------------------------------------------------------------
    files["vindhya_affiliation"] = _write_pdf(
        "vindhya_affiliation_certificate.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Vindhya College of Engineering",
            "Institution ID: INST-004",
            "Certificate No: CERT-AFF-2024-0201",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["vindhya_fire_noc"] = _write_pdf(
        "vindhya_fire_noc.pdf",
        [
            "Fire NOC (SYNTHETIC)",
            "Institution Name: Vindhya College of Engineering",
            "Institution ID: INST-004",
            "Certificate No: CERT-NOC-2024-0202",
            "Issued By: Synthetic Fire Department (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["vindhya_estamp"] = _write_pdf(
        "vindhya_estamp.pdf",
        [
            "E-Stamp Certificate (SYNTHETIC)",
            "Institution Name: Vindhya College of Engineering",
            "Institution ID: INST-004",
            "Certificate No: ESTAMP-2024-0203",
            "Issued By: Synthetic e-Stamping Authority (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    # ------------------------------------------------------------------
    # Scenario 5 (Phase 7): institution_name_mismatch -- Vikas Engineering
    # College. Institution ID lines deliberately omitted so this
    # scenario isolates to RULE-005 (name mismatch) only.
    # ------------------------------------------------------------------
    files["vikas_affiliation"] = _write_pdf(
        "vikas_affiliation_certificate.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Vikas Engineering College",
            "Certificate No: CERT-AFF-2024-0301",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["vikas_fire_noc_mismatch"] = _write_pdf(
        "vikas_fire_noc_mismatch.pdf",
        [
            "Fire NOC (SYNTHETIC)",
            "Institution Name: Shakti Institute of Management",
            "Certificate No: CERT-NOC-2024-0302",
            "Issued By: Synthetic Fire Department (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    # ------------------------------------------------------------------
    # Scenario 6 (Phase 7): duplicate_certificate_number -- Deccan
    # Institute of Science. Reuses Shree's exact affiliation certificate
    # number deliberately. Fire NOC and e-stamp are clean so the
    # scenario is isolated to this one defect at the validation_engine
    # layer (issuer_service will also independently flag a mismatch --
    # see comment in seed.py).
    # ------------------------------------------------------------------
    files["deccan_affiliation_dup"] = _write_pdf(
        "deccan_affiliation_certificate_duplicate.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Deccan Institute of Science",
            "Institution ID: INST-006",
            "Certificate No: CERT-AFF-2023-0001",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["deccan_fire_noc"] = _write_pdf(
        "deccan_fire_noc.pdf",
        [
            "Fire NOC (SYNTHETIC)",
            "Institution Name: Deccan Institute of Science",
            "Institution ID: INST-006",
            "Certificate No: CERT-NOC-DEC-0001",
            "Issued By: Synthetic Fire Department (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["deccan_estamp"] = _write_pdf(
        "deccan_estamp.pdf",
        [
            "E-Stamp Certificate (SYNTHETIC)",
            "Institution Name: Deccan Institute of Science",
            "Institution ID: INST-006",
            "Certificate No: ESTAMP-DEC-0001",
            "Issued By: Synthetic e-Stamping Authority (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    # ------------------------------------------------------------------
    # Scenario 7 (Phase 7): conflicting_certificate_in_document -- Ganga
    # Valley Institute. The affiliation certificate itself contains two
    # different "Certificate No:" lines. Fire NOC and e-stamp are clean.
    # ------------------------------------------------------------------
    files["gangavalley_affiliation_conflict"] = _write_pdf(
        "gangavalley_affiliation_certificate_conflicting.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Ganga Valley Institute",
            "Institution ID: INST-007",
            "Certificate No: CERT-GV-0001",
            "Issued By: Synthetic State Technical Board (DEMO)",
            "Certificate No: CERT-GV-9999",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["gangavalley_fire_noc"] = _write_pdf(
        "gangavalley_fire_noc.pdf",
        [
            "Fire NOC (SYNTHETIC)",
            "Institution Name: Ganga Valley Institute",
            "Institution ID: INST-007",
            "Certificate No: CERT-GV-FN-0001",
            "Issued By: Synthetic Fire Department (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["gangavalley_estamp"] = _write_pdf(
        "gangavalley_estamp.pdf",
        [
            "E-Stamp Certificate (SYNTHETIC)",
            "Institution Name: Ganga Valley Institute",
            "Institution ID: INST-007",
            "Certificate No: ESTAMP-GV-0001",
            "Issued By: Synthetic e-Stamping Authority (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    # ------------------------------------------------------------------
    # Scenario 8 (Phase 7): duplicate_uploaded_file -- Himalayan College
    # of Engineering. ONE file is generated and uploaded twice (under two
    # different doc_types) by seed.py -- only the e-stamp is a separate
    # file, so the checklist is fully satisfied and the scenario isolates
    # to RULE-009.
    # ------------------------------------------------------------------
    files["himalayan_shared"] = _write_pdf(
        "himalayan_affiliation_certificate.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Himalayan College of Engineering",
            "Institution ID: INST-008",
            "Certificate No: CERT-HCE-0001",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["himalayan_estamp"] = _write_pdf(
        "himalayan_estamp.pdf",
        [
            "E-Stamp Certificate (SYNTHETIC)",
            "Institution Name: Himalayan College of Engineering",
            "Institution ID: INST-008",
            "Certificate No: ESTAMP-HCE-0001",
            "Issued By: Synthetic e-Stamping Authority (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    # ------------------------------------------------------------------
    # Scenario 9 (Phase 7): issuer_record_unavailable -- Coastal
    # Polytechnic. All three documents are internally clean/consistent;
    # only the affiliation certificate's number has no matching issuer
    # record at all, isolating the scenario to SOURCE_UNAVAILABLE.
    # ------------------------------------------------------------------
    files["coastal_affiliation_isolated"] = _write_pdf(
        "coastal_affiliation_certificate.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Coastal Polytechnic",
            "Institution ID: INST-009",
            "Certificate No: CERT-AFF-CP-0001",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["coastal_fire_noc"] = _write_pdf(
        "coastal_fire_noc.pdf",
        [
            "Fire NOC (SYNTHETIC)",
            "Institution Name: Coastal Polytechnic",
            "Institution ID: INST-009",
            "Certificate No: CERT-NOC-CP-0001",
            "Issued By: Synthetic Fire Department (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["coastal_estamp"] = _write_pdf(
        "coastal_estamp.pdf",
        [
            "E-Stamp Certificate (SYNTHETIC)",
            "Institution Name: Coastal Polytechnic",
            "Institution ID: INST-009",
            "Certificate No: ESTAMP-CP-0001",
            "Issued By: Synthetic e-Stamping Authority (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    # ------------------------------------------------------------------
    # Scenario 10 (Phase 7): issuer_institution_mismatch -- Meridian
    # Institute of Technology. All three documents are internally
    # clean/consistent; only the affiliation certificate's issuer record
    # exists under a different institution name.
    # ------------------------------------------------------------------
    files["meridian_affiliation_mismatch"] = _write_pdf(
        "meridian_affiliation_certificate.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Meridian Institute of Technology",
            "Institution ID: INST-010",
            "Certificate No: CERT-AFF-MIT-0001",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["meridian_fire_noc"] = _write_pdf(
        "meridian_fire_noc.pdf",
        [
            "Fire NOC (SYNTHETIC)",
            "Institution Name: Meridian Institute of Technology",
            "Institution ID: INST-010",
            "Certificate No: CERT-NOC-MIT-0002",
            "Issued By: Synthetic Fire Department (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )
    files["meridian_estamp"] = _write_pdf(
        "meridian_estamp.pdf",
        [
            "E-Stamp Certificate (SYNTHETIC)",
            "Institution Name: Meridian Institute of Technology",
            "Institution ID: INST-010",
            "Certificate No: ESTAMP-MIT-0003",
            "Issued By: Synthetic e-Stamping Authority (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    # ------------------------------------------------------------------
    # Scenario 11 (Phase 7): qr_replay_demo -- Sundarbans College of
    # Technology. The fire NOC embeds a QR code that is byte-identical
    # (same decoded payload) to the affiliation certificate's QR code,
    # but prints a DIFFERENT certificate number -- a QR reused across
    # two differently-claimed certificates. Requires the optional
    # `qrcode` library; degrades gracefully (no QR images, explicitly
    # disclosed on the page) if unavailable.
    # ------------------------------------------------------------------
    _sbc_qr_payload = (
        "https://verify.mock-issuer.test/verify"
        "?issuer_type=affiliation&certificate_number=CERT-SBC-0001"
    )
    files["sundarbans_affiliation_qr"] = _write_pdf_with_qr(
        "sundarbans_affiliation_certificate_qr.pdf",
        [
            "Affiliation Certificate (SYNTHETIC)",
            "Institution Name: Sundarbans College of Technology",
            "Institution ID: INST-011",
            "Certificate No: CERT-SBC-0001",
            "Issued By: Synthetic State Technical Board (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
        qr_payload=_sbc_qr_payload,
    )
    files["sundarbans_fire_noc_qr_replay"] = _write_pdf_with_qr(
        "sundarbans_fire_noc_qr_replay.pdf",
        [
            "Fire NOC (SYNTHETIC)",
            "Institution Name: Sundarbans College of Technology",
            "Institution ID: INST-011",
            "Certificate No: CERT-SBC-0002",
            "Issued By: Synthetic Fire Department (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
        qr_payload=_sbc_qr_payload,  # deliberately the SAME payload as above
    )
    files["sundarbans_estamp"] = _write_pdf(
        "sundarbans_estamp.pdf",
        [
            "E-Stamp Certificate (SYNTHETIC)",
            "Institution Name: Sundarbans College of Technology",
            "Institution ID: INST-011",
            "Certificate No: ESTAMP-SBC-0003",
            "Issued By: Synthetic e-Stamping Authority (DEMO)",
            f"Date of Issue: {_VALID_ISSUE}",
            f"Valid Until: {_VALID_EXPIRY}",
        ],
    )

    return files