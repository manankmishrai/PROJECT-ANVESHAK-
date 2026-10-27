"""Mock issuer & QR verification workbench (Module G + Module D QR).

Everything displayed here is produced by SYNTHETIC, LOCAL adapters
(services/issuer_service.py, services/qr_service.py). Nothing on this
page represents, or should be read as, a connection to any real
government, AICTE, fire department, or university verification service.
"""
import json

import pandas as pd
import streamlit as st

from models.enums import VerificationStatus
from services import application_service, issuer_service, qr_service, validation_engine
from services.auth_service import PermissionDenied
from utils.session import require_role_ui

user = require_role_ui(["officer", "admin"])

st.title("🔎 Verification")
st.warning(
    "All issuer records and verification results on this page are "
    "**SYNTHETIC / MOCK demonstration data**. This prototype never contacts, "
    "represents, or implies a connection to any real government, AICTE, "
    "fire department, or university verification service."
)

applications = application_service.list_applications(user)
if not applications:
    st.info("No applications available yet.")
    st.stop()

code_to_id = {a["application_code"]: a["id"] for a in applications}
selected_code = st.selectbox("Application", list(code_to_id.keys()))
application_id = code_to_id[selected_code]

try:
    detail = application_service.get_application_detail(user, application_id)
except PermissionDenied as exc:
    st.error(str(exc))
    st.stop()

app = detail["application"]
st.markdown(
    f"**Institution:** {app['institution_name']} | **Category:** {app['category']} | "
    f"**Priority:** {app['priority'] or '-'}"
)

st.divider()
st.markdown("#### Run verification")
col1, col2 = st.columns(2)

with col1:
    st.caption(
        "Mock issuer-record lookup (Module G): checks each document's "
        "extracted certificate number and institution name against a "
        "small, fictional local issuer database."
    )
    if st.button("▶ Run issuer verification now", key=f"run_issuer_{application_id}"):
        try:
            results = issuer_service.run_issuer_verification(user, application_id)
            st.success(f"Issuer verification complete: {len(results)} result(s).")
            st.rerun()
        except PermissionDenied as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Issuer verification failed: {exc}")

with col2:
    st.caption(
        "QR code verification (Module D): extracts QR codes from uploaded "
        "PDFs and cross-checks their content against printed values and "
        "against QR codes found on other documents (replay detection)."
    )
    if not qr_service.QR_DECODE_AVAILABLE:
        st.info(
            "QR decoding is UNAVAILABLE in this environment (pyzbar/Pillow "
            "not installed or failed to import). Running this check will "
            "honestly record an explicit QR-UNAVAILABLE finding rather than "
            "silently skipping or guessing."
        )
    if st.button("▶ Run QR verification now", key=f"run_qr_{application_id}"):
        try:
            finding_ids = qr_service.run_qr_verification(user, application_id)
            st.success(f"QR verification complete: {len(finding_ids)} finding(s).")
            st.rerun()
        except PermissionDenied as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"QR verification failed: {exc}")

st.divider()
st.markdown("#### Issuer verification requests")
st.caption(
    "One row per document checked against the mock issuer database. The six "
    "possible statuses are defined in models.enums.VerificationStatus."
)

requests = issuer_service.list_verification_requests(user, application_id)
if not requests:
    st.caption("No issuer verification requests recorded yet for this application.")
else:
    status_labels = {
        VerificationStatus.PENDING.value: "⏳ Verification pending",
        VerificationStatus.VERIFIED.value: "✅ Verified (mock issuer)",
        VerificationStatus.MISMATCH.value: "❌ Mismatch detected",
        VerificationStatus.EXPIRED.value: "⚠️ Expired",
        VerificationStatus.SOURCE_UNAVAILABLE.value: "❔ Source unavailable",
        VerificationStatus.MANUAL_REVIEW.value: "🧑‍⚖️ Manual review required",
    }
    for req in requests:
        label = status_labels.get(req["status"], req["status"])
        with st.expander(
            f"{label} -- {req['document_doc_type']} (document id {req['document_id']}, "
            f"cert: {req['certificate_number'] or 'N/A'})"
        ):
            st.caption(
                f"Issuer type: {req['issuer_type']} | Source: {req['source']} "
                f"(mock/local adapter) | Requested: {req['requested_at']} | "
                f"Responded: {req['responded_at'] or 'N/A'}"
            )
            if req["response_json"]:
                try:
                    response = json.loads(req["response_json"])
                    st.markdown(f"**Reason:** {response.get('reason', 'N/A')}")
                    if response.get("matched_record"):
                        st.caption(f"Matched mock issuer record: {response['matched_record']}")
                except (json.JSONDecodeError, TypeError):
                    st.caption("Could not parse stored response.")

            if req["manual_notes"]:
                st.info(f"**Officer manual notes:** {req['manual_notes']}")

            if req["status"] in (
                VerificationStatus.MANUAL_REVIEW.value,
                VerificationStatus.SOURCE_UNAVAILABLE.value,
            ):
                st.markdown("**Manual verification workflow**")
                st.caption(
                    "This tool could not automatically resolve this case. An officer "
                    "may record the outcome of a manual/out-of-band check here. This "
                    "NEVER fabricates an automated result -- it only records what a "
                    "human officer attests to."
                )
                with st.form(f"manual_note_form_{req['id']}"):
                    notes = st.text_area("Manual review notes", key=f"notes_{req['id']}")
                    resolved = st.selectbox(
                        "Manually resolved status (optional -- leave unchanged to just save notes)",
                        ["(no change)"] + [s.value for s in VerificationStatus],
                        key=f"resolved_{req['id']}",
                    )
                    save = st.form_submit_button("Save manual review")
                if save:
                    try:
                        issuer_service.record_manual_verification_note(
                            user, req["id"], notes,
                            None if resolved == "(no change)" else resolved,
                        )
                        st.success("Manual review recorded.")
                        st.rerun()
                    except PermissionDenied as exc:
                        st.error(str(exc))
                    except ValueError as exc:
                        st.error(str(exc))

st.divider()
st.markdown("#### QR verification findings")
all_findings = validation_engine.list_findings(user, application_id=application_id)
qr_findings = [f for f in all_findings if f["engine"] == "qr_service"]
if not qr_findings:
    st.caption("No QR verification findings recorded yet for this application.")
else:
    qr_df = pd.DataFrame(qr_findings)[
        ["rule_id", "severity", "rung", "status", "description", "recommended_action"]
    ]
    st.dataframe(qr_df, use_container_width=True, hide_index=True)