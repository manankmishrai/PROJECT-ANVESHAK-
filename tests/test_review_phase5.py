"""Tests for Phase 5 (Module J): per-finding officer decisions,
application-level officer decisions, mandatory-remarks enforcement,
RBAC restrictions, database persistence, and audit-chain integrity.

Reuses the existing wired-fixture pattern from test_validation_engine.py
to produce REAL findings via the real validation engine, rather than
hand-inserting finding rows against a schema we have not independently
re-verified column-by-column for NOT NULL / foreign-key constraints in
this session.

Actor dicts deliberately follow the exact precedent set by
test_application_service.py / test_validation_engine.py: they do NOT
include an "id" key. created_by/decided_by therefore end up NULL in
these tests (actor.get("id") is None), which avoids any foreign-key
violation against the (deliberately unseeded, empty) users table in
temp_db. In real production use, actor dicts always come from an
authenticated row in `users`, so decided_by/created_by correctly
reference a real user id there -- this is a test-fixture simplification,
not a production behaviour gap.

Scope note: LOGIN/LOGOUT audit events (added in app.py) are not covered
here, consistent with the existing test suite's convention of not
importing/testing app.py or any Streamlit page module directly.
"""
import pymupdf
import pytest

from services.auth_service import PermissionDenied
from utils.audit import verify_chain

REAL_RULE_PACK_PATH = "rules/eoa_illustrative_v1.yaml"

ADMIN_ACTOR = {"username": "admin", "role": "admin", "institution_id": None}
OFFICER_ACTOR = {"username": "officer1", "role": "officer", "institution_id": None}
APPLICANT_ACTOR = {"username": "applicant1", "role": "applicant", "institution_id": None}


def _make_pdf_bytes(lines):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 50
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 20
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture()
def wired(temp_db, monkeypatch, tmp_path):
    import services.application_service as app_module
    import services.validation_engine as ve_module
    import services.rule_pack_loader as loader_module
    import services.review_service as review_module
    import utils.file_safety as fs_module

    monkeypatch.setattr(app_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(ve_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(loader_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(review_module, "get_connection", temp_db.get_connection)
    monkeypatch.setattr(fs_module, "UPLOAD_DIR", tmp_path / "uploads")

    return {"app": app_module, "ve": ve_module, "review": review_module}


def _create_application_with_findings(wired):
    """Creates an application with one uploaded document deliberately
    missing all recognisable labelled fields, runs the real validation
    engine, and returns (application_id, findings) with at least one
    real finding (RULE-002: missing required field) to exercise
    review_service against."""
    app_mod, ve_mod = wired["app"], wired["ve"]
    inst_id = app_mod.get_or_create_institution("Workbench Institute", "INST-WB")
    app_id = app_mod.create_application(ADMIN_ACTOR, inst_id, "EoA", "2025-26", "2025-06-01")

    pdf_bytes = _make_pdf_bytes(["This document has no recognisable labelled fields at all."])
    app_mod.add_document(ADMIN_ACTOR, app_id, "affiliation_certificate", "vague.pdf", pdf_bytes)

    ve_mod.run_validation(ADMIN_ACTOR, app_id, REAL_RULE_PACK_PATH)
    findings = ve_mod.list_findings(ADMIN_ACTOR, application_id=app_id)
    assert findings, "expected at least one finding to exercise review_service against"
    return app_id, findings


# ---------------------------------------------------------------------
# Per-finding decisions: RBAC, validation, mandatory remarks
# ---------------------------------------------------------------------

def test_record_finding_decision_requires_officer_or_admin(wired):
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]
    with pytest.raises(PermissionDenied):
        wired["review"].record_finding_decision(APPLICANT_ACTOR, finding_id, "confirmed")


def test_record_finding_decision_rejects_invalid_decision_value(wired):
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]
    with pytest.raises(ValueError):
        wired["review"].record_finding_decision(OFFICER_ACTOR, finding_id, "not_a_real_decision")


def test_record_finding_decision_unknown_finding_raises(wired):
    with pytest.raises(ValueError):
        wired["review"].record_finding_decision(OFFICER_ACTOR, 999999, "confirmed")


def test_dismiss_finding_without_remarks_is_rejected(wired):
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]
    with pytest.raises(ValueError):
        wired["review"].record_finding_decision(OFFICER_ACTOR, finding_id, "dismissed")
    with pytest.raises(ValueError):
        wired["review"].record_finding_decision(OFFICER_ACTOR, finding_id, "dismissed", remarks="   ")


def test_dismiss_finding_with_remarks_persists(wired):
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]

    updated = wired["review"].record_finding_decision(
        OFFICER_ACTOR, finding_id, "dismissed", remarks="Verified manually against source register."
    )

    assert updated["officer_decision"] == "dismissed"
    assert updated["officer_remarks"] == "Verified manually against source register."
    assert updated["decided_at"] is not None

    # Confirm persistence is real (fresh read through list_findings), not
    # just an artefact of the returned dict.
    refetched = wired["ve"].list_findings(ADMIN_ACTOR, application_id=app_id)
    this_finding = next(f for f in refetched if f["id"] == finding_id)
    assert this_finding["officer_decision"] == "dismissed"
    assert this_finding["officer_remarks"] == "Verified manually against source register."


def test_confirm_finding_without_remarks_succeeds(wired):
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]

    updated = wired["review"].record_finding_decision(OFFICER_ACTOR, finding_id, "confirmed")
    assert updated["officer_decision"] == "confirmed"
    assert updated["officer_remarks"] is None


def test_officer_decision_does_not_overwrite_automated_status(wired):
    """The automated engine's `status` column must survive human review
    untouched -- officer judgement is layered on top, never replacing it."""
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]
    original_status = findings[0]["status"]

    updated = wired["review"].record_finding_decision(OFFICER_ACTOR, finding_id, "confirmed")
    assert updated["status"] == original_status


def test_recording_finding_decision_does_not_alter_application_priority(wired, temp_db):
    """Priority (Module E) is computed exclusively by evidence_ladder and
    must never be reinvented/mutated by the review workflow."""
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]

    conn = temp_db.get_connection()
    try:
        priority_before = conn.execute(
            "SELECT priority FROM applications WHERE id = ?", (app_id,)
        ).fetchone()["priority"]
    finally:
        conn.close()

    wired["review"].record_finding_decision(OFFICER_ACTOR, finding_id, "dismissed", remarks="Reviewed.")

    conn = temp_db.get_connection()
    try:
        priority_after = conn.execute(
            "SELECT priority FROM applications WHERE id = ?", (app_id,)
        ).fetchone()["priority"]
    finally:
        conn.close()

    assert priority_before == priority_after


def test_finding_decision_is_audited_and_chain_stays_valid(wired, temp_db):
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]

    wired["review"].record_finding_decision(OFFICER_ACTOR, finding_id, "confirmed")

    conn = temp_db.get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE action = 'FINDING_DECISION_RECORDED' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["actor"] == OFFICER_ACTOR["username"]
        assert row["record_type"] == "finding"
        assert row["record_id"] == str(finding_id)

        ok, broken = verify_chain(conn)
        assert ok is True
        assert broken is None
    finally:
        conn.close()


def test_get_decided_findings_requires_officer_or_admin(wired):
    app_id, findings = _create_application_with_findings(wired)
    with pytest.raises(PermissionDenied):
        wired["review"].get_decided_findings(APPLICANT_ACTOR, app_id)


def test_get_decided_findings_returns_only_decided(wired):
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]

    assert wired["review"].get_decided_findings(OFFICER_ACTOR, app_id) == []

    wired["review"].record_finding_decision(OFFICER_ACTOR, finding_id, "confirmed")

    decided = wired["review"].get_decided_findings(OFFICER_ACTOR, app_id)
    assert len(decided) == 1
    assert decided[0]["id"] == finding_id


# ---------------------------------------------------------------------
# Application-level decisions: RBAC, validation, mandatory remarks
# ---------------------------------------------------------------------

def test_record_application_decision_requires_officer_or_admin(wired):
    app_id, _ = _create_application_with_findings(wired)
    with pytest.raises(PermissionDenied):
        wired["app"].record_application_decision(APPLICANT_ACTOR, app_id, "approved")


def test_record_application_decision_rejects_invalid_decision_value(wired):
    app_id, _ = _create_application_with_findings(wired)
    with pytest.raises(ValueError):
        wired["app"].record_application_decision(OFFICER_ACTOR, app_id, "under_review")


def test_record_application_decision_unknown_application_raises(wired):
    with pytest.raises(ValueError):
        wired["app"].record_application_decision(OFFICER_ACTOR, 999999, "approved")


def test_reject_application_without_remarks_is_rejected(wired):
    app_id, _ = _create_application_with_findings(wired)
    with pytest.raises(ValueError):
        wired["app"].record_application_decision(OFFICER_ACTOR, app_id, "rejected")
    with pytest.raises(ValueError):
        wired["app"].record_application_decision(OFFICER_ACTOR, app_id, "rejected", remarks="   ")


def test_reject_application_with_remarks_persists(wired, temp_db):
    app_id, _ = _create_application_with_findings(wired)
    wired["app"].record_application_decision(
        OFFICER_ACTOR, app_id, "rejected", remarks="Affiliation certificate could not be authenticated."
    )

    conn = temp_db.get_connection()
    try:
        row = conn.execute("SELECT status FROM applications WHERE id = ?", (app_id,)).fetchone()
        assert row["status"] == "rejected"
    finally:
        conn.close()


def test_approve_application_without_remarks_succeeds(wired, temp_db):
    app_id, _ = _create_application_with_findings(wired)
    result = wired["app"].record_application_decision(OFFICER_ACTOR, app_id, "approved")
    assert result is True

    conn = temp_db.get_connection()
    try:
        row = conn.execute("SELECT status FROM applications WHERE id = ?", (app_id,)).fetchone()
        assert row["status"] == "approved"
    finally:
        conn.close()


def test_application_decision_is_audited_and_chain_stays_valid(wired, temp_db):
    app_id, _ = _create_application_with_findings(wired)
    wired["app"].record_application_decision(OFFICER_ACTOR, app_id, "approved")

    conn = temp_db.get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE action = 'APPLICATION_DECISION_RECORDED' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["actor"] == OFFICER_ACTOR["username"]
        assert row["record_type"] == "application"
        assert row["record_id"] == str(app_id)

        ok, broken = verify_chain(conn)
        assert ok is True
        assert broken is None
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Combined officer-action history
# ---------------------------------------------------------------------

def test_get_officer_action_history_requires_officer_or_admin(wired):
    app_id, _ = _create_application_with_findings(wired)
    with pytest.raises(PermissionDenied):
        wired["app"].get_officer_action_history(APPLICANT_ACTOR, app_id)


def test_get_officer_action_history_combines_finding_and_application_decisions(wired):
    app_id, findings = _create_application_with_findings(wired)
    finding_id = findings[0]["id"]

    wired["review"].record_finding_decision(OFFICER_ACTOR, finding_id, "confirmed")
    wired["app"].record_application_decision(
        OFFICER_ACTOR, app_id, "rejected", remarks="Needs resubmission with authenticated documents."
    )

    history = wired["app"].get_officer_action_history(OFFICER_ACTOR, app_id)
    kinds = {h["kind"] for h in history}
    assert kinds == {"finding_decision", "application_decision"}
    assert len(history) == 2

    app_entry = next(h for h in history if h["kind"] == "application_decision")
    assert app_entry["actor"] == OFFICER_ACTOR["username"]
    assert "rejected" in app_entry["summary"]
    assert app_entry["remarks"] == "Needs resubmission with authenticated documents."

    finding_entry = next(h for h in history if h["kind"] == "finding_decision")
    assert finding_entry["summary"].startswith(f"Finding #{finding_id}")
    assert "confirmed" in finding_entry["summary"]