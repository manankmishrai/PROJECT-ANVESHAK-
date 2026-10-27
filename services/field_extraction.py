"""Module C: heuristic field extraction from extracted page text.

Confidence scores here are a fixed, disclosed heuristic tied to direct
"Label: value" regex matching -- NOT a calibrated ML confidence score.
Phase 3+ may add fuzzy/cross-document corroboration.

Fields that cannot be found are simply absent from the returned list.
Callers MUST treat any missing field name as "not available" -- this
module never invents or guesses a value.
"""
import re

LABEL_MATCH_CONFIDENCE = 0.80
MAX_FIELD_VALUE_LENGTH = 200

FIELD_PATTERNS = {
    "institution_name": [
        r"(?:institution|college)\s*name\s*[:\-]\s*(.+)",
    ],
    "institution_id": [
        r"(?:institution\s*id|institution\s*code|aicte\s*id)\s*[:\-]\s*([A-Za-z0-9\-/]+)",
    ],
    "certificate_number": [
        r"certificate\s*(?:no\.?|number)\s*[:\-]\s*([A-Za-z0-9\-/]+)",
    ],
    "issuing_authority": [
        r"issu(?:ed|ing)\s*(?:by|authority)\s*[:\-]\s*(.+)",
    ],
    "issue_date": [
        r"(?:date\s*of\s*issue|issued\s*on|issue\s*date)\s*[:\-]\s*"
        r"([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})",
    ],
    "expiry_date": [
        r"(?:valid\s*until|valid\s*upto|expiry\s*date|date\s*of\s*expiry)\s*[:\-]\s*"
        r"([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})",
    ],
}


def _clean_value(raw: str) -> str:
    value = raw.strip().strip(".,;:")
    return value[:MAX_FIELD_VALUE_LENGTH]


def extract_fields_from_pages(pages_text: list) -> list:
    """
    Returns a list of dicts: {field_name, field_value, confidence, page_number},
    one entry per (field, page) match found. A field with no match
    anywhere is simply absent from the result.
    """
    results = []
    for page_index, text in enumerate(pages_text, start=1):
        if not text:
            continue
        for field_name, patterns in FIELD_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    value = _clean_value(match.group(1))
                    if not value:
                        continue
                    results.append({
                        "field_name": field_name,
                        "field_value": value,
                        "confidence": LABEL_MATCH_CONFIDENCE,
                        "page_number": page_index,
                    })
    return results