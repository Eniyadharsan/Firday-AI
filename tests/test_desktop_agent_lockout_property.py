# Feature: friday-desktop-agent, Property 4: Lockout after repeated invalid tokens
"""
Property-based tests for the Session Token Authenticator lockout policy.

Property 4: Lockout after repeated invalid tokens
For any sequence of timestamped invalid-token attempts, once more than 5
invalid attempts occur within any 60-second window the Desktop_Agent SHALL
refuse new connection attempts for at least 60 seconds and SHALL record the
lockout.

**Validates: Requirements 1.7**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.auth import (
    LOCKOUT_DURATION_SECONDS,
    LOCKOUT_WINDOW_SECONDS,
    MAX_INVALID_ATTEMPTS,
    SessionTokenAuthenticator,
)


# --- Property 4: Lockout after repeated invalid tokens ---


@settings(max_examples=100, deadline=None)
@given(
    base=st.floats(min_value=0.0, max_value=1_000_000.0),
    # More than MAX_INVALID_ATTEMPTS (5) failures, all falling strictly
    # inside a single 60-second window so every failure is counted.
    offsets=st.lists(
        st.floats(
            min_value=0.0,
            max_value=LOCKOUT_WINDOW_SECONDS - 1.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=MAX_INVALID_ATTEMPTS + 1,
        max_size=25,
    ),
)
def test_more_than_five_failures_in_window_trigger_lockout(base, offsets):
    """
    Property 4: Lockout after repeated invalid tokens (trigger case)

    When more than 5 invalid-token attempts occur within a 60-second window,
    the authenticator SHALL enter a lockout state that refuses new attempts
    for at least 60 seconds from the triggering attempt.

    # Feature: friday-desktop-agent, Property 4: Lockout after repeated invalid tokens
    **Validates: Requirements 1.7**
    """
    offsets = sorted(offsets)
    auth = SessionTokenAuthenticator()

    locked = False
    for off in offsets:
        locked = auth.register_failure(base + off)

    # The lockout signal is raised once the window count exceeds 5. The caller
    # uses this return value to record the lockout in the Audit_Log.
    assert locked is True, (
        f"Expected lockout after {len(offsets)} failures within a "
        f"{LOCKOUT_WINDOW_SECONDS}s window"
    )

    # The 6th failure (index 5) is the earliest possible trigger. The lockout
    # must last at least LOCKOUT_DURATION_SECONDS from that triggering attempt.
    trigger_time = base + offsets[MAX_INVALID_ATTEMPTS]
    just_before_expiry = trigger_time + LOCKOUT_DURATION_SECONDS - 0.001
    assert auth.is_locked_out(just_before_expiry) is True, (
        "Agent must refuse new attempts for at least "
        f"{LOCKOUT_DURATION_SECONDS}s after the triggering failure"
    )

    # It must also still be locked immediately after the final recorded attempt.
    last_attempt = base + offsets[-1]
    assert auth.is_locked_out(last_attempt) is True


@settings(max_examples=100, deadline=None)
@given(
    base=st.floats(min_value=0.0, max_value=1_000_000.0),
    # At most MAX_INVALID_ATTEMPTS (5) failures within the window: not enough
    # to trip the "more than 5" threshold.
    offsets=st.lists(
        st.floats(
            min_value=0.0,
            max_value=LOCKOUT_WINDOW_SECONDS - 1.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=0,
        max_size=MAX_INVALID_ATTEMPTS,
    ),
)
def test_five_or_fewer_failures_do_not_lock_out(base, offsets):
    """
    Property 4: Lockout after repeated invalid tokens (threshold boundary)

    Five or fewer invalid attempts within the window SHALL NOT trigger a
    lockout, confirming the threshold is strictly "more than 5".

    # Feature: friday-desktop-agent, Property 4: Lockout after repeated invalid tokens
    **Validates: Requirements 1.7**
    """
    offsets = sorted(offsets)
    auth = SessionTokenAuthenticator()

    for off in offsets:
        auth.register_failure(base + off)

    check_time = base + (offsets[-1] if offsets else 0.0)
    assert auth.is_locked_out(check_time) is False, (
        f"{len(offsets)} failures (<= {MAX_INVALID_ATTEMPTS}) must not "
        "trigger a lockout"
    )
