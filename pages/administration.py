"""Administration: user management; rule packs (Phase 3); synthetic
demo data reset (Phase 7, Module K)."""
import streamlit as st

from services.auth_service import list_users, create_user, activate_user, PermissionDenied
from database.seed import reset_synthetic_demo_data, SCENARIO_CATALOG
from utils.session import require_role_ui

user = require_role_ui(["admin"])

st.title("Administration")

tab_users, tab_rules, tab_demo = st.tabs(
    ["Users & Roles", "Rule Packs (Phase 3)", "Demo Data (Phase 7)"]
)

with tab_users:
    st.subheader("Existing users")
    try:
        users = list_users(user)
    except PermissionDenied as e:
        st.error(str(e))
        users = []

    if users:
        st.dataframe(users, use_container_width=True, hide_index=True)
        pending_users = [u for u in users if u.get("role") == "applicant" and not u.get("is_active")]
        if pending_users:
            st.subheader("Pending applicant registrations")
            st.caption("Verify the applicant's authority to represent the selected institution before activation.")
            for pending in pending_users:
                cols = st.columns([3, 2, 1])
                cols[0].write(f"**{pending['full_name']}** (@{pending['username']})")
                cols[1].caption(f"Institution ID: {pending.get('institution_id') or 'Not assigned'}")
                if cols[2].button("Activate", key=f"activate_user_{pending['id']}"):
                    try:
                        activate_user(user, int(pending["id"]))
                        st.success(f"Activated {pending['username']}.")
                        st.rerun()
                    except (PermissionDenied, ValueError) as exc:
                        st.error(str(exc))

    st.divider()
    st.subheader("Create a new user")
    with st.form("create_user_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            new_username = st.text_input("Username")
            new_full_name = st.text_input("Full name")
            new_role = st.selectbox("Role", ["applicant", "officer", "admin"])
        with c2:
            new_password = st.text_input("Temporary password", type="password")
            new_email = st.text_input("Email (optional)")
        submitted = st.form_submit_button("Create user", type="primary")

        if submitted:
            if not new_username or not new_password or not new_full_name:
                st.error("Username, full name and password are required.")
            else:
                try:
                    create_user(
                        actor=user,
                        username=new_username.strip(),
                        password=new_password,
                        full_name=new_full_name.strip(),
                        role=new_role,
                        email=(new_email.strip() or None),
                    )
                    st.success(f"User '{new_username}' created.")
                    st.rerun()
                except PermissionDenied as e:
                    st.error(str(e))
                except ValueError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Could not create user (username may already exist): {e}")

with tab_rules:
    st.info(
        "Versioned YAML rule packs, maker-checker approval and rule-change audit "
        "logging are implemented in **Phase 3**."
    )

with tab_demo:
    st.subheader("Synthetic demo dataset")
    st.caption(
        "All applications, institutions and certificates listed below are "
        "entirely FICTIONAL, generated for demonstration purposes only. "
        "They are flagged `is_synthetic = 1` in the database and are the "
        "only rows this reset action will ever touch."
    )

    st.dataframe(
        [
            {
                "Scenario": s["scenario_tag"],
                "Institution": s["institution"],
                "Type": "Clean" if s["kind"] == "clean" else "Defective",
                "Summary": s["summary"],
            }
            for s in SCENARIO_CATALOG
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.warning(
        "Resetting will permanently delete ALL synthetic demo applications, "
        "their documents, findings and mock issuer records, then recreate a "
        "fresh copy of the full scenario set above. This action is scoped "
        "strictly to synthetic (`is_synthetic = 1`) rows -- it will NEVER "
        "delete real user accounts, institutions, or any non-synthetic "
        "application. The tamper-evident audit log is never deleted from; "
        "this reset is itself recorded as a new audit entry."
    )
    confirm = st.checkbox("I understand this will delete and recreate the synthetic demo dataset.")
    if st.button("Reset synthetic demo data", type="primary", disabled=not confirm):
        try:
            result = reset_synthetic_demo_data(user)
            st.success(
                f"Removed {result['applications_removed']} synthetic application(s) "
                f"and {result['issuer_records_removed']} synthetic issuer record(s). "
                f"A fresh copy of {len(SCENARIO_CATALOG)} demo scenarios has been seeded."
            )
            st.rerun()
        except PermissionDenied as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Reset failed: {e}")