"""Officer/Admin/Applicant dashboard (Module H).

Phase 5: every number on this page is computed live from the database
at render time -- nothing here is hardcoded. On a completely empty
database every metric reads 0 and the page says so explicitly instead
of crashing or showing a placeholder chart.

RBAC / security note (this is an assistant design decision, not an
explicit requirement from the blueprint, flagged here for visibility):
applicants only ever see counts and a list scoped to their OWN
institution. The multi-institution filters, the SLA alert panel and
the cross-institution priority queue are restricted to officers/admins,
because they would otherwise let an applicant see another institution's
findings and verification status -- information they have no
legitimate reason to see. This mirrors the same officer/admin-only
pattern already used throughout services/*.py via require_role().

Priority queue note: priority (P1-P4) is NOT set or edited on this
page. It is computed by the Evidence-Ladder engine (Module E,
services/evidence_ladder.py, compute_priority()) from finding severity
and evidence strength, and is only ever displayed here.

SLA alert note: the day thresholds used below come from
utils/sla_config.py and are explicitly documented there as
DEMONSTRATION DEFAULTS, not an officially established AICTE
service-level commitment.
"""
import datetime as dt

import streamlit as st

from database.db import get_connection
from models.enums import ApplicationStatus
from utils.session import require_login
from utils.sla_config import (
    MANUAL_REVIEW_SLA_DAYS,
    SOURCE_UNAVAILABLE_SLA_DAYS,
    VERIFICATION_PENDING_SLA_DAYS,
)

user = require_login()

st.title("📊 Dashboard")


def _render_applicant_dashboard(conn, user):
    institution_id = user.get("institution_id")
    st.caption("Showing figures for your own institution only.")

    if institution_id is None:
        st.info("Your account is not linked to an institution yet. No application data to show.")
        return

    total = conn.execute(
        "SELECT COUNT(*) c FROM applications WHERE institution_id = ?", (institution_id,)
    ).fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM applications WHERE institution_id = ? AND status = ?",
        (institution_id, ApplicationStatus.SUBMITTED.value),
    ).fetchone()["c"]
    under_review = conn.execute(
        "SELECT COUNT(*) c FROM applications WHERE institution_id = ? AND status = ?",
        (institution_id, ApplicationStatus.UNDER_REVIEW.value),
    ).fetchone()["c"]
    decided = conn.execute(
        "SELECT COUNT(*) c FROM applications WHERE institution_id = ? AND status IN (?, ?)",
        (institution_id, ApplicationStatus.APPROVED.value, ApplicationStatus.REJECTED.value),
    ).fetchone()["c"]

    cols = st.columns(4)
    cols[0].metric("Total applications", total)
    cols[1].metric("Pending (submitted)", pending)
    cols[2].metric("Under review", under_review)
    cols[3].metric("Decided", decided)

    if total == 0:
        st.info("No applications have been created for your institution yet. Use **Applications** to create one.")
        return

    st.divider()
    st.subheader("Your applications")
    rows = conn.execute(
        """
        SELECT application_code, category, status, priority, submission_date
        FROM applications
        WHERE institution_id = ?
        ORDER BY submission_date DESC
        """,
        (institution_id,),
    ).fetchall()
    st.dataframe([dict(r) for r in rows], use_container_width=True, hide_index=True)


def _render_summary_counts(conn, where_sql, params):
    total = conn.execute(
        f"SELECT COUNT(*) c FROM applications a {where_sql}", params
    ).fetchone()["c"]

    joiner = "AND" if where_sql else "WHERE"

    pending = conn.execute(
        f"SELECT COUNT(*) c FROM applications a {where_sql} {joiner} a.status = ?",
        params + [ApplicationStatus.SUBMITTED.value],
    ).fetchone()["c"]

    # "Requiring review": application is actively under review AND has at
    # least one open finding that no officer has recorded a decision on
    # yet. This is a deliberate, documented definition (not an implicit
    # one) -- see README Phase 5 section.
    review_required = conn.execute(
        f"""
        SELECT COUNT(DISTINCT a.id) c
        FROM applications a
        {where_sql}
        {joiner} a.status = ?
          AND EXISTS (
              SELECT 1 FROM findings f
              WHERE f.application_id = a.id
                AND f.status = 'open'
                AND f.officer_decision IS NULL
          )
        """,
        params + [ApplicationStatus.UNDER_REVIEW.value],
    ).fetchone()["c"]

    verified_docs = conn.execute(
        f"""
        SELECT COUNT(DISTINCT vr.document_id) c
        FROM verification_requests vr
        JOIN applications a ON a.id = vr.application_id
        {where_sql}
        {joiner} vr.status = 'verified'
        """,
        params,
    ).fetchone()["c"]

    expired_docs = conn.execute(
        f"""
        SELECT COUNT(DISTINCT vr.document_id) c
        FROM verification_requests vr
        JOIN applications a ON a.id = vr.application_id
        {where_sql}
        {joiner} vr.status = 'expired'
        """,
        params,
    ).fetchone()["c"]

    mismatches = conn.execute(
        f"""
        SELECT COUNT(DISTINCT vr.document_id) c
        FROM verification_requests vr
        JOIN applications a ON a.id = vr.application_id
        {where_sql}
        {joiner} vr.status = 'mismatch_detected'
        """,
        params,
    ).fetchone()["c"]

    cols = st.columns(6)
    cols[0].metric("Total applications", total)
    cols[1].metric("Pending (submitted)", pending)
    cols[2].metric(
        "Requiring review", review_required,
        help="Status = under_review AND at least one open finding with no officer decision yet.",
    )
    cols[3].metric("Verified documents", verified_docs)
    cols[4].metric("Expired documents", expired_docs)
    cols[5].metric("Detected mismatches", mismatches)

    if total == 0:
        st.info("No applications match the current filters (or the database is empty).")


def _show_table(rows, empty_message):
    if not rows:
        st.caption(empty_message)
    else:
        st.dataframe([dict(r) for r in rows], use_container_width=True, hide_index=True)


def _render_alerts(conn):
    st.subheader("⚠️ Alerts")
    st.caption(
        f"Demonstration SLA thresholds only (utils/sla_config.py), NOT an officially "
        f"established AICTE deadline: verification-pending > {VERIFICATION_PENDING_SLA_DAYS}d, "
        f"source-unavailable > {SOURCE_UNAVAILABLE_SLA_DAYS}d, manual-review > "
        f"{MANUAL_REVIEW_SLA_DAYS}d."
    )

    def _overdue(status, sla_days):
        return conn.execute(
            """
            SELECT vr.id, a.application_code, vr.issuer_type, vr.certificate_number,
                   vr.requested_at,
                   CAST(julianday('now') - julianday(vr.requested_at) AS INTEGER) AS days_outstanding
            FROM verification_requests vr
            JOIN applications a ON a.id = vr.application_id
            WHERE vr.status = ?
              AND vr.responded_at IS NULL
              AND julianday('now') - julianday(vr.requested_at) > ?
            ORDER BY days_outstanding DESC
            """,
            (status, sla_days),
        ).fetchall()

    overdue_pending = _overdue("verification_pending", VERIFICATION_PENDING_SLA_DAYS)
    overdue_source_unavailable = _overdue("source_unavailable", SOURCE_UNAVAILABLE_SLA_DAYS)
    overdue_manual_review = _overdue("manual_review_required", MANUAL_REVIEW_SLA_DAYS)

    cols = st.columns(3)
    cols[0].metric("Overdue: awaiting verification response", len(overdue_pending))
    cols[1].metric("Overdue: source unavailable", len(overdue_source_unavailable))
    cols[2].metric("Overdue: manual review", len(overdue_manual_review))

    with st.expander(f"Awaiting verification response ({len(overdue_pending)} overdue)"):
        _show_table(overdue_pending, "None overdue.")
    with st.expander(f"Source unavailable ({len(overdue_source_unavailable)} overdue)"):
        _show_table(overdue_source_unavailable, "None overdue.")
    with st.expander(f"Manual review required ({len(overdue_manual_review)} overdue)"):
        _show_table(overdue_manual_review, "None overdue.")


def _render_priority_queue(conn, where_sql, params):
    st.subheader("📋 Priority queue")
    st.caption(
        "Ordered by priority (P1 highest) then oldest submission first. Priority is "
        "computed by the Evidence-Ladder engine from finding severity and evidence "
        "strength -- it cannot be edited here."
    )

    rows = conn.execute(
        f"""
        SELECT
            a.id AS application_id,
            a.application_code,
            i.name AS institution_name,
            a.category,
            a.status,
            a.priority,
            a.submission_date,
            a.assigned_officer,
            (SELECT COUNT(*) FROM findings f
             WHERE f.application_id = a.id AND f.status = 'open' AND f.officer_decision IS NULL
            ) AS open_findings
        FROM applications a
        JOIN institutions i ON i.id = a.institution_id
        {where_sql}
        ORDER BY a.priority ASC, a.submission_date ASC
        """,
        params,
    ).fetchall()

    if not rows:
        st.info("No applications match the current filters.")
        return

    header = st.columns([2, 3, 2, 1, 1, 2, 1])
    for col, label in zip(header, ["Application", "Institution", "Status", "Priority", "Open", "Submitted", ""]):
        col.markdown(f"**{label}**")

    for row in rows:
        cols = st.columns([2, 3, 2, 1, 1, 2, 1])
        cols[0].write(row["application_code"])
        cols[1].write(row["institution_name"])
        cols[2].write(row["status"])
        cols[3].write(row["priority"])
        cols[4].write(str(row["open_findings"]))
        cols[5].write(row["submission_date"])
        if cols[6].button("Open", key=f"open_{row['application_id']}"):
            # Consumed by pages/review_workbench.py (Phase 5 Batch 3).
            st.session_state["workbench_application_id"] = row["application_id"]
            st.switch_page("pages/review_workbench.py")


def _render_officer_dashboard(conn, user):
    st.caption(
        "All figures below are computed live from the database. SLA alerts use "
        "demonstration thresholds, not an official deadline (see utils/sla_config.py)."
    )

    institutions = conn.execute(
        "SELECT DISTINCT i.id, i.name FROM institutions i "
        "JOIN applications a ON a.institution_id = i.id ORDER BY i.name"
    ).fetchall()

    with st.expander("Filters", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            institution_choice = st.selectbox(
                "Institution",
                options=["All"] + [row["name"] for row in institutions],
                index=0,
            )
            status_choice = st.multiselect(
                "Application status",
                options=[s.value for s in ApplicationStatus],
                default=[],
                help="Leave empty to include all statuses.",
            )
        with col2:
            priority_choice = st.multiselect(
                "Priority",
                options=["P1", "P2", "P3", "P4"],
                default=[],
                help="Leave empty to include all priorities.",
            )
            use_date_filter = st.checkbox("Filter by submission date", value=False)
            date_from = date_to = None
            if use_date_filter:
                date_from = st.date_input("From", value=dt.date.today() - dt.timedelta(days=30))
                date_to = st.date_input("To", value=dt.date.today())

    where_clauses = []
    params = []
    if institution_choice != "All":
        inst_id = next((row["id"] for row in institutions if row["name"] == institution_choice), None)
        if inst_id is not None:
            where_clauses.append("a.institution_id = ?")
            params.append(inst_id)
    if status_choice:
        placeholders = ",".join("?" for _ in status_choice)
        where_clauses.append(f"a.status IN ({placeholders})")
        params.extend(status_choice)
    if priority_choice:
        placeholders = ",".join("?" for _ in priority_choice)
        where_clauses.append(f"a.priority IN ({placeholders})")
        params.extend(priority_choice)
    if use_date_filter and date_from and date_to:
        where_clauses.append("a.submission_date BETWEEN ? AND ?")
        params.extend([date_from.isoformat(), date_to.isoformat()])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    _render_summary_counts(conn, where_sql, params)
    st.divider()
    _render_alerts(conn)
    st.divider()
    _render_priority_queue(conn, where_sql, params)


conn = get_connection()
try:
    if user["role"] in ("officer", "admin"):
        _render_officer_dashboard(conn, user)
    else:
        _render_applicant_dashboard(conn, user)
finally:
    conn.close()

st.divider()
with st.expander("Your account"):
    st.json({k: v for k, v in user.items() if k not in ("password_hash", "password_salt")})