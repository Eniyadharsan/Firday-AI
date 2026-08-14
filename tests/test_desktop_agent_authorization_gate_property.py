# Feature: friday-desktop-agent, Property 5: Authorization gate
"""Property-based tests for the Desktop_Agent Authorization Manager gate.

Property 5: Authorization gate
For any command execution request while User_Authorization is absent or has
been revoked, the Desktop_Agent SHALL decline execution and return an
authorization-required status; and for any authorization grant, the
Desktop_Agent SHALL append an audit entry recording the event, scope, and
timestamp.

Validates: Requirements 2.1, 2.2, 2.4, 2.5
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.authorization import AuthorizationManager
from friday.desktop_agent.models import AuditEntry, CommandStatus

# Epoch-second range kept finite/positive so timestamp arithmetic and ISO
# conversion stay well-behaved. Roughly year 2001..2035.
_times = st.floats(
    min_value=1_000_000_000.0,
    max_value=2_000_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Non-negative offsets (seconds) used to advance a monotonic-style clock.
_offsets = st.floats(
    min_value=0.0,
    max_value=100_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Permission scopes granted on authorization. Allow the empty set too.
_scopes = st.lists(
    st.text(min_size=1, max_size=24),
    min_size=0,
    max_size=6,
    unique=True,
)


def _expected_iso(epoch_seconds: float) -> str:
    """Recompute the ISO 8601 UTC timestamp the manager should record."""
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


@settings(max_examples=200)
@given(now=_times)
def test_absent_authorization_declines_with_authorization_required(now: float) -> None:
    """A fresh (never-granted) manager gates every request (Req 2.1, 2.2).

    On first start User_Authorization is absent, so the gate declines execution
    and returns an ``authorization-required`` status.
    """
    manager = AuthorizationManager()

    result = manager.require_authorization()

    assert manager.is_authorized is False
    assert result is not None
    assert result.status == CommandStatus.AUTHORIZATION_REQUIRED


@settings(max_examples=200)
@given(scope=_scopes, grant_at=_times, offset=_offsets)
def test_grant_records_audit_entry_with_event_scope_and_timestamp(
    scope: list[str], grant_at: float, offset: float
) -> None:
    """A grant opens the gate and appends an audit entry (Req 2.4).

    The appended entry records the authorization event, the granted scope, and
    the grant timestamp. After a grant the gate permits execution.
    """
    recorded: list[AuditEntry] = []
    manager = AuthorizationManager(audit_sink=recorded.append)

    returned = manager.grant(scope, now=grant_at)

    # Gate now permits execution (Req 2.1 satisfied once authorized).
    assert manager.is_authorized is True
    assert manager.require_authorization() is None

    # Exactly one audit entry was appended for the grant, and it matches the
    # entry returned by grant().
    assert len(recorded) == 1
    entry = recorded[0]
    assert entry == returned

    # The entry records the event, scope, and timestamp (Req 2.4).
    assert entry.event_type == "authorize"
    assert entry.outcome == "granted"
    assert entry.parameters == {"scope": sorted(set(scope))}
    assert entry.timestamp == _expected_iso(grant_at)


@settings(max_examples=200)
@given(scope=_scopes, grant_at=_times, offset=_offsets)
def test_revoked_authorization_declines_with_authorization_required(
    scope: list[str], grant_at: float, offset: float
) -> None:
    """After revocation the gate declines again immediately (Req 2.2, 2.5).

    Revocation flips the authorization state synchronously (well within the
    1-second bound), so the very next gate check declines execution with an
    ``authorization-required`` status and the revocation is recorded.
    """
    recorded: list[AuditEntry] = []
    manager = AuthorizationManager(audit_sink=recorded.append)

    manager.grant(scope, now=grant_at)
    assert manager.require_authorization() is None  # authorized after grant

    revoke_at = grant_at + offset
    revoke_entry = manager.revoke(now=revoke_at)

    # Gate declines immediately after revocation (Req 2.5).
    assert manager.is_authorized is False
    result = manager.require_authorization()
    assert result is not None
    assert result.status == CommandStatus.AUTHORIZATION_REQUIRED

    # The revocation was recorded with its timestamp.
    assert revoke_entry.event_type == "revoke"
    assert revoke_entry.timestamp == _expected_iso(revoke_at)
    assert recorded[-1] == revoke_entry
