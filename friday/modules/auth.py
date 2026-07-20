"""
Authentication — JWT tokens + password hashing + email OTP verification.
Uses Turso cloud DB via friday.db module.
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
from friday.config import JWT_SECRET, RESEND_API_KEY, DEV_AUTO_LOGIN, DEV_EMAIL, DEV_PASSWORD
from friday import db

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


def _send_otp_email(email: str, code: str) -> str:
    """Send OTP email via Resend.
    Returns: 'sent' on success, 'skipped' if Resend free-tier can't deliver to this
    email (treated as a failure since OTP is mandatory), 'failed' on other errors."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping OTP email")
        return "skipped"

    try:
        import resend
        resend.api_key = RESEND_API_KEY

        resend.Emails.send({
            "from": "FRIDAY <onboarding@resend.dev>",
            "to": [email],
            "subject": "Your FRIDAY Verification Code",
            "html": f"""
                <div style="font-family:monospace;background:#0a1628;color:#00e5ff;padding:40px;border-radius:12px;text-align:center">
                    <h1 style="letter-spacing:4px;margin-bottom:8px">F.R.I.D.A.Y</h1>
                    <p style="color:rgba(0,229,255,0.6);font-size:12px;margin-bottom:30px">PERSONAL AI SYSTEM</p>
                    <p style="color:#fff;font-size:14px;margin-bottom:20px">Your verification code is:</p>
                    <div style="font-size:36px;letter-spacing:8px;color:#00e5ff;background:rgba(0,229,255,0.08);border:1px solid rgba(0,229,255,0.2);border-radius:8px;padding:16px;display:inline-block">{code}</div>
                    <p style="color:rgba(255,255,255,0.5);font-size:11px;margin-top:24px">This code expires in 10 minutes.</p>
                </div>
            """,
        })
        logger.info(f"OTP email sent to {email}")
        return "sent"
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to send OTP email to {email}: {error_msg}")
        # Resend free tier limitation — can only send to the account owner's email
        if "only send testing emails" in error_msg or "verify a domain" in error_msg:
            logger.warning(f"Resend free tier: cannot send to {email}. Skipping OTP.")
            return "skipped"
        return "failed"


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
        del _pending_otps[email]
        return {"error": "Email verification is not configured. Contact the administrator."}

    result = _send_otp_email(email, code)
    if result == "sent":
        return {"otpSent": True, "message": "Verification code sent to your email."}
    elif result == "skipped":
        # Resend free tier can't deliver to this email — OTP is mandatory, so fail
        del _pending_otps[email]
        return {"error": "Could not send verification email to this address. Email verification is required to sign up."}
    else:
        # Email send failed — return error
        del _pending_otps[email]
        return {"error": "Could not send verification email. Please try again."}


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


def dev_login() -> dict:
    """Development-only auto-login. Signs in (or creates) the configured dev
    account without OTP. Gated by DEV_AUTO_LOGIN; credentials come from env vars.
    """
    if not DEV_AUTO_LOGIN or not DEV_EMAIL or not DEV_PASSWORD:
        return {"error": "Dev auto-login is disabled."}

    rows = db.execute("SELECT id, email, name, password_hash FROM users WHERE email = ?", [DEV_EMAIL])
    if not rows:
        # Create the dev account (no OTP required)
        user_id = secrets.token_hex(16)
        pw_hash = hash_password(DEV_PASSWORD)
        name = DEV_EMAIL.split("@")[0]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        db.execute("INSERT INTO users (id, email, name, password_hash, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?)",
                   [user_id, DEV_EMAIL, name, pw_hash, now, now])
        logger.info(f"Dev account created: {DEV_EMAIL}")
        return {"token": make_token(user_id, DEV_EMAIL, name), "user": {"id": user_id, "email": DEV_EMAIL, "name": name}}

    row = rows[0]
    if not verify_password(DEV_PASSWORD, row["password_hash"]):
        return {"error": "Dev credentials do not match the stored account."}

    db.execute("UPDATE users SET last_login = ? WHERE id = ?", [time.strftime("%Y-%m-%dT%H:%M:%SZ"), row["id"]])
    return {"token": make_token(row["id"], row["email"], row["name"]),
            "user": {"id": row["id"], "email": row["email"], "name": row["name"]}}


def signin(email: str, password: str) -> dict:
    if not email or not password:
        return {"error": "Email and password required."}

    rows = db.execute("SELECT id, email, name, password_hash FROM users WHERE email = ?", [email])
    if not rows:
        return {"error": "Account not found. Please sign up first."}

    row = rows[0]
    if not verify_password(password, row["password_hash"]):
        return {"error": "Invalid password."}

    # Get clean display name — never expose sensitive data
    user_name = row["name"] or ""
    # Fix corrupted name: if name equals the password, or looks like a hash, reset it
    if user_name == password or user_name.startswith("sha256:") or len(user_name) > 50:
        user_name = email.split("@")[0]
        # Fix in DB too
        db.execute("UPDATE users SET name = ?, last_login = ? WHERE id = ?",
                   [user_name, time.strftime("%Y-%m-%dT%H:%M:%SZ"), row["id"]])
    else:
        db.execute("UPDATE users SET last_login = ? WHERE id = ?", [time.strftime("%Y-%m-%dT%H:%M:%SZ"), row["id"]])

    return {"token": make_token(row["id"], row["email"], user_name), "user": {"id": row["id"], "email": row["email"], "name": user_name}}
