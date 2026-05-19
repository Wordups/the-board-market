"""
The Board Market — Authentication

Single-user system for Phase 3. First registration becomes the owner;
subsequent registrations return 403 until multi-user is enabled.

Stack: bcrypt for password hashing. JWT for session tokens (Phase 3.5).
Phase 3 ships with simple session cookie auth; JWT migration later.
"""

import sqlite3
import secrets
from datetime import datetime, timedelta
from typing import Optional

# bcrypt direct (passlib + bcrypt 4.x has known compat issues)
try:
    import bcrypt
except ImportError:
    bcrypt = None  # handled at function call

from .db import db_cursor


class AuthError(Exception):
    """Base auth exception."""


class RegistrationClosed(AuthError):
    """Single-user mode: registration disabled after first user."""


class InvalidCredentials(AuthError):
    """Wrong email or password."""


def _hash_password(password: str) -> str:
    if bcrypt is None:
        raise RuntimeError("bcrypt not installed. pip install bcrypt")
    # bcrypt has a 72-byte limit; truncate defensively
    pw_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    if bcrypt is None:
        raise RuntimeError("bcrypt not installed. pip install bcrypt")
    pw_bytes = password.encode("utf-8")[:72]
    return bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8"))


def register(email: str, password: str, display_name: Optional[str] = None) -> dict:
    """
    Register the first (and only) user. Returns user dict.
    Raises RegistrationClosed if a user already exists.
    """
    if len(password) < 12:
        raise AuthError("Password must be ≥ 12 characters")

    with db_cursor() as c:
        existing = c.execute("SELECT COUNT(*) as n FROM users").fetchone()
        if existing["n"] > 0:
            raise RegistrationClosed(
                "Single-user mode: registration is closed. "
                "Multi-user is a Phase 7+ feature."
            )

        password_hash = _hash_password(password)
        c.execute(
            """
            INSERT INTO users (email, password_hash, display_name)
            VALUES (?, ?, ?)
            """,
            (email.lower().strip(), password_hash, display_name),
        )
        user_id = c.lastrowid

        # Seed preferences row for the new user
        c.execute(
            "INSERT INTO preferences (user_id) VALUES (?)",
            (user_id,),
        )

        return {
            "id": user_id,
            "email": email.lower().strip(),
            "display_name": display_name,
        }


def login(email: str, password: str) -> dict:
    """
    Verify credentials and update last_login. Returns user dict.
    Raises InvalidCredentials on failure.
    """
    with db_cursor() as c:
        row = c.execute(
            "SELECT id, email, password_hash, display_name FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()

        if row is None or not _verify_password(password, row["password_hash"]):
            raise InvalidCredentials("Invalid email or password")

        c.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )

        return {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
        }


def get_user(user_id: int) -> Optional[dict]:
    """Fetch user by id. Returns None if not found."""
    with db_cursor() as c:
        row = c.execute(
            "SELECT id, email, display_name, created_at, last_login FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def is_registration_open() -> bool:
    """True if zero users exist (first-run scenario)."""
    with db_cursor() as c:
        row = c.execute("SELECT COUNT(*) as n FROM users").fetchone()
        return row["n"] == 0
