"""Module J (Phase 5): human review & decision workflow for individual
findings.

Officers record judgements against findings produced by the automated
engines (rule_engine, forensics_engine, issuer_service, qr_service).
This module NEVER overwrites or fabricates an automated
verification/rule result -- it only attaches a separate, clearly
attributed human decision (who, when, why) alongside it, stored in
findings.officer_decision / officer_remarks / decided_by / decided_at.

Binding project rules enforced here:
  * Only officers/admins may record a decision -- enforced in the
    backend via services.auth_service.require_role, not just by
    hiding UI controls.
  * Dismissing a finding is an adverse/consequential action and
    REQUIRES non-empty remarks.
  * Every decision is appended to the tamper-evident hash-chained
    audit log (utils.audit).
"""
from datetime import datetime, timezone

from database.db import get_connection
from services.auth_service import require_role
from utils import audit
from models.enums import FindingDecision, FINDING_DECISIONS_REQUIRING_REMARKS


def _get_finding_row(conn, finding_id):
    row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
    if row is None:
        raise ValueError(f"No finding with id {finding_id}.")
    return dict(row)


def record_finding_decision(actor, finding_id, decision, remarks=None):
    """Records an officer's decision against a single finding.

    `decision` must be one of models.enums.FindingDecision's values.
    Dismissing a finding requires non-empty remarks -- an adverse
    decision must always carry a documented human justification.

    Returns the updated finding row as a dict.
    """
    require_role(actor, ("officer", "admin"))

    valid_decisions = {d.value for d in FindingDecision}
    if decision not in valid_decisions:
        raise ValueError(f"'{decision}' is not a recognised finding decision.")

    remarks = (remarks or "").strip() or None
    if decision in FINDING_DECISIONS_REQUIRING_REMARKS and not remarks:
        raise ValueError(
            "Remarks are mandatory when dismissing a finding -- an adverse "
            "decision must always carry a documented justification."
        )

    conn = get_connection()
    try:
        finding = _get_finding_row(conn, finding_id)
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """UPDATE findings
               SET officer_decision = ?, officer_remarks = ?, decided_by = ?, decided_at = ?
               WHERE id = ?""",
            (decision, remarks, actor.get("id"), now, finding_id),
        )
        conn.commit()

        audit.append_entry(
            conn, actor=actor["username"], action="FINDING_DECISION_RECORDED",
            record_type="finding", record_id=str(finding_id),
            payload={
                "application_id": finding["application_id"],
                "rule_id": finding["rule_id"],
                "engine": finding["engine"],
                "decision": decision,
                "remarks": remarks,
            },
        )

        return _get_finding_row(conn, finding_id)
    finally:
        conn.close()


def get_decided_findings(actor, application_id):
    """Read-only: all findings for an application that already carry an
    officer decision, most recently decided first. Used to display
    'previous officer actions' in the review workbench."""
    require_role(actor, ("officer", "admin"))
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT f.*, u.username AS decided_by_username, u.full_name AS decided_by_name
               FROM findings f
               LEFT JOIN users u ON u.id = f.decided_by
               WHERE f.application_id = ? AND f.officer_decision IS NOT NULL
               ORDER BY f.decided_at DESC""",
            (application_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()