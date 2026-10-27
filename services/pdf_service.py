"""Module C: PDF text extraction.

Strategy: always try native (embedded) text extraction first via
PyMuPDF. If a page has very little extractable text (a strong signal
it is a scanned image rather than a native PDF), attempt OCR via
Tesseract. If OCR dependencies (pytesseract/Pillow) or the Tesseract
binary itself are not installed, this degrades to a clear, honest
"OCR unavailable" status instead of crashing or fabricating text.

Nothing here ever invents extracted content. If no text can be
recovered, that is reported truthfully via extraction_status.
"""
import hashlib
import io

import pymupdf

from utils.config import TESSERACT_CMD, MAX_PDF_PAGES

# Heuristic threshold to decide "this page is probably a scanned image,
# not native text" -- not a regulatory or scientifically calibrated value.
MIN_CHARS_PER_PAGE_FOR_NATIVE = 20

_OCR_IMPORT_ERROR = None
try:
    import pytesseract
    from PIL import Image

    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    OCR_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised only when OCR libs absent
    OCR_AVAILABLE = False
    _OCR_IMPORT_ERROR = str(exc)


def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _open_pdf(file_bytes: bytes):
    try:
        return pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"File could not be opened as a PDF: {exc}") from exc


def get_page_count(file_bytes: bytes) -> int:
    doc = _open_pdf(file_bytes)
    try:
        return doc.page_count
    finally:
        doc.close()


def _native_text_per_page(doc) -> list:
    return [page.get_text("text") or "" for page in doc]


def _attempt_ocr(doc):
    """Returns (pages_text, status, warning). Never raises -- any OCR
    failure degrades to a clear warning rather than crashing the app."""
    if not OCR_AVAILABLE:
        return None, "ocr_unavailable", (
            "This document appears to be scanned or image-only and has very "
            "little extractable native text. OCR is not installed in this "
            "environment (pytesseract/Pillow and/or the Tesseract binary are "
            "missing), so text could not be recovered. Install Tesseract OCR "
            "and the pytesseract/Pillow Python packages, then re-upload, to "
            f"enable OCR extraction. (detail: {_OCR_IMPORT_ERROR})"
        )

    try:
        pages_text = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(img)
            pages_text.append(text or "")
        return pages_text, "ocr", None
    except Exception as exc:  # pragma: no cover - depends on local Tesseract install
        return None, "ocr_failed", (
            f"OCR was attempted but failed: {exc}. The Tesseract binary may "
            "not be installed or not on PATH (see TESSERACT_CMD in .env)."
        )


def extract_document_text(file_bytes: bytes) -> dict:
    """
    Returns a dict:
      page_count: int
      pages_text: list[str]       (one entry per page; '' if nothing extracted)
      is_native_text: bool        (True if usable native text was found)
      ocr_used: bool
      extraction_status: one of
          'native' | 'ocr' | 'ocr_unavailable' | 'ocr_failed' | 'empty'
      warning: str | None

    Raises ValueError if the file is not a readable PDF at all, OR if it
    exceeds this prototype's configured page-count processing limit
    (MAX_PDF_PAGES -- Phase 6 security hardening against pathological
    files). A well-formed PDF within that limit with no readable text is
    NOT an error -- it is reported honestly via extraction_status instead.
    """
    doc = _open_pdf(file_bytes)
    try:
        page_count = doc.page_count

        if page_count > MAX_PDF_PAGES:
            raise ValueError(
                f"This PDF has {page_count} pages, which exceeds this "
                f"prototype's processing limit of {MAX_PDF_PAGES} pages. "
                f"This is a deliberate, disclosed safeguard against "
                f"excessive CPU/memory use from pathological files -- it is "
                f"not an assessment of this document's legitimacy. Split "
                f"the document into smaller parts, or ask an administrator "
                f"to raise MAX_PDF_PAGES, if a larger file is genuinely "
                f"required."
            )

        native_pages = _native_text_per_page(doc)
        total_chars = sum(len(p.strip()) for p in native_pages)
        avg_chars = total_chars / max(page_count, 1)

        if avg_chars >= MIN_CHARS_PER_PAGE_FOR_NATIVE:
            return {
                "page_count": page_count,
                "pages_text": native_pages,
                "is_native_text": True,
                "ocr_used": False,
                "extraction_status": "native",
                "warning": None,
            }

        ocr_pages, ocr_status, warning = _attempt_ocr(doc)
        if ocr_pages is not None:
            return {
                "page_count": page_count,
                "pages_text": ocr_pages,
                "is_native_text": False,
                "ocr_used": True,
                "extraction_status": ocr_status,
                "warning": warning,
            }

        # OCR unavailable or failed: fall back to whatever native text
        # exists (possibly none at all), reported honestly.
        extraction_status = ocr_status if total_chars == 0 else "native"
        return {
            "page_count": page_count,
            "pages_text": native_pages,
            "is_native_text": total_chars > 0,
            "ocr_used": False,
            "extraction_status": extraction_status,
            "warning": warning,
        }
    finally:
        doc.close()