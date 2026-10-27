-- ============================================================
-- Evidence-Ladder Scrutiny Copilot — full schema (Phase 1)
-- Created up-front so later phases only ADD rows/logic, never
-- migrate the schema. All CREATE statements are idempotent.
-- ============================================================

PRAGMA foreign_keys = ON;

-- ---------- Module A: institutions & users ----------
CREATE TABLE IF NOT EXISTS institutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    institution_code TEXT UNIQUE NOT NULL,
    address TEXT,
    state TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('applicant','officer','admin')),
    institution_id INTEGER,
    email TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(institution_id) REFERENCES institutions(id)
);

-- ---------- Module B: application intake ----------
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_code TEXT UNIQUE NOT NULL,
    institution_id INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT 'EoA',
    academic_year TEXT NOT NULL,
    submission_date TEXT,
    status TEXT NOT NULL DEFAULT 'draft',       -- draft, submitted, under_review, approved, rejected
    priority TEXT DEFAULT 'P4',                 -- P1..P4, see Evidence Ladder escalation policy
    created_by INTEGER,
    assigned_officer INTEGER,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    scenario_tag TEXT,                          -- labels synthetic demo scenarios (Module K)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(institution_id) REFERENCES institutions(id),
    FOREIGN KEY(created_by) REFERENCES users(id),
    FOREIGN KEY(assigned_officer) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    doc_type TEXT NOT NULL,
    required INTEGER NOT NULL DEFAULT 1,
    satisfied INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(application_id) REFERENCES applications(id)
);

-- ---------- Module C: documents & extraction ----------
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    doc_type TEXT,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    file_size INTEGER,
    page_count INTEGER,
    upload_date TEXT NOT NULL DEFAULT (datetime('now')),
    uploaded_by INTEGER,
    extraction_status TEXT DEFAULT 'pending',   -- pending, done, failed
    is_native_text INTEGER DEFAULT 0,
    ocr_used INTEGER DEFAULT 0,
    FOREIGN KEY(application_id) REFERENCES applications(id),
    FOREIGN KEY(uploaded_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS extracted_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    field_value TEXT,
    confidence REAL,
    page_number INTEGER,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

-- ---------- Module D: rule packs ----------
CREATE TABLE IF NOT EXISTS rule_packs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    file_path TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(name, version),
    FOREIGN KEY(created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS rule_pack_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_pack_id INTEGER,
    changed_by INTEGER,
    change_summary TEXT,
    changed_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(rule_pack_id) REFERENCES rule_packs(id),
    FOREIGN KEY(changed_by) REFERENCES users(id)
);

-- ---------- Module E/F: findings ----------
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    document_id INTEGER,
    rule_id TEXT,
    rule_pack_version TEXT,
    engine TEXT,                                -- E1..E5 style tag
    severity TEXT,                               -- info, low, medium, high
    rung INTEGER NOT NULL DEFAULT 0,              -- 0..4, see models/enums.py
    status TEXT,                                  -- verification_pending, verified, mismatch_detected,
                                                   -- expired, source_unavailable, manual_review_required
    description TEXT,
    reason TEXT,
    extracted_value TEXT,
    expected_value TEXT,
    page_number INTEGER,
    clause_ref TEXT,
    recommended_action TEXT,
    advisory INTEGER NOT NULL DEFAULT 1,
    officer_decision TEXT,                        -- confirmed, dismissed, pending
    officer_remarks TEXT,
    decided_by INTEGER,
    decided_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(application_id) REFERENCES applications(id),
    FOREIGN KEY(document_id) REFERENCES documents(id),
    FOREIGN KEY(decided_by) REFERENCES users(id)
);

-- ---------- Module G: mock issuer verification ----------
CREATE TABLE IF NOT EXISTS issuer_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_type TEXT NOT NULL,                    -- e_stamp, fire_noc, affiliation, other
    certificate_number TEXT NOT NULL,
    institution_name TEXT,
    issue_date TEXT,
    expiry_date TEXT,
    extra_json TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1,
    UNIQUE(issuer_type, certificate_number)
);

CREATE TABLE IF NOT EXISTS verification_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    document_id INTEGER,
    issuer_type TEXT,
    certificate_number TEXT,
    status TEXT NOT NULL DEFAULT 'verification_pending',
    source TEXT,
    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
    responded_at TEXT,
    response_json TEXT,
    manual_notes TEXT,
    FOREIGN KEY(application_id) REFERENCES applications(id),
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

-- ---------- Module J: append-only hash-chained audit log ----------
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    record_type TEXT,
    record_id TEXT,
    payload_json TEXT,
    timestamp TEXT NOT NULL
);

-- ---------- Helpful indexes ----------
CREATE INDEX IF NOT EXISTS idx_documents_application ON documents(application_id);
CREATE INDEX IF NOT EXISTS idx_findings_application ON findings(application_id);
CREATE INDEX IF NOT EXISTS idx_findings_document ON findings(document_id);
CREATE INDEX IF NOT EXISTS idx_verification_application ON verification_requests(application_id);