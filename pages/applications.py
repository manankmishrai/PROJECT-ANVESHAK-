"""Module B: application intake and listing.

Applicants may create applications only for their own institution and
may only see applications belonging to that institution. Officers and
administrators see every application. These rules are enforced in
services/application_service.py, not just by what this page displays.
"""
import datetime

import pandas as pd
import streamlit as st

from services import application_service, validation_engine, forensics_engine, issuer_service, qr_service
from services.auth_service import PermissionDenied
from utils.session import require_login
from models.enums import ApplicationCategory

user = require_login()

st.title("🗂️ Applications")

if user["role"] in ("applicant", "admin"):
    with st.expander("➕ Create a new application", expanded=False):
        institutions = application_service.list_institutions()
        inst_options = {f"{i['name']} ({i['institution_code']})": i["id"] for i in institutions}

        use_new_institution = st.checkbox("Register a new institution instead of selecting one")

        with st.form("create_application_form"):
            if use_new_institution or not inst_options:
                new_name = st.text_input("Institution name")
                new_code = st.text_input("Institution ID / code (e.g. INST-004)")
                new_address = st.text_input("Address (optional)")
                new_state = st.text_input("State (optional)")
                selected_institution_id = None
            else:
                choice = st.selectbox("Institution", list(inst_options.keys()))
                selected_institution_id = inst_options[choice]

            category = st.selectbox(
                "Category",
                [c.value for c in ApplicationCategory],
                help="Only Extension of Approval (EoA) is implemented in this prototype.",
            )
            academic_year = st.text_input("Academic year (e.g. 2025-26)")
            submission_date = st.date_input("Submission date", value=datetime.date.today())

            submitted = st.form_submit_button("Create application", use_container_width=True)

        if submitted:
            try:
                if use_new_institution or not inst_options:
                    institution_id = application_service.get_or_create_institution(
                        new_name, new_code, new_address or None, new_state or None
                    )
                else:
                    institution_id = selected_institution_id

                app_id = application_service.create_application(
                    user, institution_id, category, academic_year.strip(),
                    submission_date.isoformat(),
                )
                st.success(f"Application created (internal id {app_id}).")
                st.rerun()
            except PermissionDenied as exc:
                st.error(str(exc))
            except ValueError as exc:
                st.error(str(exc))

st.divider()
st.subheader("Your applications" if user["role"] == "applicant" else "All applications")

applications = application_service.list_applications(user)

if not applications:
    st.info("No applications visible yet.")
else:
    df = pd.DataFrame(applications)[
        ["application_code", "institution_name", "category", "academic_year",
         "status", "priority", "submission_date", "is_synthetic", "scenario_tag"]
    ]
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Application detail")
    code_to_id = {a["application_code"]: a["id"] for a in applications}
    selected_code = st.selectbox("Select an application to inspect", list(code_to_id.keys()))

    if selected_code:
        try:
            detail = application_service.get_application_detail(user, code_to_id[selected_code])
        except PermissionDenied as exc:
            st.error(str(exc))
        else:
            app = detail["application"]
            cols = st.columns(4)
            cols[0].metric("Status", app["status"])
            cols[1].metric("Priority", app["priority"] or "-")
            cols[2].metric("Category", app["category"])
            cols[3].metric("Academic year", app["academic_year"])

            if app["is_synthetic"]:
                st.warning(
                    f"This is SYNTHETIC demonstration data (scenario: "
                    f"{app['scenario_tag'] or 'unlabeled'}). Not a real application."
                )

            st.markdown(f"**Institution:** {app['institution_name']} ({app['institution_code']})")

            st.markdown("#### Document checklist")
            st.caption(
                "This checklist is an illustrative demonstration list, not a verified "
                "official AICTE/APH document requirement."
            )
            if not detail["checklist"]:
                st.caption("No checklist items defined for this category.")
            else:
                for item in detail["checklist"]:
                    icon = "✅" if item["satisfied"] else "⬜"
                    required = "required" if item["required"] else "optional"
                    st.markdown(f"{icon} `{item['doc_type']}` ({required})")

            st.markdown("#### Uploaded documents")
            if not detail["documents"]:
                st.caption("No documents uploaded yet. Use the Upload & Validate page.")
            for doc in detail["documents"]:
                status_icon = {
                    "native": "📄", "ocr": "🔎", "ocr_unavailable": "⚠️",
                    "ocr_failed": "⚠️", "empty": "❔",
                }.get(doc["extraction_status"], "❔")
                with st.expander(
                    f"{status_icon} {doc['doc_type']} -- {doc['original_filename']} "
                    f"(status: {doc['extraction_status']})"
                ):
                    st.caption(f"SHA-256: `{doc['sha256']}`")
                    st.caption(
                        f"Pages: {doc['page_count']} | Native text: "
                        f"{'yes' if doc['is_native_text'] else 'no'} | "
                        f"OCR used: {'yes' if doc['ocr_used'] else 'no'} | "
                        f"Uploaded: {doc['upload_date']}"
                    )

                    if doc["fields"]:
                        st.markdown("**Extracted fields:**")
                        for f in doc["fields"]:
                            st.markdown(
                                f"- `{f['field_name']}` = \"{f['field_value']}\" "
                                f"(page {f['page_number']}, confidence {f['confidence']:.2f})"
                            )
                    else:
                        st.caption("No fields could be extracted from this document (not fabricated).")

                    if doc["pages_text"]:
                        with st.popover("View extracted text"):
                            for i, page_text in enumerate(doc["pages_text"], start=1):
                                st.markdown(f"**Page {i}:**")
                                st.text(page_text if page_text.strip() else "(no text extracted on this page)")
                    else:
                        st.caption("Extracted text is not available for this document.")

            if user["role"] in ("officer", "admin"):
                st.divider()
                st.markdown("#### Validation (Module D -- deterministic rules)")
                st.caption(
                    "Runs the deterministic rule engine against this application's stored "
                    "data. Findings are advisory only -- see the Findings page for the full "
                    "filterable list. Rules are illustrative/demonstration only."
                )
                if st.button("▶ Run validation now", key=f"run_validation_{app['id']}"):
                    try:
                        finding_ids = validation_engine.run_validation(user, app["id"])
                        st.success(f"Validation complete: {len(finding_ids)} finding(s) generated.")
                        st.rerun()
                    except PermissionDenied as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"Validation failed: {exc}")

                st.markdown("#### PDF integrity & signature forensics (Module F)")
                st.caption(
                    "Runs PDF metadata inspection and pyHanko-based digital signature "
                    "verification where available. A valid signature proves content has not "
                    "changed since signing -- it does NOT prove the document's claims are "
                    "factually true. If pyHanko is not installed, this honestly reports "
                    "'verification unavailable' rather than a false pass/fail."
                )
                if st.button("🔍 Run signature & metadata checks now", key=f"run_forensics_{app['id']}"):
                    try:
                        finding_ids = forensics_engine.run_forensics(user, app["id"])
                        st.success(f"Forensics check complete: {len(finding_ids)} finding(s) generated.")
                        st.rerun()
                    except PermissionDenied as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"Forensics check failed: {exc}")

                st.markdown("#### Mock issuer verification (Module G)")
                st.caption(
                    "Checks each document's extracted certificate number and institution "
                    "name against a small, SYNTHETIC/mock local issuer database -- never a "
                    "real government or AICTE service. See the Verification page for the "
                    "full request history and manual-review workflow."
                )
                if st.button("📇 Run issuer verification now", key=f"run_issuer_{app['id']}"):
                    try:
                        results = issuer_service.run_issuer_verification(user, app["id"])
                        st.success(f"Issuer verification complete: {len(results)} result(s) generated.")
                        st.rerun()
                    except PermissionDenied as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"Issuer verification failed: {exc}")

                st.markdown("#### QR code verification (Module D)")
                if not qr_service.QR_DECODE_AVAILABLE:
                    st.caption(
                        "⚠️ QR decoding is unavailable in this environment -- running this "
                        "check will honestly record an explicit QR-UNAVAILABLE finding "
                        "rather than silently skipping or guessing."
                    )
                else:
                    st.caption(
                        "Extracts QR codes from uploaded PDFs and cross-checks their content "
                        "against printed values and against QR codes on other documents "
                        "(replay detection). This tool never automatically visits any URL "
                        "found in an uploaded document."
                    )
                if st.button("🔲 Run QR verification now", key=f"run_qr_{app['id']}"):
                    try:
                        finding_ids = qr_service.run_qr_verification(user, app["id"])
                        st.success(f"QR verification complete: {len(finding_ids)} finding(s) generated.")
                        st.rerun()
                    except PermissionDenied as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"QR verification failed: {exc}")

                existing_findings = validation_engine.list_findings(user, application_id=app["id"])
                if existing_findings:
                    severity_counts = {}
                    engine_counts = {}
                    for f in existing_findings:
                        severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1
                        engine_counts[f["engine"]] = engine_counts.get(f["engine"], 0) + 1
                    st.caption(f"{len(existing_findings)} finding(s) currently on record, by engine:")
                    st.write(engine_counts)
                    st.caption("By severity:")
                    st.write(severity_counts)
                else:
                    st.caption("No findings on record yet for this application.")