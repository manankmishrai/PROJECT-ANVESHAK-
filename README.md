# Evidence-Ladder Scrutiny Copilot

A local prototype for the Smart India Hackathon (SIH) that helps
scrutiny officers review institution approval-related applications and
supporting documents. It brings document intake, rule-based checks,
evidence levels, verification results, officer decisions, and reports
into one Streamlit application.

> **Prototype only:** This project is intended for demonstration and
> evaluation. It is not an official AICTE service and must not be used
> to make real regulatory decisions.

## What the application does

-   Authenticates users and applies role-based access for
    administrators, scrutiny officers, and applicants.
-   Creates applications and stores uploaded PDFs and extracted
    information.
-   Extracts native PDF text and can use Tesseract OCR as an optional
    fallback for scanned documents.
-   Runs versioned YAML validation rules and records explainable
    findings.
-   Uses an Evidence-Ladder model to distinguish unverified information,
    anomalies, consistency, digital-signature results, and
    source-verification results.
-   Inspects PDF metadata and digital signatures when the required
    libraries and configuration are available.
-   Demonstrates issuer and QR-code checks using **synthetic/mock
    data**, not real government systems.
-   Provides an officer dashboard and review workbench, including
    decisions and remarks.
-   Generates officer reports, applicant feedback reports, and CSV
    findings exports.
-   Records important actions in a hash-chained audit log.

## Important limitations

Please read these points before presenting the prototype:

-   **Mock verification:** Issuer records and responses are fictional.
    The application does not connect to AICTE or any live government,
    university, or department database.
-   **Illustrative rules:** Rule references, similarity thresholds, SLA
    values, and checklist content are demonstration values until
    verified against the applicable official handbook and requirements.
-   **Human review:** Automated findings are advisory. Weak anomaly
    signals alone must not be treated as proof of forgery. Final adverse
    decisions require an authorised human reviewer.
-   **Digital signatures:** A cryptographically valid signature does not
    prove that every statement in a document is factually correct.
    Trust-chain validation depends on the available trust configuration.
-   **OCR:** OCR requires a working Tesseract installation. If it is
    unavailable, scanned documents may not yield usable text; the
    application should report that limitation rather than invent
    extracted values.
-   **QR decoding:** QR checks depend on optional libraries and the
    platform's decoding support. The current allowlist is synthetic and
    is not a real issuer integration.
-   **PDF forensics:** The prototype checks selected metadata and
    structural signals. It does not implement every possible
    hidden-text, visual-content, or forensic analysis.
-   **Report fonts:** The current ReportLab setup may not render
    non-Latin scripts correctly.
-   **Security:** This is a local academic prototype, not a production
    deployment, penetration test, or security certification. Login rate
    limiting and other production controls remain future work.
-   **Audit log:** The audit log is tamper-evident, not immutable.
    Changes may be detected by chain verification, but the log cannot
    prevent every form of tampering.

## Technology

-   Python and Streamlit
-   SQLite
-   pytest
-   PyMuPDF and pypdf for PDF handling and text extraction
-   Tesseract / pytesseract for optional OCR
-   pyHanko for PDF digital-signature checks
-   pyzbar, qrcode, and Pillow for QR-related features
-   PyYAML, RapidFuzz, and python-dateutil for rule packs and matching
-   ReportLab for PDF reports

See `requirements.txt` for the dependencies declared by this project.
Some features are optional and may be unavailable when their
system-level dependencies are missing.

## Requirements

-   Windows 10 or Windows 11
-   A supported Python installation
-   PowerShell
-   Internet access for installing Python packages
-   Optional: Tesseract OCR installed separately if OCR is needed

The project has been tested in the current development environment with
Python 3.14. If a dependency does not yet support your Python version,
use a Python version supported by that dependency and reinstall the
requirements in a fresh virtual environment.

## Installation on Windows

Open PowerShell and move to the project folder:

``` powershell
cd D:\evidence-ladder-copilot
```

Create and activate a virtual environment:

``` powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can run the virtual environment's
Python directly instead of changing your execution policy:

``` powershell
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

If the virtual environment is activated, this also works:

``` powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Start the application

From the project directory:

``` powershell
.\venv\Scripts\python.exe -m streamlit run app.py
```

Streamlit prints a local URL in the terminal. Open that URL in your
browser. Keep the terminal open while using the application.

## Run the automated tests

Run the test suite from the project directory:

``` powershell
.\venv\Scripts\python.exe -m pytest -q
```

The latest result reported during development was **127 passed, 1
warning**. Treat this as the last recorded result, not a guarantee that
every environment or manual workflow has been tested. Re-run the command
after code or dependency changes. The warning concerned the deprecated
`fitz` import/API and should be reviewed separately; it did not cause
that test run to fail.

## Demo accounts

The original project notes list these seeded accounts. Confirm them
against the current database and seed code before presenting, especially
if the database has been reused or changed.

  Role               Username       Password
  ------------------ -------------- -----------------
  Administrator      `admin`        `Admin@123`
  Scrutiny Officer   `officer1`     `Officer@123`
  Scrutiny Officer   `officer2`     `Officer@123`
  Applicant          `applicant1`   `Applicant@123`

These are demonstration credentials, not secure production credentials.
Do not reuse them outside the local demo.

## Typical demo workflow

1.  Sign in using a seeded demo account.
2.  Open or create an application.
3.  Upload one or more synthetic PDF documents.
4.  Review extracted fields and run the available validation or
    verification checks.
5.  Open the findings and Evidence-Ladder results.
6.  Sign in as a scrutiny officer to review evidence, add remarks, and
    record a decision.
7.  Generate the relevant PDF or CSV report.
8.  Open the Audit tab and verify that the current chain is valid.

Use only the synthetic sample applications and documents during the
demo. All sample material should remain clearly labelled as fictional.

## PDF extraction and optional OCR

Native PDF text extraction is attempted first. For scanned PDFs, the
application may attempt OCR if the required Python package and Tesseract
executable are installed.

To enable OCR:

1.  Install the Tesseract OCR application for Windows using a trusted
    distribution.
2.  Install or enable the relevant Python packages as listed or
    commented in `requirements.txt`.
3.  If Tesseract is not available on `PATH`, configure `TESSERACT_CMD`
    in the project's `.env` file if the application supports that
    setting.
4.  Restart Streamlit and test with a clearly labelled synthetic scanned
    PDF.

OCR output can contain recognition errors. Check extracted fields
against the source document during the demo.

## Data and database notes

-   Application and verification records are stored in SQLite.
-   Uploaded documents are stored under `uploads/`, grouped by
    application.
-   The database and upload directory contain the state of your local
    demo. Back them up before making changes.
-   Do not delete the database or upload directory just to fix a display
    issue; doing so may remove applications, documents, audit history,
    and decisions.
-   If a schema change specifically requires a fresh demo database, stop
    Streamlit first and make a separate backup of both the database and
    uploads before resetting anything. Only use a reset procedure that
    is documented for this project.

## Audit-chain repair and verification

The audit chain was repaired during development after verification
identified a broken predecessor link. The repair recalculated hashes
from the affected point and changed historical hash values. As a result:

-   A successful check such as `(True, None)` means the **current
    repaired chain** verifies.
-   It does **not** prove that the original chain was intact before
    repair.
-   Keep the original pre-repair database backup, the timestamped backup
    created for the repair, and the repair report together.
-   Do not delete these backups or the repair report if you need to
    explain the repair during evaluation.
-   The repair utility is a maintenance script, not part of the normal
    application launch process. Do not run it again unless you
    understand its options, have stopped the app, and have made a fresh
    backup.

To verify the current chain from PowerShell:

``` powershell
python -c "from database.db import get_connection; from utils.audit import verify_chain; c=get_connection(); print(verify_chain(c)); c.close()"
```

The expected healthy result is:

``` text
(True, None)
```

This result should be checked again after exercising actions that write
to the audit log.

## Troubleshooting

### `ModuleNotFoundError` when starting the app or tests

Activate the virtual environment and reinstall dependencies:

``` powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Make sure Streamlit and pytest are run using the same Python environment
where the dependencies were installed.

### OCR does not run

Check that Tesseract is installed and accessible. Confirm the configured
executable path, restart the application, and try a synthetic scanned
PDF. The application can still work with digitally generated PDFs that
contain selectable text.

### Signature or QR status says unavailable

Check whether the optional Python packages and any required system
libraries are installed. An unavailable result is not the same as an
invalid signature or a failed QR match. For the demo, explain the
limitation instead of presenting it as a negative verification result.

### PDF report contains unusual characters

The bundled ReportLab font may not support non-Latin scripts. Use
English text for the demo report or configure a suitable Unicode font
before relying on multilingual output.

### Audit verification fails

Stop Streamlit and avoid further write actions until the cause is
understood. Preserve the database and current logs. Do not edit audit
rows manually or run a repair script without a separate backup and a
documented reason.

### Port is already in use

Stop the existing Streamlit process or start the app on another port:

``` powershell
.\venv\Scripts\python.exe -m streamlit run app.py --server.port 8502
```

## Project status

The current development record indicates that the main application
features and security-hardening work from Phases 1--6 are implemented.
The latest reported automated test run passed 127 tests with one
warning, and the repaired audit chain returned `(True, None)`.

Before calling the project demo-ready, manually verify the complete
login and role flow, multi-PDF upload, extraction/OCR fallback,
validation cases, signature and mock issuer statuses, QR replay
handling, officer decisions and persistence, PDF/CSV exports, Audit tab
text, and the audit chain after new writes. Also confirm the synthetic
demo dataset contains the intended number and variety of scenarios. Do
not claim that untested workflows passed.

## Five-minute SIH demonstration

A simple demo sequence:

1.  **Problem and overview (30 seconds):** explain that the prototype
    organises document scrutiny and highlights evidence requiring human
    attention.
2.  **Clean application (60 seconds):** open a synthetic application,
    show its documents and consistent extracted fields, and run
    validation.
3.  **Defective application (60 seconds):** show a deliberately missing
    or expired document and explain the finding and recommended action.
4.  **Verification and human review (90 seconds):** show the
    Evidence-Ladder result, clearly labelled mock issuer status, and
    officer review with remarks.
5.  **Reports and audit (60 seconds):** download a report, open the
    Audit tab, and show the current chain verification result.

If OCR, signature validation, or QR decoding is unavailable on the
presentation laptop, use a prepared synthetic PDF that supports the
available checks and explain the limitation honestly. Never imply that
mock issuer responses are live AICTE verification.

## Before submitting

-   Confirm the official SIH problem statement ID and title against the
    team's final submission materials. The previous README used
    **SIH26261**; project materials elsewhere may refer to a different
    ID, so do not publish an unverified identifier.
-   Confirm demo credentials against the current seed code.
-   Run the tests and retain the actual output.
-   Verify the audit chain after normal application actions.
-   Keep the original and repair backups plus the repair report.
-   Ensure synthetic applications and documents are labelled as
    synthetic.
-   Do not describe the prototype as production-ready or as connected to
    real issuer systems.


## Team attribution
The login hero displays a highlighted **BY TEAM ANVESHAK** credit in the project theme.
