"""Tests for upload validation and path-traversal-safe filenames."""
import pytest

from utils.file_safety import (
    validate_upload, safe_filename, build_storage_path, UploadValidationError,
)


def test_rejects_non_pdf_extension():
    with pytest.raises(UploadValidationError):
        validate_upload("not_a_pdf.exe", b"%PDF-1.4 fake")


def test_rejects_empty_file():
    with pytest.raises(UploadValidationError):
        validate_upload("empty.pdf", b"")


def test_rejects_missing_pdf_header():
    with pytest.raises(UploadValidationError):
        validate_upload("fake.pdf", b"not really a pdf")


def test_accepts_valid_looking_pdf():
    validate_upload("certificate.pdf", b"%PDF-1.4 ... rest of file ...")


def test_safe_filename_strips_path_traversal():
    name = safe_filename("../../etc/passwd.pdf")
    assert "/" not in name
    assert ".." not in name
    assert name.endswith(".pdf")


def test_safe_filename_sanitises_unsafe_characters():
    name = safe_filename("weird name!@#.pdf")
    assert " " not in name
    assert "!" not in name


def test_build_storage_path_stays_inside_upload_dir(tmp_path, monkeypatch):
    import utils.file_safety as fs_module
    monkeypatch.setattr(fs_module, "UPLOAD_DIR", tmp_path)

    path = fs_module.build_storage_path("APP-2025-ABC123", "token_certificate.pdf")
    assert tmp_path.resolve() in path.parents