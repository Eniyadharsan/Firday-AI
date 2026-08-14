# Feature: friday-desktop-agent, Property 3: Token validation and expiry
"""Property-based test for Desktop_Agent session token validation and expiry.

Property 3: Token validation and expiry
For any presented token and current time, the Desktop_Agent SHALL accept the
request only if the token is a currently-issued token whose expiry has not
passed; every issued token's lifetime SHALL be at most 3600 seconds, and any
missing, unknown, or expired token SHALL be declined and require
re-authentication.

Validates: Requirements 1.5, 1.6, 11.3, 11.4, 11.5
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.auth import (
    MAX_TOKEN_TTL_SECONDS,
    SessionTokenAuthenticator,
)

# Reasonable epoch-second range for issuance times (kept finite/positive so
# arithmetic stays well-behaved). Roughly year 2001..2035.
_issue_times = st.floats(
    min_value=1_000_000_000.0,
    max_value=2_000_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Desired TTLs spanning below, at, and above the 3600s ceiling so we exercise
# the clamp in issue_token (Req 1.6).
_ttls = st.floats(
    min_value=0.001,
    max_value=100_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Non-negative offsets (seconds) used to probe times before/after expiry.
_offsets = st.floats(
    min_value=0.0,
    max_value=100_000.0,
    allow_nan=False,
    allow_infinity=False,
)


@settings(max_examples=200)
@given(ttl=_ttls, issued_at=_issue_times)
def test_issued_token_lifetime_is_at_most_3600s(ttl: float, issued_at: float) -> None:
    """Every issued token expires no later than 3600s after issuance (Req 1.6)."""
    auth = SessionTokenAuthenticator(token_ttl_seconds=ttl)
    token = auth.issue_token(now=issued_at)

    lifetime = token.expires_at - token.issued_at
    assert token.issued_at == issued_at
    # Lifetime is positive and never exceeds the 3600s ceiling.
    assert 0 < lifetime <= MAX_TOKEN_TTL_SECONDS + 1e-6


@settings(max_examples=200)
@given(ttl=_ttls, issued_at=_issue_times, offset=_offsets)
def test_valid_token_accepted_only_before_expiry(
    ttl: float, issued_at: float, offset: float
) -> None:
    """A currently-issued token is accepted iff the current time is before expiry.

    At or after expiry the token is declined with reason ``expired`` and, once
    invalidated, is no longer accepted at any time (Req 1.5, 1.6, 11.5).
    """
    auth = SessionTokenAuthenticator(token_ttl_seconds=ttl)
    token = auth.issue_token(now=issued_at)
    now = issued_at + offset

    result = auth.validate_token(token.value, now=now)

    if now < token.expires_at:
        assert result.valid is True
        assert result.reason is None
    else:
        # At or past expiry: declined as expired (Req 1.6, 11.4).
        assert result.valid is False
        assert result.reason == "expired"
        # Re-authentication required: the expired token is invalidated, so a
        # subsequent presentation (even before its original expiry) is unknown.
        again = auth.validate_token(token.value, now=issued_at)
        assert again.valid is False
        assert again.reason == "invalid"


@settings(max_examples=200)
@given(
    presented=st.one_of(st.none(), st.just(""), st.text(min_size=1, max_size=64)),
    now=_issue_times,
)
def test_missing_or_unknown_token_is_declined(presented, now: float) -> None:
    """A missing or never-issued token is always declined (Req 1.5, 11.3, 11.4).

    The authenticator has issued no tokens, so any presented value that is
    missing (None/empty) is declined as ``missing`` and any non-empty value is
    unknown and declined as ``invalid``.
    """
    auth = SessionTokenAuthenticator()

    result = auth.validate_token(presented, now=now)

    assert result.valid is False
    if not presented:
        assert result.reason == "missing"
    else:
        assert result.reason == "invalid"


@settings(max_examples=200)
@given(ttl=_ttls, issued_at=_issue_times, offset=_offsets)
def test_only_currently_issued_tokens_are_accepted(
    ttl: float, issued_at: float, offset: float
) -> None:
    """A token value that differs from the issued one is never accepted.

    Guards the "currently-issued" clause of Property 3: presenting an unknown
    value while a valid token exists must still be declined (Req 11.4).
    """
    auth = SessionTokenAuthenticator(token_ttl_seconds=ttl)
    token = auth.issue_token(now=issued_at)
    now = issued_at + offset

    # A value guaranteed not to equal the issued token value.
    unknown = token.value + "x"
    result = auth.validate_token(unknown, now=now)

    assert result.valid is False
    assert result.reason == "invalid"
