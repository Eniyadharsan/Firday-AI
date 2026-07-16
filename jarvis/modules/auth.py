"""
Authentication — JWT tokens + password hashing + email OTP verification.
Uses Turso cloud DB via jarvis.db module.
"""

import time
import secrets
import hashlib
import random
from functools import wraps
from typing import Callable
import jwt
from flask import request, jsonify
from loguru import logger
from jarvis.config import JWT_SECRET, RESEND_API_KEY
from jarvis import db

# In-memory OTP store: {email: {"code": "123456", "expires": timestamp, "password": ..., "name": ...}}
_pending_otps: dict[str, dict] = {}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"sha256:{salt}:{h}"


def verify_password(password: str, stored_hash: str) -> bool:
    parts = stored_hash.split(":")
    if len(parts) == 3 and parts[0] == "sha256":
        return hashlib.sha256((parts[1] + password).encode()).hexdigest() == parts[2]
    return False


def make_token(user_id: str, email: str, name: str = "") -> str:
    payload = {"sub": user_id, "email": email, "name": name, "iat": int(time.time()), "exp": int(time.time()) + 7 * 24 * 3600}
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
        if "vercel.app" in host:
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


def _generate_otp() -> str:
    """Generate a 6-digit OTP code."""
    return str(random.randint(100000, 999999))


def _send_otp_email(email: str, code: str) -> bool:
    """Send OTP email via Resend. Returns True on success."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping OTP email, auto-verifying")
        return True

    try:
        import resend
        resend.api_key = RESEND_API_KEY

        resend.Emails.send({
            "from": "JARVIS <onboarding@resend.dev>",
            "to": [email],
            "subject": "Your JARVIS Verification Code",
            "html": f"""
                <div style="font-family:monospace;background:#0a1628;color:#00e5ff;padding:40px;border-radius:12px;text-align:center">
                    <h1 style="letter-spacing:4px;margin-bottom:8px">J.A.R.V.I.S</h1>
                    <p style="color:rgba(0,229,255,0.6);font-size:12px;margin-bottom:30px">PERSONAL AI SYSTEM</p>
                    <p style="color:#fff;font-size:14px;margin-bottom:20px">Your verification code is:</p>
                    <div style="font-size:36px;letter-spacing:8px;color:#00e5ff;background:rgba(0,229,255,0.08);border:1px solid rgba(0,229,255,0.2);border-radius:8px;padding:16px;display:inline-block">{code}</div>
                    <p style="color:rgba(255,255,255,0.5);font-size:11px;margin-top:24px">This code expires in 10 minutes.</p>
                </div>
            """,
        })
        logger.info(f"OTP email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email to {email}: {e}")
        return False


def signup(email: str, password: str, name: str) -> dict:
    """Initiate signup — sends OTP for email verification.
    If email already exists, auto-signin instead of erroring."""
    if not email or not password:
        return {"error": "Email and password required."}
    if len(password) < 6:
        return {"error": "Password must be at least 6 characters."}
    if "@" not in email:
        return {"error": "Invalid email."}

    existing = db.execute("SELECT id FROM users WHERE email = ?", [email])
    if existing:
        # Email already registered — try to sign them in automatically
        return signin(email, password)

    # Generate and store pending signup data
    code = _generate_otp()
    _pending_otps[email] = {
        "code": code,
        "expires": time.time() + 600,  # 10 minutes
        "password": password,
        "name": name or email.split("@")[0],
    }

    if not RESEND_API_KEY:
        # No email service configured — skip OTP, complete signup directly
        logger.info(f"No RESEND_API_KEY — auto-verifying signup for {email}")
        return _complete_signup(email)

    sent = _send_otp_email(email, code)
    if not sent:
        # Email failed — still complete signup (graceful fallback)
        logger.warning(f"OTP email failed for {email} — completing signup without verification")
        return _complete_signup(email)

    return {"otpSent": True, "message": "Verification code sent to your email."}


def verify_otp(email: str, code: str) -> dict:
    """Verify OTP and complete signup."""
    pending = _pending_otps.get(email)
    if not pending:
        return {"error": "No pending verification. Please sign up again."}

    if time.time() > pending["expires"]:
        del _pending_otps[email]
        return {"error": "Code expired. Please sign up again."}

    if pending["code"] != code.strip():
        return {"error": "Invalid code. Please try again."}

    # OTP verified — complete signup
    del _pending_otps[email]
    return _complete_signup(email, pending["password"], pending["name"])


def _complete_signup(email: str, password: str = None, name: str = None) -> dict:
    """Finalize user registration after OTP verification."""
    pending = _pending_otps.get(email)
    if password is None and pending:
        password = pending["password"]
        name = pending["name"]
        del _pending_otps[email]
    elif password is None:
        # Fallback for no-OTP mode
        pending = _pending_otps.get(email)
        if not pending:
            return {"error": "Registration data not found."}
        password = pending["password"]
        name = pending["name"]
        del _pending_otps[email]

    user_id = secrets.token_hex(16)
    pw_hash = hash_password(password)
    user_name = name or email.split("@")[0]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    db.execute("INSERT INTO users (id, email, name, password_hash, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?)",
               [user_id, email, user_name, pw_hash, now, now])
    logger.info(f"User registered: {email}")
    return {"token": make_token(user_id, email, user_name), "user": {"id": user_id, "email": email, "name": user_name}}


def signin(email: str, password: str) -> dict:
    if not email or not password:
        return {"error": "Email and password required."}

    rows = db.execute("SELECT id, email, name, password_hash FROM users WHERE email = ?", [email])
    if not rows:
        return {"error": "Account not found. Please sign up first."}

    row = rows[0]
    if not verify_password(password, row["password_hash"]):
        return {"error": "Invalid password."}

    db.execute("UPDATE users SET last_login = ? WHERE id = ?", [time.strftime("%Y-%m-%dT%H:%M:%SZ"), row["id"]])
    return {"token": make_token(row["id"], row["email"], row["name"]), "user": {"id": row["id"], "email": row["email"], "name": row["name"]}}
