"""Module D/E: findings listing and filtering.

Findings are produced by the deterministic rule engine
(services.validation_engine). This page is read-only; officer
confirm/dismiss/decision actions are implemented in a later phase
(Module J, Phase 5).
"""
import streamlit as st

from services import application_service, validation_engine
from utils.session import require_role_ui

user = require_role_ui(("officer", "admin"))

st.title("🔍 Findings")
st.caption(
    "Findings are deterministic rule-engine results. They are advisory only -- "
    "no finding here is proof of fraud, and signature-related findings only "
    "indicate whether verification has run yet, not a verification result."
)

applications = application_service.list_applications(user)
app_options = {"(All applications)": None}
app_options.update({a["application_code"]: a["id"] for a in applications})

col1, col2, col3, col4 = st.columns(4)
with col1:
    selected_app_label = st.selectbox("Application", list(app_options.keys()))
with col2:
    severity_filter = st.selectbox("Severity", ["(All)", "low", "medium", "high", "critical"])
with col3:
    status_filter = st.selectbox("Status", ["(All)", "open"])
with col4:
    rule_id_filter = st.text_input("Rule ID contains")

application_id = app_options[selected_app_label]
severity = None if severity_filter == "(All)" else severity_filter
status = None if status_filter == "(All)" else status_filter

findings = validation_engine.list_findings(
    user, application_id=application_id, severity=severity, status=status,
)
if rule_id_filter:
    findings = [f for f in findings if rule_id_filter.lower() in (f["rule_id"] or "").lower()]

st.divider()
st.caption(f"{len(findings)} finding(s) match the current filters.")

if not findings:
    st.info("No findings match the current filters. Run validation from the Applications page.")
else:
    SEVERITY_COLORS = {
        "low": "#64748b", "medium": "#d97706", "high": "#dc2626", "critical": "#991b1b",
    }
    for f in findings:
        color = SEVERITY_COLORS.get(f["severity"], "#64748b")
        st.markdown(
            f"""<div class="evidence-card" style="border-left-color:{color};">
<strong>{f['rule_id']}</strong> — {f['description']}<br/>
<span style="color:#475569;">Application: {f['application_code']} ({f['institution_name']}) |
Document: {f['original_filename'] or '—'} ({f['doc_type'] or '—'}) |
Severity: {f['severity']} | Status: {f['status']}</span>
</div>""",
            unsafe_allow_html=True,
        )
        with st.expander("Details"):
            st.markdown(f"**Reason:** {f['reason']}")
            st.markdown(f"**Expected value:** {f['expected_value']}")
            st.markdown(f"**Extracted/observed value:** {f['extracted_value']}")
            st.markdown(f"**Page number:** {f['page_number'] if f['page_number'] else 'N/A'}")
            st.markdown(f"**Clause reference (illustrative, not verified):** {f['clause_ref'] or 'N/A'}")
            st.markdown(f"**Recommended action:** {f['recommended_action']}")
            st.caption(
                f"Rule pack version: {f['rule_pack_version']} | Engine: {f['engine']} | "
                f"Recorded: {f['created_at']}"
            )