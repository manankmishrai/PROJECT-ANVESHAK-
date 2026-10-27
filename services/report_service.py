"""Module I: downloadable validation reports (PDF + CSV) and
applicant-facing restricted feedback.

Two distinct audiences are produced, and the distinction is enforced
HERE, in backend code -- not merely by which page/button the UI shows
(Phase 6, Section B requirement):

  * Officer/admin report (`generate_officer_pdf_report`): everything on
    record for the application -- rule-engine findings, forensics /
    signature findings, mock issuer-verification results (always
    clearly labelled as synthetic/mock), officer decisions, remarks,
    and full action history.

  * Applicant report (`generate_applicant_pdf_report`): ONLY
    completeness / consistency / expiry findings produced by the
    deterministic rule engine. Forensic/signature findings, raw
    issuer-verification detail, officer remarks/decisions, and any
    finding whose text references another institution or another
    application are excluded -- never merely hidden in the UI.

This module never invents a result or a figure. Everything rendered is
read directly from the database at generation time, and every
generated report is itself recorded via a REPORT_GENERATED audit
entry.

Known, disclosed limitation: PDF text is rendered with reportlab's
built-in Helvetica font (WinAnsi/Latin-1 encoding only). Characters
outside that range (e.g. most Indic scripts) will not render
correctly. This does NOT crash report generation -- it is a cosmetic
limitation of the bundled fonts, documented here and in the README,
not silently hidden.
"""
from datetime import datetime, timezone
from io import BytesIO, StringIO
import csv

from database.db import get_connection
from services import application_service, evidence_ladder
from services.auth_service import require_role, PermissionDenied
from models.enums import Rung
from utils import audit

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False


class ReportUnavailableError(Exception):
    """Raised when a report cannot be produced -- missing dependency,
    application not found, etc. Never silently returns an empty or
    fabricated report instead."""


# Engines excluded wholesale from applicant-facing reports.
RESTRICTED_ENGINES_FOR_APPLICANT = {"forensics_engine", "issuer_service", "qr_service"}

DISCLAIMER_GENERAL = (
    "This report was produced by a prototype scrutiny-support tool built for "
    "SIH 2026 (AICTE Smart Automation theme). It is an advisory aid only. "
    "Findings flag anomalies and inconsistencies for human review -- an "
    "anomaly is NEVER, by itself, proof of fraud or non-compliance. Final "
    "determinations rest with an authorised human officer."
)
DISCLAIMER_ISSUER = (
    "SYNTHETIC / MOCK VERIFICATION DATA: issuer-verification results below "
    "are produced by a local, illustrative mock registry bundled with this "
    "prototype. They are NOT the result of a real AICTE or government "
    "database lookup and must never be treated as such."
)
DISCLAIMER_UNICODE = (
    "Note: this report is rendered with a basic Latin-script PDF font. "
    "Text in non-Latin scripts may not display correctly."
)


# ---------------------------------------------------------------------
# Data gathering helpers
# ---------------------------------------------------------------------

def _get_application_or_raise(conn, application_id):
    row = conn.execute(
        "SELECT a.*, i.name AS institution_name, i.institution_code AS institution_code, "
        "i.state AS institution_state FROM applications a "
        "JOIN institutions i ON i.id = a.institution_id WHERE a.id = ?",
        (application_id,),
    ).fetchone()
    if row is None:
        raise ReportUnavailableError(f"Application {application_id} was not found.")
    return dict(row)


def _enforce_applicant_access(actor, application):
    if actor["role"] == "applicant" and actor.get("institution_id") != application["institution_id"]:
        raise PermissionDenied("You may only view reports for your own institution's applications.")


def _raw_findings_for_application(conn, application_id):
    rows = conn.execute(
        """SELECT f.*, d.original_filename AS original_filename, d.doc_type AS doc_type
           FROM findings f
           LEFT JOIN documents d ON d.id = f.document_id
           WHERE f.application_id = ?
           ORDER BY f.engine, f.created_at""",
        (application_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _contains_other_institution_reference(text, own_institution_id, all_institutions, other_app_codes):
    if not text:
        return False
    low = str(text).lower()
    for code in other_app_codes:
        if code and code.lower() in low:
            return True
    for inst in all_institutions:
        if inst["id"] == own_institution_id:
            continue
        if inst.get("name") and inst["name"].lower() in low:
            return True
        if inst.get("institution_code") and inst["institution_code"].lower() in low:
            return True
    return False


def _applicant_visible_findings(conn, application, all_findings):
    own_institution_id = application["institution_id"]
    all_institutions = [dict(r) for r in conn.execute(
        "SELECT id, name, institution_code FROM institutions"
    ).fetchall()]
    other_app_codes = [r["application_code"] for r in conn.execute(
        "SELECT application_code FROM applications WHERE id != ?", (application["id"],)
    ).fetchall()]

    visible = []
    for f in all_findings:
        if f.get("engine") in RESTRICTED_ENGINES_FOR_APPLICANT:
            continue
        combined = " ".join(
            str(f.get(k) or "") for k in ("description", "reason", "extracted_value", "expected_value")
        )
        if _contains_other_institution_reference(combined, own_institution_id, all_institutions, other_app_codes):
            continue
        f2 = dict(f)
        for key in ("officer_decision", "officer_remarks", "decided_by", "decided_at"):
            f2.pop(key, None)
        visible.append(f2)
    return visible


def _rung_label(rung_value):
    try:
        return evidence_ladder.evidence_source_label(rung_value)
    except Exception:
        return f"Rung {rung_value}"


def _esc(value, default="\u2014"):
    if value is None or value == "":
        return default
    s = str(value)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------

def _styles():
    base = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=base["BodyText"], fontSize=8, leading=10)
    small = ParagraphStyle("small", parent=base["BodyText"], fontSize=8, leading=10, textColor=colors.grey)
    return base, cell, small


def _kv_table(pairs, avail_width):
    base, cell, _ = _styles()
    data = [[Paragraph(f"<b>{_esc(k)}</b>", cell), Paragraph(_esc(v), cell)] for k, v in pairs]
    t = Table(data, colWidths=[avail_width * 0.32, avail_width * 0.68])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
    ]))
    return t


SEVERITY_COLORS = {
    "low": colors.HexColor("#e8f5e9"),
    "medium": colors.HexColor("#fff8e1"),
    "high": colors.HexColor("#ffe0b2"),
    "critical": colors.HexColor("#ffcdd2"),
}


def _findings_table(findings, avail_width, show_officer_cols):
    base, cell, _ = _styles()
    headers = ["Engine", "Rule / Check", "Severity", "Evidence Level", "Description", "Recommended Action"]
    if show_officer_cols:
        headers += ["Officer Decision", "Remarks"]
    data = [[Paragraph(f"<b>{h}</b>", cell) for h in headers]]

    for f in findings:
        row = [
            Paragraph(_esc(f.get("engine")), cell),
            Paragraph(_esc(f.get("rule_id")), cell),
            Paragraph(_esc(f.get("severity")), cell),
            Paragraph(_esc(_rung_label(f.get("rung", 0))), cell),
            Paragraph(_esc(f.get("description")), cell),
            Paragraph(_esc(f.get("recommended_action")), cell),
        ]
        if show_officer_cols:
            row.append(Paragraph(_esc(f.get("officer_decision")), cell))
            row.append(Paragraph(_esc(f.get("officer_remarks")), cell))
        data.append(row)

    if show_officer_cols:
        widths = [0.10, 0.14, 0.08, 0.14, 0.24, 0.16, 0.08, 0.06]
    else:
        widths = [0.11, 0.15, 0.09, 0.16, 0.29, 0.20]
    col_widths = [avail_width * w for w in widths]

    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for idx, f in enumerate(findings, start=1):
        bg = SEVERITY_COLORS.get(f.get("severity"))
        if bg:
            style.append(("BACKGROUND", (0, idx), (-1, idx), bg))
    t.setStyle(TableStyle(style))
    return t


def _render_pdf(audience, application, checklist, documents, findings,
                 verification_requests=None, username_by_id=None,
                 action_history=None, generated_by="system"):
    if not REPORTLAB_AVAILABLE:
        raise ReportUnavailableError(
            "PDF generation requires the 'reportlab' package, which is not "
            "installed in this environment. Install it with: pip install reportlab"
        )
    verification_requests = verification_requests or []
    username_by_id = username_by_id or {}
    action_history = action_history or []

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                             topMargin=14 * mm, bottomMargin=14 * mm)
    avail_width = doc.width
    base, cell, small = _styles()
    story = []

    title = "Evidence-Ladder Scrutiny Copilot \u2014 Validation Report"
    if audience == "applicant":
        title += " (Applicant Feedback)"
    story.append(Paragraph(title, base["Title"]))
    story.append(Paragraph(DISCLAIMER_GENERAL, small))
    story.append(Paragraph(DISCLAIMER_UNICODE, small))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Application Details", base["Heading2"]))
    story.append(_kv_table([
        ("Application ID", application.get("application_code")),
        ("Institution", application.get("institution_name")),
        ("Institution Code", application.get("institution_code")),
        ("State", application.get("institution_state")),
        ("Category", application.get("category")),
        ("Academic Year", application.get("academic_year")),
        ("Submission Date", application.get("submission_date")),
        ("Status", application.get("status")),
        ("Priority", application.get("priority")),
    ], avail_width))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Documents Checked", base["Heading2"]))
    doc_rows = [["Document Type", "Filename", "Uploaded"]]
    for d in documents:
        doc_rows.append([d.get("doc_type", "\u2014"), d.get("original_filename", "\u2014"),
                          str(d.get("upload_date") or "\u2014")])
    t = Table([[Paragraph(f"<b>{_esc(c)}</b>", cell) for c in doc_rows[0]]] +
              [[Paragraph(_esc(c), cell) for c in r] for r in doc_rows[1:]],
              colWidths=[avail_width * 0.3, avail_width * 0.5, avail_width * 0.2])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
    story.append(t)
    story.append(Spacer(1, 6))

    missing = [c for c in checklist if c.get("required") and not c.get("satisfied")]
    if missing:
        story.append(Paragraph(
            "<b>Missing required documents:</b> " +
            ", ".join(_esc(c.get("doc_type")) for c in missing),
            base["BodyText"]))
    else:
        story.append(Paragraph("All checklist-required documents have been uploaded.", base["BodyText"]))
    story.append(Spacer(1, 10))

    if audience == "officer":
        story.append(Paragraph("Extraction Results", base["Heading2"]))
        story.append(Paragraph(
            "Confidence values below are a fixed heuristic label-match "
            "confidence (not a calibrated machine-learning score).", small))
        field_rows = [["Document", "Field", "Value", "Confidence", "Page"]]
        any_fields = False
        for d in documents:
            for fld in d.get("fields", []):
                any_fields = True
                field_rows.append([
                    d.get("original_filename", "\u2014"), fld.get("field_name"),
                    fld.get("field_value"), f"{fld.get('confidence', 0):.2f}",
                    str(fld.get("page_number", "\u2014")),
                ])
        if any_fields:
            t = Table([[Paragraph(f"<b>{_esc(c)}</b>", cell) for c in field_rows[0]]] +
                      [[Paragraph(_esc(c), cell) for c in r] for r in field_rows[1:]],
                      colWidths=[avail_width * 0.26, avail_width * 0.18, avail_width * 0.34,
                                 avail_width * 0.12, avail_width * 0.10],
                      repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
                                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
            story.append(t)
        else:
            story.append(Paragraph("No fields were extracted for this application.", base["BodyText"]))
        story.append(Spacer(1, 10))

    story.append(Paragraph("Findings (Rules Executed, Forensics, Verification)"
                            if audience == "officer" else "Completeness, Consistency and Expiry Findings",
                            base["Heading2"]))
    if findings:
        story.append(_findings_table(findings, avail_width, show_officer_cols=(audience == "officer")))
    else:
        story.append(Paragraph("No findings are currently on record for this application.", base["BodyText"]))
    story.append(Spacer(1, 10))

    if audience == "officer":
        sig_findings = [f for f in findings if f.get("engine") == "forensics_engine"
                         and str(f.get("rule_id", "")).startswith("SIG-")]
        story.append(Paragraph("Signature-Check Results", base["Heading2"]))
        if sig_findings:
            for f in sig_findings:
                story.append(Paragraph(
                    f"<b>{_esc(f.get('original_filename'))}:</b> {_esc(f.get('description'))}",
                    base["BodyText"]))
        else:
            story.append(Paragraph("No signature-check results are on record.", base["BodyText"]))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Issuer Verification Status", base["Heading2"]))
        story.append(Paragraph(DISCLAIMER_ISSUER, small))
        if verification_requests:
            vr_rows = [["Issuer Type", "Certificate No.", "Status", "Source", "Notes"]]
            for v in verification_requests:
                vr_rows.append([v.get("issuer_type"), v.get("certificate_number"),
                                 v.get("status"), v.get("source") or "\u2014",
                                 v.get("manual_notes") or "\u2014"])
            t = Table([[Paragraph(f"<b>{_esc(c)}</b>", cell) for c in vr_rows[0]]] +
                      [[Paragraph(_esc(c), cell) for c in r] for r in vr_rows[1:]],
                      colWidths=[avail_width * 0.18, avail_width * 0.22, avail_width * 0.18,
                                 avail_width * 0.14, avail_width * 0.28], repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
                                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
            story.append(t)
        else:
            story.append(Paragraph("No issuer-verification requests are on record.", base["BodyText"]))
        story.append(Spacer(1, 10))

    story.append(Paragraph("Missing and Expired Documents", base["Heading2"]))
    expired = [f for f in findings if "expired" in str(f.get("rule_id", "")).lower()
               or "expired" in str(f.get("description", "")).lower()]
    lines = []
    if missing:
        lines.append("Missing: " + ", ".join(_esc(c.get("doc_type")) for c in missing))
    if expired:
        lines.append("Expired/near-expiry findings: " + "; ".join(_esc(f.get("description")) for f in expired))
    if not lines:
        lines = ["No missing or expired documents were identified."]
    for ln in lines:
        story.append(Paragraph(ln, base["BodyText"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Recommended Rectification Actions", base["Heading2"]))
    actions = []
    seen = set()
    for f in findings:
        act = f.get("recommended_action")
        if act and act not in seen and "N/A" not in act:
            seen.add(act)
            actions.append(f"[{_esc(f.get('rule_id'))}] {_esc(act)}")
    if actions:
        for a in actions:
            story.append(Paragraph("\u2022 " + a, base["BodyText"]))
    else:
        story.append(Paragraph("No rectification actions are currently recommended.", base["BodyText"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Unresolved Manual Checks", base["Heading2"]))
    unresolved = [f for f in findings if not f.get("officer_decision") and f.get("status") == "open"]
    if audience == "officer":
        unresolved_vr = [v for v in verification_requests if v.get("status") not in ("verified",)]
        if unresolved:
            story.append(Paragraph(f"{len(unresolved)} finding(s) awaiting officer review.", base["BodyText"]))
        if unresolved_vr:
            story.append(Paragraph(f"{len(unresolved_vr)} verification request(s) not yet fully verified.",
                                    base["BodyText"]))
        if not unresolved and not unresolved_vr:
            story.append(Paragraph("No unresolved manual checks remain.", base["BodyText"]))
    else:
        if unresolved:
            story.append(Paragraph(f"{len(unresolved)} item(s) are still awaiting officer review.",
                                    base["BodyText"]))
        else:
            story.append(Paragraph("No items are currently awaiting officer review.", base["BodyText"]))
    story.append(Spacer(1, 10))

    if audience == "officer":
        story.append(Paragraph("Officer Decisions and Remarks (Action History)", base["Heading2"]))
        if action_history:
            hist_rows = [["When", "Actor", "Summary", "Remarks"]]
            for h in action_history:
                hist_rows.append([str(h.get("timestamp")), h.get("actor"), h.get("summary"),
                                   h.get("remarks") or "\u2014"])
            t = Table([[Paragraph(f"<b>{_esc(c)}</b>", cell) for c in hist_rows[0]]] +
                      [[Paragraph(_esc(c), cell) for c in r] for r in hist_rows[1:]],
                      colWidths=[avail_width * 0.18, avail_width * 0.14, avail_width * 0.38,
                                 avail_width * 0.30], repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
                                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
            story.append(t)
        else:
            story.append(Paragraph("No officer decisions have been recorded for this application.",
                                    base["BodyText"]))
        story.append(Spacer(1, 10))
    else:
        story.append(Paragraph(
            "This feedback report excludes internal forensic analysis, raw issuer-"
            "verification detail, officer notes, and administrative information.",
            small))
        story.append(Spacer(1, 6))

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    story.append(Paragraph(f"Report generated: {ts} by {_esc(generated_by)}", small))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------

def generate_officer_pdf_report(actor, application_id) -> bytes:
    require_role(actor, ("officer", "admin"))
    conn = get_connection()
    try:
        application = _get_application_or_raise(conn, application_id)
        checklist = [dict(r) for r in conn.execute(
            "SELECT * FROM checklist_items WHERE application_id = ?", (application_id,)
        ).fetchall()]
        documents = [dict(r) for r in conn.execute(
            "SELECT * FROM documents WHERE application_id = ?", (application_id,)
        ).fetchall()]
        for d in documents:
            d["fields"] = [dict(r) for r in conn.execute(
                "SELECT * FROM extracted_fields WHERE document_id = ? ORDER BY page_number",
                (d["id"],),
            ).fetchall()]
        findings = _raw_findings_for_application(conn, application_id)
        verification_requests = [dict(r) for r in conn.execute(
            "SELECT * FROM verification_requests WHERE application_id = ? ORDER BY requested_at",
            (application_id,),
        ).fetchall()]
        username_by_id = {r["id"]: r["username"] for r in conn.execute(
            "SELECT id, username FROM users").fetchall()}
        action_history = application_service.get_officer_action_history(actor, application_id)

        pdf_bytes = _render_pdf(
            audience="officer", application=application, checklist=checklist,
            documents=documents, findings=findings,
            verification_requests=verification_requests, username_by_id=username_by_id,
            action_history=action_history, generated_by=actor["username"],
        )

        audit.append_entry(
            conn, actor=actor["username"], action="REPORT_GENERATED",
            record_type="application", record_id=str(application_id),
            payload={"report_type": "officer_pdf", "application_code": application["application_code"]},
        )
        conn.commit()
        return pdf_bytes
    finally:
        conn.close()


def generate_applicant_pdf_report(actor, application_id) -> bytes:
    require_role(actor, ("applicant", "officer", "admin"))
    conn = get_connection()
    try:
        application = _get_application_or_raise(conn, application_id)
        _enforce_applicant_access(actor, application)
        checklist = [dict(r) for r in conn.execute(
            "SELECT * FROM checklist_items WHERE application_id = ?", (application_id,)
        ).fetchall()]
        documents = [dict(r) for r in conn.execute(
            "SELECT * FROM documents WHERE application_id = ?", (application_id,)
        ).fetchall()]
        all_findings = _raw_findings_for_application(conn, application_id)
        visible_findings = _applicant_visible_findings(conn, application, all_findings)

        pdf_bytes = _render_pdf(
            audience="applicant", application=application, checklist=checklist,
            documents=documents, findings=visible_findings, generated_by=actor["username"],
        )

        audit.append_entry(
            conn, actor=actor["username"], action="REPORT_GENERATED",
            record_type="application", record_id=str(application_id),
            payload={"report_type": "applicant_pdf", "application_code": application["application_code"]},
        )
        conn.commit()
        return pdf_bytes
    finally:
        conn.close()


def generate_findings_csv(actor, application_id) -> bytes:
    """Officer/admin only: full, unrestricted findings export. Not
    offered to applicants -- the applicant feedback report above is
    the only applicant-facing artefact."""
    require_role(actor, ("officer", "admin"))
    conn = get_connection()
    try:
        application = _get_application_or_raise(conn, application_id)
        findings = _raw_findings_for_application(conn, application_id)
        username_by_id = {r["id"]: r["username"] for r in conn.execute(
            "SELECT id, username FROM users").fetchall()}

        out = StringIO()
        writer = csv.writer(out)
        columns = ["id", "engine", "rule_id", "severity", "rung", "status", "description",
                   "reason", "extracted_value", "expected_value", "page_number", "clause_ref",
                   "recommended_action", "officer_decision", "officer_remarks",
                   "decided_by_username", "decided_at", "created_at", "document_filename", "doc_type"]
        writer.writerow(columns)
        for f in findings:
            writer.writerow([
                f.get("id"), f.get("engine"), f.get("rule_id"), f.get("severity"), f.get("rung"),
                f.get("status"), f.get("description"), f.get("reason"), f.get("extracted_value"),
                f.get("expected_value"), f.get("page_number"), f.get("clause_ref"),
                f.get("recommended_action"), f.get("officer_decision"), f.get("officer_remarks"),
                username_by_id.get(f.get("decided_by"), ""), f.get("decided_at"), f.get("created_at"),
                f.get("original_filename"), f.get("doc_type"),
            ])

        audit.append_entry(
            conn, actor=actor["username"], action="REPORT_GENERATED",
            record_type="application", record_id=str(application_id),
            payload={"report_type": "findings_csv", "application_code": application["application_code"],
                     "row_count": len(findings)},
        )
        conn.commit()
        return out.getvalue().encode("utf-8-sig")
    finally:
        conn.close()