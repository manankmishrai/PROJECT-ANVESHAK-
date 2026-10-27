"""Module F (part 1): PDF digital-signature forensics using pyHanko,
where available.

Distinguishes (never collapses into one pass/fail result):
  - NO_SIGNATURE         : the PDF has no embedded digital signature.
  - VALID_TRUSTED        : signature intact AND certificate chain trusted.
  - VALID_UNTRUSTED_CHAIN: signature intact, but no trust roots are
                            configured in this prototype so chain trust
                            could not be established -- NOT the same as
                            "invalid".
  - INVALID              : cryptographic check shows signed content was
                            modified after signing, or the signature
                            fails to validate.
  - UNSUPPORTED          : the file could not be parsed for signature
                            verification (not a standard PDF, corrupted,
                            or uses an unsupported signature mechanism).
  - UNAVAILABLE          : pyHanko is not installed, or verification
                            could not run for an environmental reason.
                            Never silently treated as valid or invalid.

IMPORTANT: a valid, trusted digital signature proves the signed bytes
have not changed since signing and (if trust is configured) that the
certificate chains to a trusted root. It does NOT prove the factual
content of the document is true. This module never represents
otherwise, in code comments, findings text, or the UI.
"""
from pathlib import Path

from models.enums import SignatureCheckStatus as SigStatus, Rung

try:
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    PYHANKO_AVAILABLE = True
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - exercised only when pyhanko missing
    PYHANKO_AVAILABLE = False
    _IMPORT_ERROR = str(exc)

NO_SIGNATURE = SigStatus.NO_SIGNATURE.value
VALID_TRUSTED = SigStatus.VALID_TRUSTED.value
VALID_UNTRUSTED_CHAIN = SigStatus.VALID_UNTRUSTED_CHAIN.value
INVALID = SigStatus.INVALID.value
UNSUPPORTED = SigStatus.UNSUPPORTED.value
UNAVAILABLE = SigStatus.UNAVAILABLE.value


def inspect_signatures(pdf_path) -> dict:
    """Returns:
        {
          "status": one of the module-level constants above,
          "signature_count": int,
          "signatures": [ {signer_cn, intact, valid, trusted,
                            coverage, modification_detected}, ... ],
          "limitation": str|None,   # explicit human-readable caveat
        }

    Never raises -- an unsigned PDF, a PDF pyHanko cannot parse, a
    missing file, or pyHanko not being installed are all reported as a
    status, not an exception.
    """
    pdf_path = Path(pdf_path)

    if not PYHANKO_AVAILABLE:
        return {
            "status": UNAVAILABLE,
            "signature_count": 0,
            "signatures": [],
            "limitation": (
                "pyHanko is not installed in this environment, so PDF "
                "signature verification could not run. This is NOT the "
                "same as 'no signature' or 'invalid signature' -- the "
                f"check itself could not be attempted ({_IMPORT_ERROR})."
            ),
        }

    try:
        with open(pdf_path, "rb") as f:
            reader = PdfFileReader(f)
            embedded = list(getattr(reader, "embedded_signatures", []) or [])

            if not embedded:
                return {
                    "status": NO_SIGNATURE,
                    "signature_count": 0,
                    "signatures": [],
                    "limitation": None,
                }

            # No trust roots configured in this prototype -- we never
            # claim to validate against any real certificate authority.
            vc = ValidationContext(trust_roots=[], allow_fetching=False)

            sig_results = []
            any_invalid = False
            any_untrusted = False
            for emb_sig in embedded:
                entry = {
                    "signer_cn": None, "intact": None, "valid": None,
                    "trusted": None, "coverage": None,
                    "modification_detected": None,
                }
                try:
                    status = validate_pdf_signature(emb_sig, vc)
                    entry["intact"] = bool(getattr(status, "intact", False))
                    entry["valid"] = bool(getattr(status, "valid", False))
                    entry["trusted"] = bool(getattr(status, "trusted", False))
                    coverage = getattr(status, "coverage", None)
                    entry["coverage"] = str(coverage) if coverage is not None else None
                    mod_level = getattr(status, "modification_level", None)
                    entry["modification_detected"] = (
                        str(mod_level) not in (None, "NONE", "ModificationLevel.NONE")
                        if mod_level is not None else None
                    )
                    signer_cert = getattr(status, "signing_cert", None)
                    if signer_cert is not None:
                        entry["signer_cn"] = str(getattr(signer_cert, "subject", "")) or None

                    if not (entry["intact"] and entry["valid"]):
                        any_invalid = True
                    elif not entry["trusted"]:
                        any_untrusted = True
                except Exception as sig_exc:
                    entry["valid"] = None
                    entry["intact"] = None
                    entry["signer_cn"] = f"(error evaluating this signature: {sig_exc})"
                    any_invalid = True
                sig_results.append(entry)

            if any_invalid:
                overall, limitation = INVALID, None
            elif any_untrusted:
                overall = VALID_UNTRUSTED_CHAIN
                limitation = (
                    "Signature(s) are cryptographically intact, but no trust "
                    "roots are configured in this prototype, so certificate "
                    "chain trust could not be established. This is NOT the "
                    "same as an invalid signature."
                )
            else:
                overall, limitation = VALID_TRUSTED, None

            return {
                "status": overall,
                "signature_count": len(sig_results),
                "signatures": sig_results,
                "limitation": limitation,
            }
    except Exception as exc:
        return {
            "status": UNSUPPORTED,
            "signature_count": 0,
            "signatures": [],
            "limitation": (
                f"This file could not be parsed for signature verification "
                f"({exc}). It may use an unsupported PDF feature, be "
                f"corrupted, not exist, or not be a standard PDF."
            ),
        }


def rung_and_severity_for_signature_status(status: str):
    """Maps a signature status to (rung:int, severity:str). This is the
    single place that decides how strongly a signature result may ever
    influence priority escalation -- see services.evidence_ladder."""
    mapping = {
        NO_SIGNATURE: (Rung.UNVERIFIABLE.value, "low"),
        UNAVAILABLE: (Rung.UNVERIFIABLE.value, "low"),
        UNSUPPORTED: (Rung.UNVERIFIABLE.value, "low"),
        VALID_UNTRUSTED_CHAIN: (Rung.SIGNED_INTACT.value, "low"),
        VALID_TRUSTED: (Rung.SIGNED_INTACT.value, "low"),
        INVALID: (Rung.SIGNED_INTACT.value, "critical"),
    }
    return mapping.get(status, (Rung.UNVERIFIABLE.value, "low"))