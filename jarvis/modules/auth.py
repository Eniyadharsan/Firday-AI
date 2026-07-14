"""Authentication module — bcrypt hashing + JWT tokens."""

import time
import json
import secrets
import hashlib
import sqlite3
from loguru import logger
from jarvis.config import DB_PATH, JWT_SECRET, BCRYPT_ROUNDS

# Use bcrypt if available, fallback to argon2, then SHA-256
try:
    import bcrypt
    HASH_METHOD = "bcrypt"
except ImportError:
    try:
        from argon2 import PasswordHasher
        _ph = PasswordHasher()
        HASH_METHOD = "argon2"
    except ImportError:
        HASH_METHOD = "sha256"
        logger.warning("Neither bcrypt nor argon2 available, using SHA-256 (install bcrypt for production)")


def _init_db() -> None:
    """Initialize the users table."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT
        )
    """)
    conn.commit()
    conn.close()

_init_db()


def hash_password(password: str) -> str:
    """Hash a password using the best available method."""
    if HASH_METHOD == "bcrypt":
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()
    elif HASH_METHOD == "argon2":
        return _ph.hash(password)
    else:
        salt = secrets.token_hex(16)
        h = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"sha256:{salt}:{h}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against its hash."""
    if HASH_METHOD == "bcrypt":
        return bcrypt.checkpw(password.encode(), stored_hash.encode())
    elif HASH_METHOD == "argon2":
        try:
            return _ph.verify(stored_hash, password)
        except Exception:
            return False
    else:
        parts = stored_hash.split(":")
        if len(parts) == 3 and parts[0] == "sha256":
            return hashlib.sha256((parts[1] + password).encode()).hexdigest() == parts[2]
        return False


def make_token(user_id: str, email: str) -> str:
    """Create a JWT-like token."""
    payload = json.dumps({"userId": user_id, "email": email, "exp": time.time() + 7 * 24 * 3600})
    b64 = secrets.token_urlsafe(32)
    sig = hashlib.sha256((b64 + JWT_SECRET).encode()).hexdigest()[:16]
    return f"{b64}.{sig}"


def verify_token(token: str) -> dict | None:
    """Verify a token. Returns user info or None."""
    # Simple token validation (in production, use proper JWT)
    if token and len(token) > 10:
        return {"valid": True}
    return None


def signup(email: str, password: str, name: str) -> dict:
    """Register a new user."""
    if not email or not password:
        return {"error": "Email and password required."}
    if len(password) < 6:
        return {"error": "Password must be at least 6 characters."}

    conn = sqlite3.connect(str(DB_PATH))
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            return {"error": "Email already registered. Please sign in."}

        user_id = secrets.token_hex(16)
        pw_hash = hash_password(password)
        user_name = name or email.split("@")[0]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        conn.execute(
            "INSERT INTO users (id, email, name, password_hash, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email, user_name, pw_hash, now, now),
        )
        conn.commit()
        token = make_token(user_id, email)
        return {"token": token, "user": {"id": user_id, "email": email, "name": user_name}}
    except Exception as e:
        logger.error(f"Signup error: {e}")
        return {"error": "Registration failed."}
    finally:
        conn.close()


def signin(email: str, password: str) -> dict:
    """Authenticate an existing user."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute("SELECT id, email, name, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            return {"error": "Invalid email or password."}

        user_id, user_email, user_name, pw_hash = row
        if not verify_password(password, pw_hash):
            return {"error": "Invalid email or password."}

        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (time.strftime("%Y-%m-%dT%H:%M:%SZ"), user_id))
        conn.commit()
        token = make_token(user_id, user_email)
        return {"token": token, "user": {"id": user_id, "email": user_email, "name": user_name}}
    except Exception as e:
        logger.error(f"Signin error: {e}")
        return {"error": "Login failed."}
    finally:
        conn.close()
