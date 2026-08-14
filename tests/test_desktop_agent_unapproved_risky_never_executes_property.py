# Feature: friday-desktop-agent, Property 16: Unapproved risky action never executes
"""Property-based tests for the Confirmation Manager's fail-closed behavior.

Property 16: Unapproved risky action never executes
- For any Risky_Action whose Confirmation_Prompt is declined or receives no
  response within 30 seconds, the Desktop_Agent SHALL cancel the action
  without executing it and SHALL record the cancellation reason (declined or
  timeout) in the Audit_Log.

The Confirmation Manager (friday/desktop_agent/confirmation.py) is the risk
gate (Layer 7) of the enforcement gauntlet. When a Structured_Command
references a Risky_Action it raises a pending :class:`ConfirmationPrompt` and
withholds execution. This property drives the two "unapproved" resolution
paths -- an explicit decline and a 30-second timeout -- across arbitrary risky
commands and clock values, and asserts that in both cases:

- the resolution status is ``CANCELLED``,
- no OS side effect ever occurs (the executor's OS seam is never invoked),
- the prompt is removed from the pending set, and
- exactly one audit entry is recorded whose outcome is ``cancelled`` and whose
  reason is ``declined`` (decline path) or ``timeout`` (timeout path).

All OS side effects are isolated behind a fake seam (mirroring the
``tests/_adapter_fakes.py`` pattern), so the property tests the manager's
cancellation logic, not the OS.

Validates: Requirements 6.4, 6.5
"""

from __future__ import annotations

from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.confirmation import (
    DEFAULT_TIMEOUT_SECONDS,
    EVENT_CONFIRMATION,
    REASON_DECLINED,
    REASON_TIMEOUT,
    ConfirmationManager,
)
from friday.desktop_agent.executor import CommandExecutor
from friday.desktop_agent.models import (
    AuditEntry,
    CommandStatus,
    RiskClass,
    StructuredCommand,
)
from friday.desktop_agent.registry import all_commands


class _OSHandlersSpy:
    """Fake OS seam that records calls but performs no real side effect.

    Implements the full :class:`OSHandlers` protocol. If the Confirmation
    Manager ever executes an unapproved risky action, one of these methods
    would be invoked and ``calls`` would become non-empty -- which Property 16
    forbids. No real OS action is ever performed (mirrors the
    ``tests/_adapter_fakes.py`` fake pattern).
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def _record(self, name: str, *args) -> None:
        self.calls.append((name, args))

    def launch_app(self, app_name: str) -> None:
        self._record("launch_app", app_name)

    def open_path(self, path: str) -> None:
        self._record("open_path", path)

    def open_browser(self, url: str) -> None:
        self._record("open_browser", url)

    def set_volume(self, level: int) -> None:
        self._record("set_volume", level)

    def media_action(self, action: str) -> None:
        self._record("media_action", action)

    def type_text(self, text: str) -> None:
        self._record("type_text", text)

    def window_action(self, action: str, target: Optional[str]) -> None:
        self._record("window_action", action, target)

    def lock_workstation(self) -> None:
        self._record("lock_workstation")


# The risky commands in the real Command_Registry. Only a Risky_Action reaches
# the Confirmation Manager's risk gate, so the generators are constrained to
# the registry's risky entries to keep the input space realistic.
_RISKY_COMMAND_IDS = tuple(
    command.command_id
    for command in all_commands()
    if command.risk_class is RiskClass.RISKY
)

_confidences = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Arbitrary parameter maps forwarded with the request. Parameters are
# irrelevant to cancellation (the action never executes), so they are free.
_parameters = st.dictionaries(
    keys=st.text(min_size=1, max_size=16),
    values=st.one_of(
        st.text(max_size=32),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
    ),
    max_size=5,
)

# Epoch-second range kept finite/positive so timestamp arithmetic and ISO
# conversion stay well-behaved. Roughly year 2001..2035.
_times = st.floats(
    min_value=1_000_000_000.0,
    max_value=2_000_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)


def _risky_commands() -> st.SearchStrategy[StructuredCommand]:
    """Generate a Structured_Command referencing a Risky_Action."""
    return st.builds(
        StructuredCommand,
        command_id=st.sampled_from(_RISKY_COMMAND_IDS),
        parameters=_parameters,
        confidence=_confidences,
    )


def _make_manager() -> tuple[ConfirmationManager, _OSHandlersSpy, list[AuditEntry]]:
    """Build a ConfirmationManager wired to a spy executor and audit sink."""
    handlers = _OSHandlersSpy()
    audit: list[AuditEntry] = []
    executor = CommandExecutor(handlers, audit_sink=audit.append)
    manager = ConfirmationManager(executor, audit_sink=audit.append)
    return manager, handlers, audit


# Feature: friday-desktop-agent, Property 16: Unapproved risky action never executes
@settings(max_examples=200)
@given(command=_risky_commands(), created_at=_times, delta=st.floats(
    min_value=0.0, max_value=DEFAULT_TIMEOUT_SECONDS, allow_nan=False, allow_infinity=False
))
def test_declined_risky_action_is_cancelled_without_executing(
    command: StructuredCommand, created_at: float, delta: float
) -> None:
    """A declined risky action is cancelled, never executed, and recorded.

    Raising then declining the prompt must yield a ``CANCELLED`` result, invoke
    no OS handler, clear the pending prompt, and append exactly one audit entry
    recording the ``declined`` reason (Req 6.4).

    Validates: Requirements 6.4
    """
    manager, handlers, audit = _make_manager()

    raised = manager.require_confirmation(command, None, now=created_at)
    assert raised.status == CommandStatus.CONFIRMATION_REQUIRED
    prompt_id = next(iter(manager.pending_prompt_ids))

    result = manager.decline(prompt_id, now=created_at + delta)

    # Cancelled, not executed.
    assert result.status == CommandStatus.CANCELLED
    assert result.command_id == command.command_id
    assert handlers.calls == [], "a declined risky action must not touch the OS"

    # The prompt is resolved (no longer pending) and cannot be double-resolved.
    assert prompt_id not in manager.pending_prompt_ids

    # Exactly one cancellation audit entry recording the declined reason.
    cancellations = [e for e in audit if e.event_type == EVENT_CONFIRMATION]
    assert len(cancellations) == 1
    entry = cancellations[0]
    assert entry.outcome == "cancelled"
    assert entry.reason == REASON_DECLINED
    assert entry.command_id == command.command_id
    assert entry.timestamp  # a timestamp is always recorded


# Feature: friday-desktop-agent, Property 16: Unapproved risky action never executes
@settings(max_examples=200)
@given(command=_risky_commands(), created_at=_times, overshoot=st.floats(
    min_value=0.0, max_value=100_000.0, allow_nan=False, allow_infinity=False
))
def test_timed_out_risky_action_is_cancelled_without_executing(
    command: StructuredCommand, created_at: float, overshoot: float
) -> None:
    """A risky action with no response within 30s is cancelled and recorded.

    Sweeping timeouts at or after the 30-second window must cancel the pending
    prompt, invoke no OS handler, clear the prompt, and append exactly one
    audit entry recording the ``timeout`` reason (Req 6.5).

    Validates: Requirements 6.5
    """
    manager, handlers, audit = _make_manager()

    manager.require_confirmation(command, None, now=created_at)
    prompt_id = next(iter(manager.pending_prompt_ids))

    # No response arrives; the confirmation window elapses (>= 30 seconds).
    now = created_at + DEFAULT_TIMEOUT_SECONDS + overshoot
    cancelled = manager.check_timeouts(now=now)

    assert len(cancelled) == 1
    assert cancelled[0].status == CommandStatus.CANCELLED
    assert cancelled[0].command_id == command.command_id
    assert handlers.calls == [], "a timed-out risky action must not touch the OS"

    # The prompt is resolved (no longer pending).
    assert prompt_id not in manager.pending_prompt_ids

    # Exactly one cancellation audit entry recording the timeout reason.
    cancellations = [e for e in audit if e.event_type == EVENT_CONFIRMATION]
    assert len(cancellations) == 1
    entry = cancellations[0]
    assert entry.outcome == "cancelled"
    assert entry.reason == REASON_TIMEOUT
    assert entry.command_id == command.command_id
    assert entry.timestamp


# Feature: friday-desktop-agent, Property 16: Unapproved risky action never executes
@settings(max_examples=200)
@given(command=_risky_commands(), created_at=_times, overshoot=st.floats(
    min_value=0.0, max_value=100_000.0, allow_nan=False, allow_infinity=False
))
def test_approval_after_timeout_never_executes(
    command: StructuredCommand, created_at: float, overshoot: float
) -> None:
    """An approval landing after the 30s window is rejected as a timeout.

    The manager fails closed: even an approve() call cannot execute a prompt
    whose confirmation window has already elapsed. The action is cancelled as a
    timeout and never touches the OS (Req 6.5).

    Validates: Requirements 6.5
    """
    manager, handlers, audit = _make_manager()

    manager.require_confirmation(command, None, now=created_at)
    prompt_id = next(iter(manager.pending_prompt_ids))

    now = created_at + DEFAULT_TIMEOUT_SECONDS + overshoot
    result = manager.approve(prompt_id, now=now)

    assert result.status == CommandStatus.CANCELLED
    assert handlers.calls == [], "an expired approval must not touch the OS"
    assert prompt_id not in manager.pending_prompt_ids

    cancellations = [e for e in audit if e.event_type == EVENT_CONFIRMATION]
    assert len(cancellations) == 1
    assert cancellations[0].reason == REASON_TIMEOUT
