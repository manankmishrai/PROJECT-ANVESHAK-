"""Module E: pure-logic tests for the documented escalation policy.
No database involved -- compute_priority() takes plain dicts."""
from services.evidence_ladder import compute_priority
from models.enums import Rung


def test_no_findings_is_routine():
    assert compute_priority([]) == "P4"


def test_many_rung1_critical_findings_never_reach_p1():
    findings = [{"rung": Rung.ANOMALY.value, "severity": "critical"} for _ in range(20)]
    assert compute_priority(findings) == "P3"


def test_rung0_findings_never_escalate():
    findings = [{"rung": Rung.UNVERIFIABLE.value, "severity": "critical"} for _ in range(5)]
    assert compute_priority(findings) == "P3"


def test_rung3_adverse_reaches_p1():
    findings = [{"rung": Rung.SIGNED_INTACT.value, "severity": "critical"}]
    assert compute_priority(findings) == "P1"


def test_rung4_adverse_reaches_p1():
    findings = [{"rung": Rung.VERIFIED_AT_SOURCE.value, "severity": "high"}]
    assert compute_priority(findings) == "P1"


def test_rung3_clean_result_does_not_escalate():
    # a VALID signature (low severity) must not raise priority
    findings = [{"rung": Rung.SIGNED_INTACT.value, "severity": "low"}]
    assert compute_priority(findings) == "P4"


def test_rung2_adverse_reaches_p2_not_p1():
    findings = [{"rung": Rung.CONSISTENT.value, "severity": "high"}]
    assert compute_priority(findings) == "P2"


def test_rung4_medium_expiry_reaches_p2():
    findings = [{"rung": Rung.VERIFIED_AT_SOURCE.value, "severity": "medium"}]
    assert compute_priority(findings) == "P2"


def test_mixed_findings_take_highest_qualifying_tier():
    findings = [
        {"rung": Rung.ANOMALY.value, "severity": "critical"},
        {"rung": Rung.SIGNED_INTACT.value, "severity": "critical"},
    ]
    assert compute_priority(findings) == "P1"


def test_rung2_mismatch_cannot_be_forced_to_p1_by_quantity():
    findings = [{"rung": Rung.CONSISTENT.value, "severity": "critical"} for _ in range(50)]
    assert compute_priority(findings) == "P2"