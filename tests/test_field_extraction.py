"""Tests for Module C: heuristic field extraction (never fabricates values)."""
from services.field_extraction import extract_fields_from_pages


def test_extracts_known_fields():
    pages = [
        "Institution Name: Shree Institute of Technology\n"
        "Certificate No: CERT-2023-0001\n"
        "Date of Issue: 01-06-2023\n"
        "Valid Until: 31-05-2026\n"
    ]
    fields = extract_fields_from_pages(pages)
    names = {f["field_name"] for f in fields}
    assert "institution_name" in names
    assert "certificate_number" in names
    assert "issue_date" in names
    assert "expiry_date" in names


def test_missing_fields_are_simply_absent():
    pages = ["This page has no recognisable labelled fields at all."]
    fields = extract_fields_from_pages(pages)
    assert fields == []


def test_field_values_are_not_fabricated_beyond_match():
    pages = ["Certificate No: XYZ-999"]
    fields = extract_fields_from_pages(pages)
    assert len(fields) == 1
    assert fields[0]["field_value"] == "XYZ-999"