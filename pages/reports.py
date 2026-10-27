"""Module I: downloadable validation reports and applicant feedback
(Phase 6).

Report CONTENT restriction between the officer/admin report and the
applicant feedback report is decided entirely inside
services.report_service, based on the logged-in user's role -- never
by a flag this page passes in. This page only decides which buttons
to show; the backend is the actual security boundary (Phase 6,
Section B requirement).

Every report is generated on demand, directly from the records
currently stored in the database -- nothing here is pre-generated,
cached across sessions, or fabricated.
"""
import streamlit as st

from services import application_service, report_service
from services.auth_service import PermissionDenied
from utils.session import require_login

user = require_login()

st.title("\U0001F4C4 Reports")
st.caption(
    "Reports are generated on demand from the records currently stored in the "
    "database. They are not pre-generated or cached, so they always reflect the "
    "latest findings, verification results and officer decisions on file."
)

try:
    applications = application_service.list_applications(user)
except Exception as exc:
    st.error(
        "Could not load your applications. Please try reloading the page. "
        f"(Details: {exc})"
    )
    st.stop()

if not applications:
    st.info(
        "No applications are visible to you yet. "
        + ("Create one from the Applications page to get started."
           if user["role"] in ("applicant", "admin")
           else "No applications have been submitted yet.")
    )
    st.stop()

code_to_id = {a["application_code"]: a["id"] for a in applications}
selected_code = st.selectbox("Select an application", list(code_to_id.keys()))
application_id = code_to_id[selected_code]

st.divider()

if user["role"] in ("officer", "admin"):
    st.subheader("Officer / administrator report")
    st.caption(
        "Includes rule-engine findings, PDF forensics and signature-check results, "
        "mock issuer-verification results (clearly labelled as synthetic -- never a "
        "real government database lookup), officer decisions and remarks, and full "
        "action history."
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("\U0001F9FE Generate PDF report", key="gen_officer_pdf", use_container_width=True):
            with st.spinner("Generating PDF report..."):
                try:
                    pdf_bytes = report_service.generate_officer_pdf_report(user, application_id)
                except report_service.ReportUnavailableError as exc:
                    st.error(
                        f"Could not generate the report: {exc}\n\n"
                        "If this message mentions a missing package, install it "
                        "(see the README) and try again."
                    )
                except PermissionDenied as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(
                        "An unexpected error occurred while generating the report. "
                        f"Please try again or contact an administrator. (Details: {exc})"
                    )
                else:
                    st.session_state["_officer_pdf_bytes"] = pdf_bytes
                    st.session_state["_officer_pdf_code"] = selected_code
                    st.success("Report generated.")

        if (st.session_state.get("_officer_pdf_code") == selected_code
                and "_officer_pdf_bytes" in st.session_state):
            st.download_button(
                "\u2B07\uFE0F Download officer PDF report",
                data=st.session_state["_officer_pdf_bytes"],
                file_name=f"{selected_code}_officer_report.pdf",
                mime="application/pdf",
                key="dl_officer_pdf",
                use_container_width=True,
            )

    with col2:
        if st.button("\U0001F4CA Generate CSV findings export", key="gen_csv", use_container_width=True):
            with st.spinner("Generating CSV export..."):
                try:
                    csv_bytes = report_service.generate_findings_csv(user, application_id)
                except report_service.ReportUnavailableError as exc:
                    st.error(str(exc))
                except PermissionDenied as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(
                        "An unexpected error occurred while generating the CSV export. "
                        f"Please try again or contact an administrator. (Details: {exc})"
                    )
                else:
                    st.session_state["_csv_bytes"] = csv_bytes
                    st.session_state["_csv_code"] = selected_code
                    st.success("CSV export generated.")

        if (st.session_state.get("_csv_code") == selected_code
                and "_csv_bytes" in st.session_state):
            st.download_button(
                "\u2B07\uFE0F Download findings CSV",
                data=st.session_state["_csv_bytes"],
                file_name=f"{selected_code}_findings.csv",
                mime="text/csv",
                key="dl_csv",
                use_container_width=True,
            )

    st.divider()

st.subheader("Applicant feedback report")
st.caption(
    "A restricted report suitable for sharing with the applicant institution. It "
    "includes only completeness, consistency and expiry findings produced by the "
    "deterministic rule engine. Internal forensic analysis, raw issuer-verification "
    "detail, officer notes and administrative information are excluded from this "
    "report -- this restriction is enforced in the backend, not merely hidden on "
    "this page."
)

if st.button("\U0001F4C4 Generate applicant feedback PDF", key="gen_applicant_pdf"):
    with st.spinner("Generating applicant feedback report..."):
        try:
            pdf_bytes = report_service.generate_applicant_pdf_report(user, application_id)
        except report_service.ReportUnavailableError as exc:
            st.error(
                f"Could not generate the report: {exc}\n\n"
                "If this message mentions a missing package, install it "
                "(see the README) and try again."
            )
        except PermissionDenied as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(
                "An unexpected error occurred while generating the report. "
                f"Please try again or contact an administrator. (Details: {exc})"
            )
        else:
            st.session_state["_applicant_pdf_bytes"] = pdf_bytes
            st.session_state["_applicant_pdf_code"] = selected_code
            st.success("Applicant feedback report generated.")

if (st.session_state.get("_applicant_pdf_code") == selected_code
        and "_applicant_pdf_bytes" in st.session_state):
    st.download_button(
        "\u2B07\uFE0F Download applicant feedback PDF",
        data=st.session_state["_applicant_pdf_bytes"],
        file_name=f"{selected_code}_applicant_feedback.pdf",
        mime="application/pdf",
        key="dl_applicant_pdf",
    )