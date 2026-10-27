"""Upload validation and path-traversal-safe filename handling.

Covers the Module B/C security requirements: file type checking, size
limits, and safe storage paths that cannot escape the configured
upload directory regardless of what a client sends as a filename.
"""
import re
import uuid
from pathlib import Path

from utils.config import MAX_UPLOAD_MB, UPLOAD_DIR

ALLOWED_EXTENSIONS = {".pdf"}
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


class UploadValidationError(ValueError):
    """Raised for any rejected upload. Subclasses ValueError so existing
    callers that catch ValueError still work without modification."""
    pass


def validate_upload(original_filename: str, file_bytes: bytes) -> None:
    """Raises UploadValidationError with a human-readable reason if the
    upload should be rejected. Never silently accepts something unsafe."""
    if not original_filename:
        raise UploadValidationError("Uploaded file has no filename.")

    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            f"Unsupported file type '{suffix or '(none)'}'. Only PDF files are accepted."
        )

    if not file_bytes:
        raise UploadValidationError("Uploaded file is empty.")

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise UploadValidationError(
            f"File exceeds the maximum allowed size of {MAX_UPLOAD_MB} MB."
        )

    if not file_bytes.startswith(b"%PDF-"):
        raise UploadValidationError(
            "File does not appear to be a valid PDF (missing %PDF header)."
        )


def safe_filename(original_filename: str) -> str:
    """Strips any directory components and unsafe characters, and
    prefixes a random token so concurrent/duplicate uploads never
    collide or silently overwrite each other on disk.

    `Path(original_filename).name` discards everything before the final
    path separator, which neutralises `../../etc/passwd.pdf`-style
    traversal attempts at the filename level.
    """
    base_name = Path(original_filename).name
    base_name = base_name.replace("\x00", "")
    stem = Path(base_name).stem[:80]
    suffix = Path(base_name).suffix.lower()
    stem = _UNSAFE_CHARS.sub("_", stem) or "file"
    token = uuid.uuid4().hex[:12]
    return f"{token}_{stem}{suffix}"


def build_storage_path(application_code: str, safe_name: str) -> Path:
    """Builds a storage path under UPLOAD_DIR/<application_code>/<safe_name>,
    then defensively verifies the resolved path is still inside
    UPLOAD_DIR -- defense in depth in case anything upstream of this
    function is ever changed in a way that reintroduces traversal risk.
    """
    app_folder = _UNSAFE_CHARS.sub("_", application_code) or "unknown_application"
    upload_root = UPLOAD_DIR.resolve()
    target_dir = (upload_root / app_folder).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = (target_dir / safe_name).resolve()
    if not target_path.is_relative_to(upload_root):
        raise UploadValidationError("Resolved storage path escapes the upload directory.")

    return target_path