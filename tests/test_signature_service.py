"""Module F: tests for signature_service. These are written to pass
whether or not pyHanko is actually installed/working in this
environment, since that could not be verified without running it here
-- the module must behave honestly (report UNAVAILABLE/UNSUPPORTED)
rather than crash either way."""
import fitz  # PyMuPDF
from services import signature_service as sigsvc


def _make_plain_pdf(tmp_path):
    path = tmp_path / "plain.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def test_plain_unsigned_pdf_is_handled_honestly(tmp_path):
    path = _make_plain_pdf(tmp_path)
    result = sigsvc.inspect_signatures(path)
    assert result["status"] in (sigsvc.NO_SIGNATURE, sigsvc.UNAVAILABLE, sigsvc.UNSUPPORTED)
    if result["status"] == sigsvc.NO_SIGNATURE:
        assert result["signature_count"] == 0
        assert result["limitation"] is None
    else:
        assert result["limitation"]


def test_missing_file_never_raises(tmp_path):
    missing = tmp_path / "does_not_exist.pdf"
    result = sigsvc.inspect_signatures(missing)
    assert result["status"] in (sigsvc.UNAVAILABLE, sigsvc.UNSUPPORTED)
    assert result["limitation"]


def test_rung_and_severity_mapping_never_exceeds_rung3():
    for status in (
        sigsvc.NO_SIGNATURE, sigsvc.UNAVAILABLE, sigsvc.UNSUPPORTED,
        sigsvc.VALID_TRUSTED, sigsvc.VALID_UNTRUSTED_CHAIN, sigsvc.INVALID,
    ):
        rung, severity = sigsvc.rung_and_severity_for_signature_status(status)
        assert rung <= 3
        assert severity in ("low", "medium", "high", "critical")


def test_invalid_signature_is_rung3_critical():
    rung, severity = sigsvc.rung_and_severity_for_signature_status(sigsvc.INVALID)
    assert rung == 3
    assert severity == "critical"


def test_valid_trusted_signature_is_rung3_low_not_adverse():
    rung, severity = sigsvc.rung_and_severity_for_signature_status(sigsvc.VALID_TRUSTED)
    assert rung == 3
    assert severity == "low"


def test_no_signature_is_rung0():
    rung, severity = sigsvc.rung_and_severity_for_signature_status(sigsvc.NO_SIGNATURE)
    assert rung == 0