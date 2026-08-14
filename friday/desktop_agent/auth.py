"""Session token authentication and rate limiting for the Desktop_Agent.

This module implements the Session Token Authenticator described in
design.md ("Session Token Authenticator"). It is responsible for the second
layer of the Desktop_Agent enforcement gauntlet: issuing high-entropy,
expiring per-session tokens, validating presented tokens on every command
request, and enforcing a lockout after repeated invalid-token attempts.

Design guarantees enforced here:

- Every issued token carries at least 128 bits of entropy and expires no
  later than 3600 seconds after issuance (Req 1.4, 1.6).
- Missing, unknown, or expired tokens are rejected; once a token reaches its
  expiry it is invalidated and re-authentication is required (Req 1.5, 11.3,
  11.4, 11.5).
- After more than 5 invalid-token attempts within any 60-second window, new
  connection attempts are refused for at least 60 seconds (Req 1.7).

Time is injected via ``now`` parameters (epoch seconds) so the logic is pure
and testable without wall-clock dependencies.

**Validates: Requirements 1.4, 1.5, 1.6, 1.7, 11.3, 11.4, 11.5**
"""

from __future__ import annotations

import secrets
import time
from typing import Optional

from friday.desktop_agent.models import AuthResult, SessionToken

# secrets.token_urlsafe(32) draws 32 random bytes = 256 bits of entropy,
# comfortably above the 128-bit floor required by Req 1.4.
_TOKEN_NBYTES = 32

# Maximum lifetime of a session token in seconds (Req 1.6).
MAX_TOKEN_TTL_SECONDS = 3600

# Lockout tuning (Req 1.7): more than this many invalid attempts within
# LOCKOUT_WINDOW_SECONDS triggers a lockout lasting at least
# LOCKOUT_DURATION_SECONDS.
MAX_INVALID_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 60.0
LOCKOUT_DURATION_SECONDS = 60.0


class SessionTokenAuthenticator:
    """Issues, validates, and rate-limits per-session authentication tokens.

    A single authenticator instance manages the set of currently-issued
    tokens for the Desktop_Agent's Local_Channel plus the invalid-attempt
    bookkeeping used to enforce the lockout policy.

    The class is intentionally free of any wall-clock coupling: callers pass
    the current time (epoch seconds) into every time-sensitive method so the
    behavior is deterministic and property-testable.

    **Validates: Requirements 1.4, 1.5, 1.6, 1.7, 11.3, 11.4, 11.5**
    """

    def __init__(self, token_ttl_seconds: float = MAX_TOKEN_TTL_SECONDS) -> None:
        """Initialize the authenticator.

        Args:
            token_ttl_seconds: Desired token lifetime in seconds. Clamped to
                the inclusive range ``(0, MAX_TOKEN_TTL_SECONDS]`` so an issued
                token can never outlive the 3600-second ceiling (Req 1.6).
        """
        if token_ttl_seconds <= 0:
            raise ValueError("token_ttl_seconds must be positive")
        # Never allow a lifetime beyond the 3600s ceiling (Req 1.6).
        self._token_ttl_seconds: float = min(
            float(token_ttl_seconds), float(MAX_TOKEN_TTL_SECONDS)
        )
        # Currently-issued tokens keyed by their opaque value.
        self._tokens: dict[str, SessionToken] = {}
        # Epoch-second timestamps of recent invalid-token attempts.
        self._failures: list[float] = []
        # Epoch second until which new attempts are refused; 0.0 means no
        # active lockout.
        self._locked_until: float = 0.0

    def issue_token(self, now: Optional[float] = None) -> SessionToken:
        """Create and register a new per-session token.

        The token value is generated with ``secrets.token_urlsafe(32)`` which
        yields 256 bits of entropy (>=128-bit floor, Req 1.4). Its expiry is
        set exactly ``token_ttl_seconds`` after issuance and never exceeds
        ``issued_at + 3600`` (Req 1.6).

        Args:
            now: Issuance time in epoch seconds. Defaults to the current
                wall-clock time when omitted.

        Returns:
            The newly issued and registered :class:`SessionToken`.

        **Validates: Requirements 1.4, 1.6**
        """
        issued_at = time.time() if now is None else float(now)
        expires_at = issued_at + self._token_ttl_seconds
        value = secrets.token_urlsafe(_TOKEN_NBYTES)
        token = SessionToken(
            value=value,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self._tokens[value] = token
        return token

    def validate_token(
        self, presented: Optional[str], now: Optional[float] = None
    ) -> AuthResult:
        """Validate a presented token value against the issued set.

        A request is accepted only if the presented value corresponds to a
        currently-issued token whose expiry has not passed. Expired tokens are
        invalidated on inspection so that re-authentication is required
        (Req 11.5).

        Args:
            presented: The token value presented on the request, or ``None``.
            now: Current time in epoch seconds. Defaults to wall-clock time.

        Returns:
            An :class:`AuthResult` with ``valid=True`` when the token is
            currently-issued and unexpired, otherwise ``valid=False`` with a
            ``reason`` of ``"missing"``, ``"invalid"``, or ``"expired"``.

        **Validates: Requirements 1.5, 1.6, 11.3, 11.4, 11.5**
        """
        current = time.time() if now is None else float(now)

        # Missing token: absent or empty value (Req 1.5, 11.4).
        if not presented:
            return AuthResult(valid=False, reason="missing")

        # Unknown token: not among the currently-issued set (Req 11.4).
        token = self._tokens.get(presented)
        if token is None:
            return AuthResult(valid=False, reason="invalid")

        # Expired token: expiry reached or passed. Invalidate so that further
        # requests require re-authentication (Req 1.6, 11.5).
        if current >= token.expires_at:
            del self._tokens[presented]
            return AuthResult(valid=False, reason="expired")

        return AuthResult(valid=True)

    def register_failure(self, now: Optional[float] = None) -> bool:
        """Record an invalid-token attempt and update lockout state.

        Records the failure timestamp and, if more than
        ``MAX_INVALID_ATTEMPTS`` failures have occurred within any
        ``LOCKOUT_WINDOW_SECONDS`` window, engages a lockout lasting at least
        ``LOCKOUT_DURATION_SECONDS`` (Req 1.7).

        Args:
            now: Time of the failed attempt in epoch seconds. Defaults to
                wall-clock time.

        Returns:
            ``True`` if the agent is in a lockout state after recording this
            failure, else ``False``. The caller is responsible for recording
            the lockout in the Audit_Log when this transitions to ``True``.

        **Validates: Requirements 1.7**
        """
        current = time.time() if now is None else float(now)
        self._failures.append(current)

        # Drop failures outside the sliding window so the list cannot grow
        # unbounded and the count reflects only the relevant window.
        window_start = current - LOCKOUT_WINDOW_SECONDS
        self._failures = [t for t in self._failures if t > window_start]

        # More than 5 invalid attempts within the window triggers a lockout
        # for at least 60 seconds (Req 1.7).
        if len(self._failures) > MAX_INVALID_ATTEMPTS:
            self._locked_until = max(
                self._locked_until, current + LOCKOUT_DURATION_SECONDS
            )

        return self.is_locked_out(current)

    def is_locked_out(self, now: Optional[float] = None) -> bool:
        """Report whether new connection attempts are currently refused.

        Args:
            now: Current time in epoch seconds. Defaults to wall-clock time.

        Returns:
            ``True`` while the active lockout has not yet elapsed, else
            ``False``.

        **Validates: Requirements 1.7**
        """
        current = time.time() if now is None else float(now)
        return current < self._locked_until
