"""Module E: Evidence-Ladder core -- rung semantics and the documented,
binding escalation policy that converts an application's findings into
a review-priority tier.

THE LADDER (see models.enums.Rung for the canonical values):
    Rung 4 -- VERIFIED_AT_SOURCE : matched against an authoritative
                                    issuer record. In THIS PROTOTYPE
                                    that source is always the local
                                    MOCK issuer service -- never a real
                                    government database.
    Rung 3 -- SIGNED_INTACT      : a completed cryptographic PDF
                                    signature check (pyHanko), whether
                                    the result was valid or invalid.
    Rung 2 -- CONSISTENT         : a completed deterministic
                                    cross-check between two values
                                    found within the submission itself
                                    (e.g. QR-encoded value vs printed
                                    value), whether they agreed or not.
    Rung 1 -- ANOMALY            : a heuristic, text/field-extraction
                                    based flag (Phase 3 rule engine).
                                    Advisory only.
    Rung 0 -- UNVERIFIABLE       : no check could be completed (tool
                                    unavailable, source unreachable,
                                    nothing applicable to check).

BINDING ESCALATION POLICY (do not weaken this without also updating
this docstring and the README):

  1. A finding's rung records how strong/reproducible the *method* was,
     never whether the AI/extractor was "confident". Confidence scores
     are never used to raise a rung.

  2. Only findings that reached rung >= 2 via a genuine deterministic,
     reproducible check (a direct internal cross-check, a cryptographic
     signature check, or a mock-issuer source lookup) can contribute to
     priority above the routine tier.

  3. Rung 0 and Rung 1 findings -- including every Phase 3 rule-engine
     finding -- can NEVER, alone or in combination with any number of
     other Rung 0/1 findings, push an application to the highest
     priority tier (P1). At most they contribute to P3.

  4. Reaching P1 strictly requires at least one finding at rung >= 3
     (a completed cryptographic check or a mock-issuer-source result)
     that is also flagged high/critical severity.

  5. No automated process ever sets a finding or application to
     "confirmed forged". Priority only indicates review urgency for a
     human officer. Final adverse decisions always require a human
     (Module J, implemented in Phase 5).
"""
from models.enums import Rung
from utils import audit

ADVERSE_SEVERITIES = ("high", "critical")

RUNG_SOURCE_LABELS = {
    Rung.UNVERIFIABLE: "No completed check / source unavailable",
    Rung.ANOMALY: "Heuristic text/field-extraction rule (Module D, Phase 3)",
    Rung.CONSISTENT: "Deterministic internal cross-check (e.g. QR vs printed value)",
    Rung.SIGNED_INTACT: "Cryptographic PDF signature check (pyHanko, Module F)",
    Rung.VERIFIED_AT_SOURCE: "Mock issuer-record lookup (SYNTHETIC -- not a real government service)",
}


def evidence_source_label(rung_value):
    """Human-readable description of *what kind* of check produced a
    finding at a given rung, for display in the UI."""
    try:
        return RUNG_SOURCE_LABELS[Rung(rung_value)]
    except (ValueError, KeyError):
        return "Unknown"


def _is_adverse(finding):
    return (finding.get("severity") or "").lower() in ADVERSE_SEVERITIES


def compute_priority(findings):
    """Pure function (no DB access) implementing the escalation policy
    above. `findings` is a list of dicts, each with at least an int
    'rung' and a str 'severity' key. Returns one of 'P1'..'P4'.

    Deliberately simple and auditable rather than a weighted score --
    each tier is reachable only through an explicit, documented
    condition, never by accumulating weak signals.
    """
    if not findings:
        return "P4"

    strong_adverse = [
        f for f in findings
        if f.get("rung", 0) >= Rung.SIGNED_INTACT.value and _is_adverse(f)
    ]
    if strong_adverse:
        return "P1"

    consistent_adverse = [
        f for f in findings
        if f.get("rung", 0) == Rung.CONSISTENT.value and _is_adverse(f)
    ]
    at_source_medium = [
        f for f in findings
        if f.get("rung", 0) >= Rung.SIGNED_INTACT.value
        and (f.get("severity") or "").lower() == "medium"
    ]
    if consistent_adverse or at_source_medium:
        return "P2"

    any_notable = [
        f for f in findings
        if _is_adverse(f) or (f.get("severity") or "").lower() == "medium"
    ]
    if any_notable:
        return "P3"

    return "P4"


def recompute_and_store_priority(conn, application_id, actor_username="system"):
    """Reads every current finding for an application, recomputes its
    priority tier, and persists it if changed. Safe to call repeatedly
    (idempotent) -- intended to be called at the end of every
    verification engine run (rule engine, forensics engine, issuer
    engine, QR engine) so priority always reflects the latest evidence.
    """
    rows = conn.execute(
        "SELECT rung, severity FROM findings WHERE application_id = ?",
        (application_id,),
    ).fetchall()
    findings = [dict(r) for r in rows]
    new_priority = compute_priority(findings)

    current = conn.execute(
        "SELECT priority FROM applications WHERE id = ?", (application_id,)
    ).fetchone()
    if current is None:
        return new_priority

    if current["priority"] != new_priority:
        conn.execute(
            "UPDATE applications SET priority = ? WHERE id = ?",
            (new_priority, application_id),
        )
        conn.commit()
        audit.append_entry(
            conn, actor=actor_username, action="PRIORITY_RECOMPUTED",
            record_type="application", record_id=str(application_id),
            payload={
                "old_priority": current["priority"],
                "new_priority": new_priority,
                "finding_count": len(findings),
            },
        )
    return new_priority