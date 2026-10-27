
"""Audit log viewer and hash-chain verification."""
import pandas as pd
import streamlit as st

from database.db import get_connection
from utils.audit import verify_chain, get_entries
from utils.session import require_role_ui

user = require_role_ui(["officer", "admin"])

st.title("Audit Logs")
st.caption(
    "Append-only, hash-chained event log. Each entry stores the previous "
    "entry's hash, so edits or deletions become detectable. This is "
    "tamper-evident, not immutable: an administrator with direct database "
    "access could still rebuild the chain from scratch."
)

conn = get_connection()
try:
    ok, broken_seq = verify_chain(conn)
    entries = get_entries(conn, limit=500)
finally:
    conn.close()

if ok:
    st.success("Chain integrity check: VALID")
else:
    st.error(
        f"Chain integrity check: BROKEN at entry #{broken_seq}"
    )

if entries:
    df = pd.DataFrame([dict(e) for e in entries])
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info(
        "No audit events recorded yet. Log in or out to generate some."
    )

st.divider()
st.subheader("Integrity self-test")
st.caption(
    "For demonstration only: directly edits the most recent stored "
    "audit row to show that verify_chain detects the modification."
)

if user["role"] != "admin":
    st.info(
        "This destructive demonstration action is restricted to "
        "administrators. Officers can view the audit log and its "
        "integrity status, but cannot trigger direct database "
        "tampering from this page."
    )
else:
    if st.button("Simulate tampering with the most recent entry"):
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT seq FROM audit_log "
                "ORDER BY seq DESC LIMIT 1"
            ).fetchone()

            if row:
                conn.execute(
                    "UPDATE audit_log SET action = ? WHERE seq = ?",
                    ("TAMPERED_ACTION", row["seq"]),
                )
                conn.commit()
                st.warning(
                    f"Entry #{row['seq']} was modified directly "
                    "in the database. Reload this page."
                )
            else:
                st.info("No entries to tamper with yet.")
        finally:
            conn.close()
