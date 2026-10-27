import streamlit as st


def get_current_user():
    return st.session_state.get("user")


def require_login():
    """Stops the page if not logged in; otherwise returns the current
    user dict so callers can do `user = require_login()`."""
    user = get_current_user()
    if user is None:
        st.warning("Please log in to continue.")
        st.stop()
    return user


def require_role_ui(allowed_roles):
    """UI-level convenience gate only. NOT the authoritative permission check --
    the authoritative check is services.auth_service.require_role, enforced
    in the backend regardless of what the UI shows or hides."""
    user = require_login()
    if user["role"] not in allowed_roles:
        st.error("You do not have permission to view this page.")
        st.stop()
    return user


def logout():
    if "user" in st.session_state:
        del st.session_state["user"]