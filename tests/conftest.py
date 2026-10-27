import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point database.db at a fresh, isolated SQLite file for this test."""
    import database.db as db_module

    test_db_path = tmp_path / "test_evidence_ladder.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db_path)
    db_module.init_db()
    return db_module