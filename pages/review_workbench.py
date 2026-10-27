"""Application Review Workbench (Module J).

Phase 5: this is where an officer reviews a single application end to
end and records decisions. It intentionally reuses, rather than
reimplements:

  - services.validation_engine.list_findings()      (Module D findings)
  - services.review_service.record_finding_decision() (Module J actions)
  - services.application_service.record_application_decision()
  - services.application_service.get_officer_action_history()
  - models.enums.Rung / RUNG_LABELS for evidence-level display

Everything else on this page (application header, document list,
extracted fields, checklist/missing-documents, verification-request
history) is read with direct SQL against the already-confirmed schema,
the same pattern pages/dashboard.py uses -- these are read-only
displays, not state-changing actions, so there is no RBAC concern in
reading them this way. All WRITE actions (finding decisions,
application decisions) go exclusively through the service layer, which
is where require_role() enforcement actually lives. That is the
authoritative backend restriction that keeps applicants from performing
officer-only actions, even though this page also bars them at the UI
level below as a first line of defence.

CORRECTION (flagged during Phase 5 test-writing): findings.decided_by
stores an integer users.id, not a username. The finding detail panel
below resolves it via a small id->username lookup rather than printing
the raw id.
"""
import streamlit as st

from database.db import get_connection
from models.enums import Rung, FindingDecision, FINDING_DECISIONS_REQUIRING_REMARKS, ApplicationStatus
from services import validation_engine
from services import review_service
from services import application_service
from utils.session import require_login

try:
    from models.enums import RUNG_LABELS
except ImportError:  # pragma: no cover - defensive only
    RUNG_LABELS = {}


def _rung_label(rung_value):
    """Best-effort human label for a rung value.

    Defensive by design: we don't have RUNG_LABELS's exact keying
    convention confirmed verbatim in this session, so this tries a
    couple of reasonable possibilities before falling back to a plain
    numeric label rather than crashing the page.
    """
    try:
        return RUNG_LABELS[Rung(rung_value)]
    except Exception:
        pass
    try:
        return RUNG_LABELS[int(rung_value)]
    except Exception:
        pass
    return f"Rung {rung_value}"


user = require_login()

if user["role"] not in ("officer", "admin"):
    st.error("This page is restricted to scrutiny officers and administrators.")
    st.caption(
        "Applicants cannot access the review workbench. This is enforced again, "
        "authoritatively, inside services/review_service.py and "
        "services/application_service.py via require_role() -- this page-level "
        "check is only a first line of defence, not the real control."
    )
    st.stop()

st.title("🗂️ Review Workbench")

conn = get_connection()
try:
    app_rows = conn.execute(
        "SELECT id, application_code, priority, status, submission_date "
        "FROM applications ORDER BY priority ASC, submission_date ASC"
    ).fetchall()
    username_by_id = {
        row["id"]: row["username"]
        for row in conn.execute("SELECT id, username FROM users").fetchall()
    }
finally:
    conn.close()

if not app_rows:
    st.info("No applications exist yet. Create one from the **Applications** page.")
    st.stop()

app_ids = [row["id"] for row in app_rows]
labels = {row["id"]: f"{row['application_code']} — {row['status']} — {row['priority']}" for row in app_rows}

preselected = st.session_state.get("workbench_application_id")
default_index = app_ids.index(preselected) if preselected in app_ids else 0

selected_id = st.selectbox(
    "Application",
    options=app_ids,
    format_func=lambda i: labels[i],
    index=default_index,
)
st.session_state["workbench_application_id"] = selected_id
application_id = selected_id

conn = get_connection()
try:
    app_row = conn.execute(
        """
        SELECT a.*, i.name AS institution_name, i.institution_code, i.state
        FROM applications a
        JOIN institutions i ON i.id = a.institution_id
        WHERE a.id = ?
        """,
        (application_id,),
    ).fetchone()

    documents = conn.execute(
        "SELECT * FROM documents WHERE application_id = ? ORDER BY doc_type",
        (application_id,),
    ).fetchall()

    checklist = conn.execute(
        "SELECT * FROM checklist_items WHERE application_id = ? ORDER BY doc_type",
        (application_id,),
    ).fetchall()

    verification_requests = conn.execute(
        """
        SELECT vr.*, d.doc_type, d.original_filename
        FROM verification_requests vr
        JOIN documents d ON d.id = vr.document_id
        WHERE vr.application_id = ?
        ORDER BY vr.requested_at DESC
        """,
        (application_id,),
    ).fetchall()

    extracted_fields_by_doc = {}
    for doc in documents:
        extracted_fields_by_doc[doc["id"]] = conn.execute(
            "SELECT * FROM extracted_fields WHERE document_id = ? ORDER BY field_name",
            (doc["id"],),
        ).fetchall()
finally:
    conn.close()

if app_row is None:
    st.error("Selected application could not be loaded.")
    st.stop()

# ---------------------------------------------------------------- header --
st.header(f"{app_row['application_code']}")
cols = st.columns(5)
cols[0].metric("Status", app_row["status"])
cols[1].metric("Priority", app_row["priority"])
cols[2].metric("Category", app_row["category"])
cols[3].metric("Academic year", app_row["academic_year"])
cols[4].metric("Submitted", app_row["submission_date"])

st.caption(
    f"Institution: **{app_row['institution_name']}** "
    f"({app_row['institution_code']}, {app_row['state']}) &nbsp;|&nbsp; "
    f"Assigned officer: {app_row['assigned_officer'] or '—'}"
)
if app_row["is_synthetic"]:
    st.caption(f"🧪 Synthetic demo application — scenario: `{app_row['scenario_tag']}`")

st.divider()

# ------------------------------------------------------------- documents --
st.subheader("📄 Documents")
if not documents:
    st.caption("No documents uploaded yet.")
else:
    for doc in documents:
        with st.expander(f"{doc['doc_type']} — {doc['original_filename']}"):
            dcols = st.columns(4)
            dcols[0].write(f"**Extraction:** {doc['extraction_status']}")
            dcols[1].write(f"**Native text:** {'Yes' if doc['is_native_text'] else 'No'}")
            dcols[2].write(f"**OCR used:** {'Yes' if doc['ocr_used'] else 'No'}")
            dcols[3].write(f"**Pages:** {doc['page_count']}")
            st.caption(f"SHA-256: `{doc['sha256']}`")

            fields = extracted_fields_by_doc.get(doc["id"], [])
            if fields:
                st.markdown("**Extracted fields**")
                st.dataframe(
                    [
                        {
                            "field": f["field_name"],
                            "value": f["field_value"],
                            "confidence": f["confidence"],
                            "page": f["page_number"],
                        }
                        for f in fields
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No extracted fields recorded for this document.")

st.divider()

# ----------------------------------------------------- checklist / gaps --
st.subheader("✅ Document checklist")
missing_required = [c for c in checklist if c["required"] and not c["satisfied"]]
if checklist:
    st.dataframe(
        [
            {"document type": c["doc_type"], "required": bool(c["required"]), "satisfied": bool(c["satisfied"])}
            for c in checklist
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.caption("No checklist recorded for this application.")

if missing_required:
    st.warning(
        "Missing required documents: " + ", ".join(c["doc_type"] for c in missing_required)
    )

st.divider()

# --------------------------------------------- issuer verification history --
st.subheader("🏛️ Issuer verification history")
if not verification_requests:
    st.caption("No verification requests recorded for this application.")
else:
    st.dataframe(
        [
            {
                "document": vr["original_filename"],
                "issuer type": vr["issuer_type"],
                "certificate #": vr["certificate_number"],
                "status": vr["status"],
                "source": vr["source"],
                "requested": vr["requested_at"],
                "responded": vr["responded_at"],
                "manual notes": vr["manual_notes"],
            }
            for vr in verification_requests
        ],
        use_container_width=True,
        hide_index=True,
    )
    expired = [vr for vr in verification_requests if vr["status"] == "expired"]
    if expired:
        st.warning(
            "Expired documents detected: "
            + ", ".join(f"{vr['original_filename']} ({vr['certificate_number']})" for vr in expired)
        )

st.divider()

# -------------------------------------------------------------- findings --
st.subheader("🔍 Findings")
findings = validation_engine.list_findings(user, application_id=application_id)

if not findings:
    st.caption("No findings recorded for this application yet.")
else:
    decision_options = [d.value for d in FindingDecision]

    for finding in findings:
        rung_label = _rung_label(finding.get("rung", 0))
        decided = finding.get("officer_decision")
        badge = f" — ✔️ {decided}" if decided else ""
        header = f"[{finding['severity'].upper()}] {finding['rule_id']} — {rung_label}{badge}"

        with st.expander(header):
            icols = st.columns(2)
            with icols[0]:
                st.write(f"**Engine:** {finding['engine']}")
                st.write(f"**Document:** {finding.get('original_filename', '—')} ({finding.get('doc_type', '—')})")
                st.write(f"**Page:** {finding.get('page_number', '—')}")
                st.write(f"**Clause ref:** {finding.get('clause_ref') or '—'}")
            with icols[1]:
                st.write(f"**Advisory only:** {'Yes' if finding.get('advisory') else 'No'}")
                st.write(f"**Extracted value:** {finding.get('extracted_value') or '—'}")
                st.write(f"**Expected value:** {finding.get('expected_value') or '—'}")

            st.markdown(f"**Description:** {finding.get('description') or '—'}")
            st.markdown(f"**Reason:** {finding.get('reason') or '—'}")
            if finding.get("recommended_action"):
                st.info(f"Recommended action: {finding['recommended_action']}")

            if decided:
                decided_by_name = username_by_id.get(finding.get("decided_by"), "—")
                st.success(
                    f"Officer decision already recorded: **{decided}** "
                    f"by {decided_by_name} at {finding.get('decided_at') or '—'}"
                )
                if finding.get("officer_remarks"):
                    st.caption(f"Remarks: {finding['officer_remarks']}")

            st.markdown("---")
            st.markdown("**Record / update officer decision**")
            chosen = st.selectbox(
                "Decision",
                options=decision_options,
                key=f"decision_select_{finding['id']}",
            )
            remarks_required = chosen in FINDING_DECISIONS_REQUIRING_REMARKS
            remarks = st.text_area(
                f"Remarks{' (required for this decision)' if remarks_required else ' (optional)'}",
                key=f"decision_remarks_{finding['id']}",
            )
            if st.button("Save decision", key=f"decision_submit_{finding['id']}"):
                if remarks_required and not remarks.strip():
                    st.error("Remarks are mandatory for this decision.")
                else:
                    try:
                        review_service.record_finding_decision(
                            user, finding["id"], chosen, remarks=remarks.strip() or None
                        )
                        st.success("Decision recorded.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not record decision: {exc}")

st.divider()

# ------------------------------------------------------ application decision --
st.subheader("📝 Application decision")
st.caption(
    f"Current status: **{app_row['status']}**. Recording a decision here does not "
    f"overwrite or erase the automated engine results above -- it is stored "
    f"separately as the human judgement layered on top of them."
)

app_remarks = st.text_area(
    "Remarks (required if rejecting)",
    key="app_decision_remarks",
)
acols = st.columns(2)
with acols[0]:
    if st.button("✅ Approve application", use_container_width=True):
        try:
            application_service.record_application_decision(
                user, application_id, ApplicationStatus.APPROVED.value,
                remarks=app_remarks.strip() or None,
            )
            st.success("Application approved.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not record approval: {exc}")
with acols[1]:
    if st.button("❌ Reject application", use_container_width=True):
        if not app_remarks.strip():
            st.error("Remarks are mandatory when rejecting an application.")
        else:
            try:
                application_service.record_application_decision(
                    user, application_id, ApplicationStatus.REJECTED.value,
                    remarks=app_remarks.strip(),
                )
                st.success("Application rejected.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not record rejection: {exc}")

st.divider()

# -------------------------------------------------------- previous actions --
st.subheader("🕑 Previous officer actions")
history = application_service.get_officer_action_history(user, application_id)
if not history:
    st.caption("No officer actions recorded yet for this application.")
else:
    st.dataframe(
        [
            {
                "when": h["timestamp"],
                "type": h["kind"],
                "by": h["actor"],
                "summary": h["summary"],
                "remarks": h.get("remarks") or "",
            }
            for h in history
        ],
        use_container_width=True,
        hide_index=True,
    )