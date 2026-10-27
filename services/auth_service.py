from database.db import get_connection
from utils.security import hash_password, verify_password
from utils import audit

ROLES = ("applicant", "officer", "admin")


class PermissionDenied(Exception):
    pass


def authenticate(username: str, password: str):
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,))
        row = cur.fetchone()
        if row is None:
            audit.append_entry(conn, actor=username, action="LOGIN_FAILED",
                                record_type="user", record_id=username,
                                payload={"reason": "unknown_user"})
            return None

        if verify_password(password, row["password_salt"], row["password_hash"]):
            audit.append_entry(conn, actor=username, action="LOGIN_SUCCESS",
                                record_type="user", record_id=str(row["id"]))
            return dict(row)
        else:
            audit.append_entry(conn, actor=username, action="LOGIN_FAILED",
                                record_type="user", record_id=str(row["id"]),
                                payload={"reason": "bad_password"})
            return None
    finally:
        conn.close()


def require_role(user, allowed_roles):
    if user is None or user.get("role") not in allowed_roles:
        raise PermissionDenied(
            f"Action requires one of roles {allowed_roles}, got "
            f"{user.get('role') if user else None}."
        )


def list_users(actor):
    require_role(actor, ("admin",))
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, username, full_name, role, email, institution_id, is_active, created_at "
            "FROM users ORDER BY id"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def create_user(actor, username, password, full_name, role, email=None, institution_id=None):
    require_role(actor, ("admin",))
    if role not in ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {ROLES}.")

    salt, pwd_hash = hash_password(password)

    conn = get_connection()
    try:
        cur = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        if cur.fetchone() is not None:
            raise ValueError(f"Username '{username}' already exists.")

        cur = conn.execute(
            """INSERT INTO users
               (username, password_salt, password_hash, full_name, role, email, institution_id)
               VALUES (?,?,?,?,?,?,?)""",
            (username, salt, pwd_hash, full_name, role, email, institution_id),
        )
        new_id = cur.lastrowid
        conn.commit()
        audit.append_entry(conn, actor=actor["username"], action="USER_CREATED",
                            record_type="user", record_id=username, payload={"role": role})
        return new_id
    finally:
        conn.close()


def deactivate_user(actor, user_id):
    require_role(actor, ("admin",))
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        conn.commit()
        audit.append_entry(conn, actor=actor["username"], action="USER_DEACTIVATED",
                            record_type="user", record_id=str(user_id))
    finally:
        conn.close()


def list_institutions_for_registration():
    """Return existing institutions for the public applicant registration form."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, institution_code, state FROM institutions ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def register_applicant(username, password, full_name, email, institution_id):
    """Create a pending applicant account; an administrator must activate it."""
    if not username or not username.strip():
        raise ValueError("Username is required.")
    if not full_name or not full_name.strip():
        raise ValueError("Full name is required.")
    if not email or not email.strip():
        raise ValueError("Email is required.")
    if not isinstance(institution_id, int) or institution_id <= 0:
        raise ValueError("Choose a valid institution.")
    salt, pwd_hash = hash_password(password)
    conn = get_connection()
    try:
        if conn.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)",
                        (username.strip(),)).fetchone():
            raise ValueError("That username is already taken.")
        institution = conn.execute(
            "SELECT id FROM institutions WHERE id=?", (institution_id,)
        ).fetchone()
        if institution is None:
            raise ValueError("Selected institution does not exist.")
        cur = conn.execute(
            """INSERT INTO users
               (username, password_salt, password_hash, full_name, role,
                institution_id, email, is_active)
               VALUES (?, ?, ?, ?, 'applicant', ?, ?, 0)""",
            (username.strip(), salt, pwd_hash, full_name.strip(),
             institution_id, email.strip()),
        )
        user_id = cur.lastrowid
        conn.commit()
        audit.append_entry(conn, actor=username.strip(), action="APPLICANT_REGISTRATION_REQUESTED",
                           record_type="user", record_id=str(user_id),
                           payload={"institution_id": institution_id, "status": "pending_admin_approval"})
        return user_id
    finally:
        conn.close()


def activate_user(actor, user_id):
    """Admin-only activation for pending applicant registrations."""
    require_role(actor, ("admin",))
    conn = get_connection()
    try:
        row = conn.execute("SELECT username, is_active FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("User not found.")
        conn.execute("UPDATE users SET is_active=1 WHERE id=?", (user_id,))
        conn.commit()
        audit.append_entry(conn, actor=actor["username"], action="USER_ACTIVATED",
                           record_type="user", record_id=str(user_id),
                           payload={"username": row["username"]})
    finally:
        conn.close()
