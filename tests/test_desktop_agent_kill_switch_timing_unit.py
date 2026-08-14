"""Unit test for the Agent State Machine Kill_Switch timing and audit.

Asserts two behaviors of ``AgentStateMachine.activate_kill_switch``:

    * New command execution requests are refused within 1 second of the
      Kill_Switch activation, measured with a monotonic clock (Req 8.2).
    * The Kill_Switch activation and its timestamp are recorded in the
      Audit_Log (Req 8.4).

The state machine flips to the ``disabled`` state synchronously inside
``activate_kill_switch(now)``, so the execution gate (``require_enabled()``)
reflects the disabled state immediately. These example tests measure the
elapsed wall time using ``time.monotonic()`` (a steady, non-decreasing clock
unaffected by system clock adjustments) between the activation and the gate
declining execution, and assert it is comfortably within the 1-second bound.
They also assert that a collecting audit sink receives a ``kill_switch`` entry
carrying the activation timestamp.

Validates: Requirements 8.2, 8.4
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from friday.desktop_agent.models import (
    AgentState,
    AuditEntry,
    CommandStatus,
)
from friday.desktop_agent.state import AgentStateMachine


KILL_SWITCH_BOUND_SECONDS = 1.0


class _AuditSpy:
    """A collecting fake standing in for the Audit_Log ``append`` seam.

    Records every :class:`AuditEntry` it receives so the test can assert the
    Kill_Switch activation was recorded (Req 8.4).
    """

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def test_new_requests_refused_within_one_second_of_kill_switch() -> None:
    """Activating the Kill_Switch refuses execution within 1s (monotonic clock).

    Validates: Requirements 8.2
    """
    machine = AgentStateMachine(initial_state=AgentState.ENABLED)

    # While enabled the execution gate allows requests through.
    assert machine.require_enabled() is None, (
        "gate should allow execution while enabled"
    )

    # Activate the Kill_Switch and measure how long until the gate refuses,
    # using a monotonic clock so the measurement is immune to wall-clock
    # adjustments.
    activation_start = time.monotonic()
    machine.activate_kill_switch(now=time.time())
    gate_result = machine.require_enabled()
    elapsed = time.monotonic() - activation_start

    # The agent must now be disabled and decline execution with a disabled
    # status (Req 8.5), and the refusal must take effect within 1s (Req 8.2).
    assert machine.is_disabled is True
    assert gate_result is not None, "gate must refuse execution after kill-switch"
    assert gate_result.status is CommandStatus.DISABLED
    assert elapsed <= KILL_SWITCH_BOUND_SECONDS, (
        f"kill-switch took {elapsed:.6f}s to take effect; "
        f"expected within {KILL_SWITCH_BOUND_SECONDS}s"
    )


def test_gate_refuses_every_subsequent_request_within_bound_after_kill_switch() -> None:
    """After the Kill_Switch fires, every later request is refused within 1s.

    Reinforces that the refusal is durable (not a one-off) and each subsequent
    gate check remains within the 1-second timing bound.

    Validates: Requirements 8.2
    """
    machine = AgentStateMachine(initial_state=AgentState.ENABLED)
    machine.activate_kill_switch(now=time.time())

    for _ in range(5):
        start = time.monotonic()
        result = machine.require_enabled()
        elapsed = time.monotonic() - start

        assert result is not None
        assert result.status is CommandStatus.DISABLED
        assert elapsed <= KILL_SWITCH_BOUND_SECONDS


def test_kill_switch_activation_is_recorded_in_audit_log() -> None:
    """The Kill_Switch activation and its timestamp are recorded (Req 8.4).

    Validates: Requirements 8.4
    """
    audit = _AuditSpy()
    machine = AgentStateMachine(
        audit_sink=audit.append, initial_state=AgentState.ENABLED
    )

    now = 1_500_000_000.0
    returned = machine.activate_kill_switch(now=now)

    # Exactly one audit entry was recorded for the activation.
    assert len(audit.entries) == 1
    entry = audit.entries[0]

    # It is a kill-switch event carrying the activation timestamp (Req 8.4).
    assert entry.event_type == "kill_switch"
    assert entry.outcome == "disabled"
    expected_timestamp = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    assert entry.timestamp == expected_timestamp

    # The recorded entry matches the one returned to the caller.
    assert returned == entry


def test_kill_switch_records_activation_regardless_of_starting_state() -> None:
    """The activation is recorded even when triggered from the observing state.

    The Kill_Switch can fire from any active state; the audit record must be
    written in every case (Req 8.4).

    Validates: Requirements 8.4
    """
    audit = _AuditSpy()
    machine = AgentStateMachine(
        audit_sink=audit.append, initial_state=AgentState.OBSERVING
    )

    machine.activate_kill_switch(now=1_600_000_000.0)

    assert machine.is_disabled is True
    assert len(audit.entries) == 1
    assert audit.entries[0].event_type == "kill_switch"
