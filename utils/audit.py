import hashlib
import json
import threading
from datetime import datetime, timezone

GENESIS_HASH = "0" * 64

# Serialize appends inside one process; SQLite locking below also protects
# writers in other processes. Without this, two sessions can read the same
# latest hash and create two sibling entries in the chain.
_APPEND_LOCK = threading.RLock()

# NOTE: This audit log is TAMPER-EVIDENT, not immutable. A database
# administrator with direct SQLite access could, in principle, rewrite
# the entire chain consistently. The hash chain lets anyone detect
# tampering by recomputing it -- it does not make tampering impossible.


def _canonical_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash, actor, action, record_type, record_id, payload_json, timestamp) -> str:
    payload = {
        "prev_hash": prev_hash,
        "actor": actor,
        "action": action,
        "record_type": record_type,
        "record_id": record_id,
        "payload_json": payload_json,
        "timestamp": timestamp,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def append_entry(conn, actor, action, record_type=None, record_id=None, payload=None) -> str:
    """Append one serialized audit event and return its hash.

    Acquire SQLite's write reservation *before* reading the previous hash.
    Otherwise concurrent Streamlit sessions can both read the same last hash
    and append sibling entries, making the chain appear tampered with.
    """
    with _APPEND_LOCK:
        # Historically this function committed the caller's pending work too.
        # Preserve that behavior, then start a transaction that locks writers
        # before reading the tail of the chain.
        if conn.in_transaction:
            conn.commit()

        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
            )
            row = cur.fetchone()
            prev_hash = row["entry_hash"] if row else GENESIS_HASH

            timestamp = datetime.now(timezone.utc).isoformat()
            payload_json = _canonical_json(payload) if payload is not None else None
            entry_hash = _compute_hash(
                prev_hash, actor, action, record_type, record_id,
                payload_json, timestamp,
            )

            conn.execute(
                """INSERT INTO audit_log
                   (prev_hash, entry_hash, actor, action, record_type, record_id, payload_json, timestamp)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (prev_hash, entry_hash, actor, action, record_type, record_id,
                 payload_json, timestamp),
            )
            conn.commit()
            return entry_hash
        except Exception:
            conn.rollback()
            raise


def get_entries(conn, limit=200):
    """Return the most recent entries, displayed oldest-to-newest.

    The inner DESC query ensures a busy log does not hide recent events
    once it exceeds ``limit``. The outer ASC query preserves readable
    chronological order in the UI.
    """
    safe_limit = max(1, min(int(limit), 5000))
    cur = conn.execute(
        """SELECT * FROM (
               SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?
           ) ORDER BY seq ASC""",
        (safe_limit,),
    )
    return [dict(r) for r in cur.fetchall()]


def verify_chain(conn):
    cur = conn.execute("SELECT * FROM audit_log ORDER BY seq ASC")
    rows = [dict(r) for r in cur.fetchall()]

    prev_hash = GENESIS_HASH
    for row in rows:
        expected_hash = _compute_hash(
            prev_hash, row["actor"], row["action"], row["record_type"],
            row["record_id"], row["payload_json"], row["timestamp"],
        )
        if row["prev_hash"] != prev_hash or row["entry_hash"] != expected_hash:
            return False, row["seq"]
        prev_hash = row["entry_hash"]

    return True, None