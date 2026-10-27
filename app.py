import streamlit as st

from database.db import init_db, is_initialised, get_connection
from database.seed import seed_if_empty, seed_demo_applications_if_empty, seed_issuer_records_if_empty
from services.auth_service import authenticate, register_applicant, list_institutions_for_registration
from utils.config import APP_NAME
from utils import session
from utils import audit
from utils.theme import inject_theme, ladder_hero_html

st.set_page_config(page_title=APP_NAME, layout="wide", initial_sidebar_state="expanded")

inject_theme()

if not is_initialised():
    init_db()
seed_if_empty()
seed_demo_applications_if_empty()
seed_issuer_records_if_empty()


def login_screen():
    st.markdown(
        ladder_hero_html(
            APP_NAME,
            "AI-Powered Application Validation, Document Authentication and "
            "Regulatory Compliance Verification. Every claim climbs the ladder before it is trusted.",
        ),
        unsafe_allow_html=True,
    )

    login_tab, register_tab = st.tabs(["Log in", "New applicant? Create account"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", use_container_width=True)

        if submitted:
            user = authenticate(username, password)
            if user is None:
                st.error("Invalid username or password, or your account is awaiting administrator approval.")
            else:
                conn = get_connection()
                try:
                    audit.append_entry(
                        conn, actor=user["username"], action="LOGIN",
                        record_type="user", record_id=str(user["id"]),
                        payload={"role": user["role"]},
                    )
                finally:
                    conn.close()
                st.session_state["user"] = user
                st.rerun()

        with st.expander("Demo accounts (synthetic, for evaluation only)"):
            st.markdown(
                """
                | Role | Username | Password |
                |---|---|---|
                | Administrator | `admin` | `Admin@123` |
                | Scrutiny Officer | `officer1` | `Officer@123` |
                | Scrutiny Officer | `officer2` | `Officer@123` |
                | Applicant | `applicant1` | `Applicant@123` |
                """
            )

    with register_tab:
        st.subheader("Create an applicant account")
        st.info(
            "New accounts are pending until an administrator verifies the institution "
            "association and activates the account. You cannot sign in before approval."
        )
        institutions = list_institutions_for_registration()
        if not institutions:
            st.warning("No institutions are available. Ask an administrator to add the institution first.")
        else:
            institution_options = {
                f"{row['name']} ({row['institution_code']}) — {row.get('state') or 'State not set'}": row["id"]
                for row in institutions
            }
            with st.form("applicant_registration_form", clear_on_submit=True):
                reg_name = st.text_input("Full name")
                reg_username = st.text_input("Choose a username")
                reg_email = st.text_input("Email address")
                reg_password = st.text_input("Create password (minimum 6 characters)", type="password")
                reg_confirm = st.text_input("Confirm password", type="password")
                selected_institution = st.selectbox("Your institution", list(institution_options))
                accepted = st.checkbox(
                    "I confirm I am authorised to request applicant access for this institution."
                )
                reg_submit = st.form_submit_button("Request applicant access", use_container_width=True)

            if reg_submit:
                if reg_password != reg_confirm:
                    st.error("Passwords do not match.")
                elif not accepted:
                    st.error("Please confirm your institution association.")
                else:
                    try:
                        register_applicant(
                            username=reg_username, password=reg_password,
                            full_name=reg_name, email=reg_email,
                            institution_id=int(institution_options[selected_institution]),
                        )
                        st.success(
                            "Registration request submitted. An administrator must verify "
                            "your institution association and activate your account before login."
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"Registration could not be completed: {exc}")


def build_navigation(user):
    dashboard = st.Page("pages/dashboard.py", title="Dashboard", icon=":material/space_dashboard:", default=True)
    applications = st.Page("pages/applications.py", title="Applications", icon=":material/folder:")
    upload_validate = st.Page("pages/upload_validate.py", title="Upload & Validate", icon=":material/upload_file:")
    findings_page = st.Page("pages/findings.py", title="Findings", icon=":material/rule_folder:")
    verification = st.Page("pages/verification.py", title="Verification", icon=":material/fact_check:")
    review_workbench = st.Page(
        "pages/review_workbench.py",
        title="Review Workbench",
        icon=":material/task_alt:",
    )
    reports = st.Page("pages/reports.py", title="Reports", icon=":material/description:")
    audit_logs = st.Page("pages/audit_logs.py", title="Audit Logs", icon=":material/history:")
    administration = st.Page("pages/administration.py", title="Administration", icon=":material/admin_panel_settings:")

    nav = {"Overview": [dashboard], "Workflow": [applications]}

    if user["role"] in ("applicant", "officer"):
        nav["Workflow"].append(upload_validate)
    if user["role"] in ("officer", "admin"):
        nav["Workflow"].append(findings_page)
    if user["role"] == "officer":
        nav["Workflow"].append(verification)
    if user["role"] in ("officer", "admin"):
        # Phase 5 (Module J): application review workbench. Restricted to
        # officer/admin at the navigation level; the authoritative
        # restriction is enforced backend-side in review_service.py and
        # application_service.py via require_role(), as with every other
        # officer-only action in this prototype.
        nav["Workflow"].append(review_workbench)

    nav["Reports"] = [reports]

    governance = []
    if user["role"] in ("officer", "admin"):
        governance.append(audit_logs)
    if user["role"] == "admin":
        governance.append(administration)
    if governance:
        nav["Governance"] = governance

    return st.navigation(nav)


def render_sidebar_identity(user):
    with st.sidebar:
        st.markdown("---")
        st.markdown(f"**{user['full_name']}**")
        st.caption(f"Role: {user['role'].capitalize()}")
        if st.button("Log out", use_container_width=True):
            # Phase 5 (Module J): audit logout before clearing session state,
            # while we still have the authenticated user's identity on hand.
            conn = get_connection()
            try:
                audit.append_entry(
                    conn,
                    actor=user["username"],
                    action="LOGOUT",
                    record_type="user",
                    record_id=str(user["id"]),
                    payload={},
                )
            finally:
                conn.close()
            session.logout()
            st.rerun()


user = session.get_current_user()

if user is None:
    login_screen()
else:
    render_sidebar_identity(user)
    pg = build_navigation(user)
    pg.run()