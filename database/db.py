"""SQLite connection management and schema initialisation."""
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "database" / "evidence_ladder.db"
SCHEMA_PATH = ROOT_DIR / "database" / "schema.sql"


def get_connection() -> sqlite3.Connection:
    """Open a new connection. Short-lived connections are opened and
    closed per service call to keep this simple and safe for Streamlit's
    multi-session execution model."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create all tables if they do not already exist. Safe to call on
    every application startup; later phases can add new CREATE TABLE
    statements to schema.sql without breaking existing data."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()


def is_initialised() -> bool:
    if not DB_PATH.exists():
        return False
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        return row["c"] > 0
    finally:
        conn.close()