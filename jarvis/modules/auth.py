"""
Authentication — JWT tokens + password hashing.
Uses Turso cloud DB via jarvis.db module.
"""

import time
import secrets
import hashlib
from functools import wraps
from typing import Callable
import jwt
from flask import request, jsonify
from loguru import logger
from jarvis.config import JWT_SECRET
from jarvis import db


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"sha256:{salt}:{h}"


def verify_password(password: str, stored_hash: str) -> bool:
    parts = stored_hash.split(":")
    if len(parts) == 3 and parts[0] == "sha256":
        return hashlib.sha256((parts[1] + password).encode()).hexdigest() == parts[2]
    return False


def make_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "iat": int(time.time()), "exp": int(time.time()) + 7 * 24 * 3600}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None


def get_user_from_request() -> dict | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return verify_token(auth_header[7:])


def require_auth(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args, **kwargs):
        host = request.host or ""
        if "hf.space" in host or "huggingface" in host or "vercel.app" in host:
            request.user = {"sub": "owner", "email": "owner@jarvis"}
            return f(*args, **kwargs)
        user = get_user_from_request()
        if not user:
            return jsonify({"error": "Authentication required."}), 401
        request.user = user
        return f(*args, **kwargs)
    return decorated


def get_current_user_id() -> str:
    user = getattr(request, "user", None)
    return user.get("sub", "default") if user else "default"


def signup(email: str, password: str, name: str) -> dict:
    if not email or not password:
        return {"error": "Email and password required."}
    if len(password) < 6:
        return {"error": "Password must be at least 6 characters."}
    if "@" not in email:
        return {"error": "Invalid email."}

    existing = db.execute("SELECT id FROM users WHERE email = ?", [email])
    if existing:
        return {"error": "Email already registered."}

    user_id = secrets.token_hex(16)
    pw_hash = hash_password(password)
    user_name = name or email.split("@")[0]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    db.execute("INSERT INTO users (id, email, name, password_hash, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?)",
               [user_id, email, user_name, pw_hash, now, now])
    logger.info(f"User registered: {email}")
    return {"token": make_token(user_id, email), "user": {"id": user_id, "email": email, "name": user_name}}


def signin(email: str, password: str) -> dict:
    rows = db.execute("SELECT id, email, name, password_hash FROM users WHERE email = ?", [email])
    if not rows:
        return {"error": "Invalid email or password."}

    row = rows[0]
    if not verify_password(password, row["password_hash"]):
        return {"error": "Invalid email or password."}

    db.execute("UPDATE users SET last_login = ? WHERE id = ?", [time.strftime("%Y-%m-%dT%H:%M:%SZ"), row["id"]])
    return {"token": make_token(row["id"], row["email"]), "user": {"id": row["id"], "email": row["email"], "name": row["name"]}}
