import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]

APP_NAME = os.getenv("APP_NAME", "Evidence-Ladder Scrutiny Copilot")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))

# Phase 2: where uploaded PDFs are stored on disk, outside the repo's
# tracked source tree. Created automatically on first upload.
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(ROOT_DIR / "uploads")))

# Phase 2 OCR fallback (optional). If unset, pytesseract uses whatever
# "tesseract" resolves to on PATH. If the Tesseract binary is not
# installed at all, services/pdf_service.py degrades gracefully instead
# of crashing.
TESSERACT_CMD = os.getenv("TESSERACT_CMD")

# Phase 6: hard cap on PDF page count accepted for text/QR extraction.
# This is a disclosed, deliberately simple resource-exhaustion defence
# for this prototype -- NOT a general-purpose DoS mitigation. A
# maliciously crafted PDF could still be expensive to parse per-page;
# this only bounds the number of pages processed.
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "100"))