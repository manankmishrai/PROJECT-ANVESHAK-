"""Shared enums for findings, evidence rungs, verification statuses,
application lifecycle, document classification, rule-engine rule
types/severities (Phase 3), issuer types and PDF signature check
statuses (Phase 4), and officer decision workflow (Phase 5).

Defined early so later phases (D, E, F, G) do not require restructuring
service code.
"""
from enum import IntEnum, Enum


class Rung(IntEnum):
    UNVERIFIABLE = 0
    ANOMALY = 1
    CONSISTENT = 2
    SIGNED_INTACT = 3
    VERIFIED_AT_SOURCE = 4


RUNG_LABELS = {
    Rung.UNVERIFIABLE: "Rung 0 -- Unverifiable or source unavailable",
    Rung.ANOMALY: "Rung 1 -- Anomaly flagged (advisory only)",
    Rung.CONSISTENT: "Rung 2 -- Internally consistent",
    Rung.SIGNED_INTACT: "Rung 3 -- Cryptographically intact",
    Rung.VERIFIED_AT_SOURCE: "Rung 4 -- Verified at source",
}


class VerificationStatus(str, Enum):
    PENDING = "verification_pending"
    VERIFIED = "verified"
    MISMATCH = "mismatch_detected"
    EXPIRED = "expired"
    SOURCE_UNAVAILABLE = "source_unavailable"
    MANUAL_REVIEW = "manual_review_required"


class Role(str, Enum):
    APPLICANT = "applicant"
    OFFICER = "officer"
    ADMIN = "admin"


# ---------------------------------------------------------------------
# Phase 2 additions (Module B: application intake)
# ---------------------------------------------------------------------

class ApplicationStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    DECISION_RECORDED = "decision_recorded"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApplicationCategory(str, Enum):
    # Only Extension of Approval is implemented in this prototype.
    EOA = "EoA"


class DocType(str, Enum):
    AFFILIATION_CERTIFICATE = "affiliation_certificate"
    FIRE_NOC = "fire_noc"
    ESTAMP = "e_stamp"
    LAND_DOCUMENT = "land_document"
    BUILDING_SAFETY_CERTIFICATE = "building_safety_certificate"
    OTHER = "other"


# IMPORTANT: this is an illustrative/demonstration checklist only, used
# to exercise the application-intake workflow end to end. It is NOT an
# authoritative AICTE/APH document requirement list. A verified official
# checklist must replace this before any real regulatory use.
DEFAULT_CHECKLIST_BY_CATEGORY = {
    ApplicationCategory.EOA.value: [
        DocType.AFFILIATION_CERTIFICATE.value,
        DocType.FIRE_NOC.value,
        DocType.ESTAMP.value,
    ],
}


# ---------------------------------------------------------------------
# Phase 3 additions (Module D: deterministic validation rules engine)
# ---------------------------------------------------------------------

class RuleType(str, Enum):
    """Fixed set of supported deterministic rule behaviours. A YAML rule
    pack may only reference these values -- rule_pack_loader rejects
    any rule_type not in this enum, so a rule pack file can never cause
    arbitrary code execution."""
    MISSING_REQUIRED_DOCUMENT = "missing_required_document"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    EXPIRED_CERTIFICATE = "expired_certificate"
    INVALID_DATE_RANGE = "invalid_date_range"
    CROSS_DOCUMENT_FIELD_MISMATCH = "cross_document_field_mismatch"
    DUPLICATE_CERTIFICATE_NUMBER = "duplicate_certificate_number"
    CONFLICTING_FIELD_VALUES = "conflicting_field_values"
    DUPLICATE_FILE_HASH = "duplicate_file_hash"
    MISSING_SIGNATURE_INFO = "missing_signature_info"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(str, Enum):
    OPEN = "open"
    # NOTE: officer decisions (confirm/dismiss/etc.) are NOT modelled as
    # additional values of this enum. They are recorded in a separate
    # column (findings.officer_decision) via models.enums.FindingDecision
    # below (Phase 5), so the original automated `status` value produced
    # by rule_engine / forensics_engine / issuer_service / qr_service is
    # never overwritten or lost when an officer acts on a finding.


# ---------------------------------------------------------------------
# Phase 4 additions (Module F: PDF signature forensics, Module G: mock
# issuer verification)
# ---------------------------------------------------------------------

class IssuerType(str, Enum):
    """The synthetic/mock issuer record categories supported by the
    local mock issuer service. NOT connected to any real government
    or institutional database."""
    ESTAMP = "estamp"
    FIRE_NOC = "fire_noc"
    AFFILIATION = "affiliation"


class SignatureCheckStatus(str, Enum):
    """Possible outcomes of a PDF digital-signature inspection. These
    are deliberately distinct from each other -- 'missing', 'invalid',
    'untrusted chain', and 'could not check' must never be collapsed
    into a single pass/fail result."""
    NO_SIGNATURE = "no_signature"
    VALID_TRUSTED = "signature_valid_trusted"
    VALID_UNTRUSTED_CHAIN = "signature_valid_untrusted_chain"
    INVALID = "signature_invalid"
    UNSUPPORTED = "unsupported_format"
    UNAVAILABLE = "verification_unavailable"


# ---------------------------------------------------------------------
# Phase 5 additions (Module J: human review & decision workflow)
# ---------------------------------------------------------------------

class FindingDecision(str, Enum):
    """Officer actions recordable against an individual finding.

    Stored in findings.officer_decision -- this NEVER overwrites the
    underlying deterministic/verification `status` column produced by
    an automated engine, so the original automated result is always
    preserved alongside the officer's judgement.
    """
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    EVIDENCE_REQUESTED = "evidence_requested"
    MANUAL_VERIFICATION_ASSIGNED = "manual_verification_assigned"
    FURTHER_REVIEW_REQUIRED = "further_review_required"


# Decisions that MUST be accompanied by non-empty officer remarks, per
# the binding project rule that adverse/consequential actions always
# require a documented human justification.
FINDING_DECISIONS_REQUIRING_REMARKS = {FindingDecision.DISMISSED.value}

# Application-level final decisions that MUST be accompanied by
# non-empty officer remarks.
APPLICATION_DECISIONS_REQUIRING_REMARKS = {ApplicationStatus.REJECTED.value}