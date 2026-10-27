"""Module C: multi-PDF upload and text/field extraction.

Backend permission and institution-ownership checks live in
services/application_service.py -- this page only arranges the UI.
"""
import streamlit as st

from services import application_service, qr_service
from services.auth_service import PermissionDenied
from utils.file_safety import UploadValidationError
from utils.session import require_role_ui
from models.enums import DEFAULT_CHECKLIST_BY_CATEGORY, DocType

user = require_role_ui(("applicant", "officer"))

st.title("📤 Upload & Validate")
st.caption(
    "Upload PDF evidence against an existing application. Text extraction runs "
    "automatically (native PDF text first, OCR fallback if available). The "
    "rules engine and evidence ladder are implemented in Phases 3-4."
)

applications = application_service.list_applications(user)

if not applications:
    st.info("No applications available. Create one on the Applications page first.")
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
    f"**Status:** {app['status']}"
)

st.markdown("#### Checklist status")
checklist_doc_types = [c["doc_type"] for c in detail["checklist"]] or \
    DEFAULT_CHECKLIST_BY_CATEGORY.get(app["category"], [])

if detail["checklist"]:
    cols = st.columns(len(detail["checklist"]))
    for col, item in zip(cols, detail["checklist"]):
        with col:
            st.metric(item["doc_type"], "Satisfied" if item["satisfied"] else "Missing")

st.divider()
st.markdown("#### Upload document(s)")

doc_type_options = checklist_doc_types + [
    d.value for d in DocType if d.value not in checklist_doc_types
]
doc_type = st.selectbox("Document type for this upload", doc_type_options)

uploaded_files = st.file_uploader(
    "Select one or more PDF files", type=["pdf"], accept_multiple_files=True
)

if uploaded_files and st.button("Upload and extract", use_container_width=True):
    for uploaded_file in uploaded_files:
        file_bytes = uploaded_file.getvalue()
        st.markdown(f"**{uploaded_file.name}**")
        try:
            result = application_service.add_document(
                user, application_id, doc_type, uploaded_file.name, file_bytes
            )
        except UploadValidationError as exc:
            st.error(f"Rejected: {exc}")
            continue
        except PermissionDenied as exc:
            st.error(str(exc))
            continue
        except ValueError as exc:
            st.error(str(exc))
            continue

        status = result["extraction_status"]
        if status == "native":
            st.success("Native PDF text extracted successfully.")
        elif status == "ocr":
            st.success("Scanned document detected -- OCR extraction succeeded.")
        elif status in ("ocr_unavailable", "ocr_failed"):
            st.warning(result["warning"])
        else:
            st.info("No extractable text was found in this document.")

        if result["duplicates"]:
            others = ", ".join(
                f"{d['application_code']}/{d['original_filename']}" for d in result["duplicates"]
            )
            st.warning(
                f"⚠️ This file's SHA-256 fingerprint matches already-uploaded document(s): "
                f"{others}. This is flagged for awareness only -- it is not, by itself, "
                f"proof of wrongdoing."
            )

        if result["fields_found"]:
            with st.expander(f"Extracted fields from {uploaded_file.name}"):
                for f in result["fields_found"]:
                    st.markdown(
                        f"- `{f['field_name']}` = \"{f['field_value']}\" "
                        f"(page {f['page_number']}, confidence {f['confidence']:.2f})"
                    )
        else:
            st.caption("No recognisable fields were extracted from this document (not fabricated).")

        qr_hits = qr_service.extract_qr_payloads_from_bytes(file_bytes)
        if qr_hits:
            pages = ", ".join(str(h["page_number"]) for h in qr_hits)
            st.caption(
                f"🔲 {len(qr_hits)} QR code(s) detected in this document (page(s): {pages}). "
                f"This is a local preview only -- it does not verify, follow, or visit any "
                f"URL automatically."
            )
            if user["role"] in ("officer", "admin"):
                st.caption("Run full QR verification from the Verification page.")
        elif not qr_service.QR_DECODE_AVAILABLE:
            st.caption(
                "QR code detection is unavailable in this environment "
                "(pyzbar/Pillow not installed)."
            )

    st.info("Visit the Applications page to see the updated checklist and document list.")