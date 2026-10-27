"""Tests for Module J: hash-chained audit log."""
from utils.audit import append_entry, verify_chain, get_entries


def test_audit_chain_empty_is_valid(temp_db):
    conn = temp_db.get_connection()
    try:
        ok, broken = verify_chain(conn)
        assert ok is True
        assert broken is None
    finally:
        conn.close()


def test_audit_chain_detects_tampering(temp_db):
    conn = temp_db.get_connection()
    try:
        append_entry(conn, actor="tester", action="EVENT_ONE", payload={"n": 1})
        append_entry(conn, actor="tester", action="EVENT_TWO", payload={"n": 2})
        conn.commit()

        ok, broken = verify_chain(conn)
        assert ok is True
        assert broken is None

        conn.execute("UPDATE audit_log SET action = 'HACKED' WHERE seq = 1")
        conn.commit()

        ok2, broken2 = verify_chain(conn)
        assert ok2 is False
        assert broken2 == 1
    finally:
        conn.close()


def test_audit_chain_links_correctly(temp_db):
    conn = temp_db.get_connection()
    try:
        h1 = append_entry(conn, actor="a", action="ONE")
        h2 = append_entry(conn, actor="b", action="TWO")
        conn.commit()
        row2 = conn.execute("SELECT prev_hash, entry_hash FROM audit_log WHERE seq = 2").fetchone()
        assert row2["prev_hash"] == h1
        assert row2["entry_hash"] == h2
    finally:
        conn.close()


def test_audit_entries_returns_latest_rows_in_chronological_order(temp_db):
    conn = temp_db.get_connection()
    try:
        for i in range(5):
            append_entry(conn, actor="tester", action=f"EVENT_{i}")
        conn.commit()

        entries = get_entries(conn, limit=3)
        assert [entry["action"] for entry in entries] == [
            "EVENT_2", "EVENT_3", "EVENT_4"
        ]
    finally:
        conn.close()


def test_concurrent_appends_keep_a_single_hash_chain(temp_db):
    """Concurrent sessions must not append sibling entries from one tail hash."""
    from concurrent.futures import ThreadPoolExecutor

    def append_one(i):
        conn = temp_db.get_connection()
        try:
            return append_entry(conn, actor=f"worker-{i}", action=f"EVENT_{i}")
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append_one, range(32)))

    conn = temp_db.get_connection()
    try:
        ok, broken = verify_chain(conn)
        assert ok is True
        assert broken is None
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 32
    finally:
        conn.close()
