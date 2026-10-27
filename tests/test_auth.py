"""Tests for Module A: password hashing, authentication and RBAC."""
import pytest

from utils.security import hash_password, verify_password
from services.auth_service import PermissionDenied, require_role


def test_password_hash_roundtrip():
    salt, pwd_hash = hash_password("Correct@123")
    assert verify_password("Correct@123", salt, pwd_hash) is True
    assert verify_password("Wrong@123", salt, pwd_hash) is False


def test_password_minimum_length():
    with pytest.raises(ValueError):
        hash_password("abc")


def test_authenticate_success_and_failure(temp_db, monkeypatch):
    import database.seed as seed_module
    monkeypatch.setattr(seed_module, "get_connection", temp_db.get_connection)
    seed_module.seed_demo_data()

    import services.auth_service as auth_module
    monkeypatch.setattr(auth_module, "get_connection", temp_db.get_connection)

    user = auth_module.authenticate("admin", "Admin@123")
    assert user is not None
    assert user["role"] == "admin"

    bad = auth_module.authenticate("admin", "wrong-password")
    assert bad is None

    missing = auth_module.authenticate("ghost", "whatever")
    assert missing is None


def test_require_role_blocks_wrong_role():
    applicant = {"username": "applicant1", "role": "applicant"}
    with pytest.raises(PermissionDenied):
        require_role(applicant, ["admin"])
    require_role(applicant, ["applicant", "admin"])  # must not raise


def test_create_user_requires_admin(temp_db, monkeypatch):
    import services.auth_service as auth_module
    monkeypatch.setattr(auth_module, "get_connection", temp_db.get_connection)

    officer_actor = {"username": "officer1", "role": "officer"}
    with pytest.raises(PermissionDenied):
        auth_module.create_user(officer_actor, "newuser", "Passw0rd!", "New User", "applicant")


def test_create_user_succeeds_for_admin(temp_db, monkeypatch):
    import services.auth_service as auth_module
    monkeypatch.setattr(auth_module, "get_connection", temp_db.get_connection)

    admin_actor = {"username": "admin", "role": "admin"}
    new_id = auth_module.create_user(admin_actor, "newofficer", "Passw0rd!", "New Officer", "officer")
    assert isinstance(new_id, int) and new_id > 0

    users = auth_module.list_users(admin_actor)
    usernames = [u["username"] for u in users]
    assert "newofficer" in usernames


def test_applicant_registration_is_pending_and_institution_bound(temp_db, monkeypatch):
    import database.seed as seed_module
    import services.auth_service as auth_module

    monkeypatch.setattr(seed_module, "get_connection", temp_db.get_connection)
    seed_module.seed_demo_data()
    monkeypatch.setattr(auth_module, "get_connection", temp_db.get_connection)

    conn = temp_db.get_connection()
    try:
        institution = conn.execute(
            "SELECT id FROM institutions WHERE institution_code='INST-001'"
        ).fetchone()
        institution_id = institution["id"]
    finally:
        conn.close()

    user_id = auth_module.register_applicant(
        "newapplicant", "StrongPass123", "New Applicant",
        "newapplicant@example.test", institution_id
    )
    conn = temp_db.get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        assert row["role"] == "applicant"
        assert row["institution_id"] == institution_id
        assert row["is_active"] == 0
    finally:
        conn.close()


def test_applicant_registration_rejects_duplicate_username(temp_db, monkeypatch):
    import database.seed as seed_module
    import services.auth_service as auth_module

    monkeypatch.setattr(seed_module, "get_connection", temp_db.get_connection)
    seed_module.seed_demo_data()
    monkeypatch.setattr(auth_module, "get_connection", temp_db.get_connection)

    conn = temp_db.get_connection()
    try:
        inst = conn.execute("SELECT id FROM institutions LIMIT 1").fetchone()["id"]
    finally:
        conn.close()

    with pytest.raises(ValueError, match="already taken"):
        auth_module.register_applicant(
            "applicant1", "StrongPass123", "Duplicate User",
            "duplicate@example.test", inst
        )


def test_only_admin_can_activate_pending_applicant(temp_db, monkeypatch):
    import database.seed as seed_module
    import services.auth_service as auth_module

    monkeypatch.setattr(seed_module, "get_connection", temp_db.get_connection)
    seed_module.seed_demo_data()
    monkeypatch.setattr(auth_module, "get_connection", temp_db.get_connection)

    conn = temp_db.get_connection()
    try:
        inst = conn.execute("SELECT id FROM institutions LIMIT 1").fetchone()["id"]
    finally:
        conn.close()
    user_id = auth_module.register_applicant(
        "pendingapp", "StrongPass123", "Pending Applicant",
        "pending@example.test", inst
    )
    with pytest.raises(PermissionDenied):
        auth_module.activate_user({"username": "officer1", "role": "officer"}, user_id)

    auth_module.activate_user({"username": "admin", "role": "admin"}, user_id)
    conn = temp_db.get_connection()
    try:
        active = conn.execute("SELECT is_active FROM users WHERE id=?", (user_id,)).fetchone()["is_active"]
        assert active == 1
    finally:
        conn.close()
