"""Unit test for the Authorization Manager revoke timing bound.

Asserts that command execution is refused within 1 second of revoking
User_Authorization, measured with a monotonic clock.

The Authorization Manager flips its authorization state synchronously inside
``revoke(now)``, so the enforcement gate (``require_authorization()``) reflects
the revocation immediately. This example test measures the elapsed wall time,
using ``time.monotonic()`` (a steady, non-decreasing clock unaffected by system
clock adjustments), between the revoke call and the gate declining execution,
and asserts it is comfortably within the 1-second bound.

Validates: Requirements 2.5
"""

from __future__ import annotations

import time

from friday.desktop_agent.authorization import AuthorizationManager
from friday.desktop_agent.models import CommandStatus


REVOKE_BOUND_SECONDS = 1.0


def test_execution_refused_within_one_second_of_revocation() -> None:
    """Revocation stops command acceptance within 1s (monotonic clock).

    Validates: Requirements 2.5
    """
    manager = AuthorizationManager()

    # Grant first so the gate would otherwise allow execution.
    manager.grant(scope=["launch_app"], now=time.time())
    assert manager.require_authorization() is None, (
        "gate should allow execution while authorized"
    )

    # Revoke and measure how long until the gate refuses, using a monotonic
    # clock so the measurement is immune to wall-clock adjustments.
    revoke_start = time.monotonic()
    manager.revoke(now=time.time())
    gate_result = manager.require_authorization()
    elapsed = time.monotonic() - revoke_start

    # The gate must now refuse execution with an authorization-required status.
    assert gate_result is not None, "gate must refuse execution after revocation"
    assert gate_result.status is CommandStatus.AUTHORIZATION_REQUIRED

    # And the refusal must take effect within the 1-second bound (Req 2.5).
    assert elapsed <= REVOKE_BOUND_SECONDS, (
        f"revocation took {elapsed:.6f}s to take effect; "
        f"expected within {REVOKE_BOUND_SECONDS}s"
    )


def test_gate_refuses_immediately_for_every_subsequent_request_after_revoke() -> None:
    """After revocation, every later request is refused within the bound.

    Reinforces that the refusal is durable (not a one-off) and each subsequent
    gate check remains within the 1-second timing bound.

    Validates: Requirements 2.5
    """
    manager = AuthorizationManager()
    manager.grant(scope=["lock_pc"], now=time.time())
    manager.revoke(now=time.time())

    for _ in range(5):
        start = time.monotonic()
        result = manager.require_authorization()
        elapsed = time.monotonic() - start

        assert result is not None
        assert result.status is CommandStatus.AUTHORIZATION_REQUIRED
        assert elapsed <= REVOKE_BOUND_SECONDS
