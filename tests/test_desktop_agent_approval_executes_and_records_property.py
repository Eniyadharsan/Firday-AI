# Feature: friday-desktop-agent, Property 15: Approval executes and records
"""Property-based tests for approving a Risky_Action's Confirmation_Prompt.

Property 15: Approval executes and records
- For any Risky_Action whose Confirmation_Prompt is approved, the Desktop_Agent
  SHALL execute the action and record the approval in the Audit_Log.

The Confirmation Manager (friday/desktop_agent/confirmation.py) is the risk
gate (Layer 7) of the enforcement gauntlet. When a Structured_Command
references a Risky_Action it raises a pending :class:`ConfirmationPrompt` and
withholds execution. This property drives the manager across every *risky*
Registered_Command (``window_management`` and ``lock_pc``) with valid
parameters, raises the prompt, then approves it inside the 30-second window,
and asserts:

- the associated action is actually executed -- the matching OS handler on the
  injected seam is invoked and the returned result reflects the handler
  outcome (exactly SUCCESS or FAILURE), and
- the approval is recorded in the Audit_Log as a ``confirmation`` entry whose
  outcome is ``approved`` for the same command (Req 6.3).

All OS side effects are isolated behind a fake :class:`OSHandlers` seam and the
Audit_Log is a collecting fake (mirroring the ``tests/_adapter_fakes.py``
pattern), so the property tests the manager's approve/execute/record logic, not
the OS.

Validates: Requirements 6.3
"""

from __future__ import annotations

from typing import Any, Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.confirmation import (
    EVENT_CONFIRMATION,
    ConfirmationManager,
)
from friday.desktop_agent.executor import CommandExecutor
from friday.desktop_agent.models import (
    AuditEntry,
    CommandStatus,
    RiskClass,
    StructuredCommand,
)
from friday.desktop_agent.registry import all_commands, lookup


class _FakeOSHandlers:
    """Fake OS seam standing in for every real operating-system side effect.

    Implements the full :class:`OSHandlers` protocol. Every handler records the
    call and either returns cleanly or raises a configured exception, according
    to ``should_raise``. No real OS action is ever performed, so an approved
    risky action's execution path is exercised in isolation (mirroring the
    ``tests/_adapter_fakes.py`` fake pattern).
    """

    def __init__(self, should_raise: bool = False) -> None:
        self._should_raise = should_raise
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if self._should_raise:
            raise RuntimeError(f"simulated OS failure in {name}")

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


class _CollectingAudit:
    """Collecting fake Audit_Log sink that records every appended entry."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


# --------------------------------------------------------------------------- #
# Generators producing a valid Structured_Command for each *risky* command.
#
# Only the risky commands in the allow-list raise a Confirmation_Prompt, so the
# property is scoped to them: ``window_management`` and ``lock_pc``. Parameters
# satisfy each command's schema so the approved action reaches its handler.
# --------------------------------------------------------------------------- #

_confidences = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)


def _window_management() -> st.SearchStrategy[StructuredCommand]:
    with_target = st.fixed_dictionaries(
        {
            "action": st.sampled_from(
                ["minimize", "maximize", "restore", "focus", "close"]
            ),
            "target": st.text(min_size=1, max_size=64),
        }
    )
    without_target = st.fixed_dictionaries(
        {
            "action": st.sampled_from(
                ["minimize", "maximize", "restore", "focus", "close"]
            )
        }
    )
    return st.builds(
        StructuredCommand,
        command_id=st.just("window_management"),
        parameters=st.one_of(with_target, without_target),
        confidence=_confidences,
    )


def _lock_pc() -> st.SearchStrategy[StructuredCommand]:
    return st.builds(
        StructuredCommand,
        command_id=st.just("lock_pc"),
        parameters=st.just({}),
        confidence=_confidences,
    )


def _risky_commands() -> st.SearchStrategy[StructuredCommand]:
    """Generate a valid Structured_Command for any risky Registered_Command."""
    return st.one_of(_window_management(), _lock_pc())


# The OS-seam method each risky command's handler dispatches to. Used to assert
# the action was actually executed on approval.
_EXPECTED_SEAM = {
    "window_management": "window_action",
    "lock_pc": "lock_workstation",
}


def test_generators_cover_the_risky_registry() -> None:
    """Sanity check: a generator exists for every risky Registered_Command.

    Guards against registry drift: if a new risky command is added without a
    matching generator, this test fails so the property stays comprehensive.
    """
    covered = {"window_management", "lock_pc"}
    risky = {
        command.command_id
        for command in all_commands()
        if command.risk_class is RiskClass.RISKY
    }
    assert risky == covered


# Feature: friday-desktop-agent, Property 15: Approval executes and records
@settings(max_examples=200)
@given(
    command=_risky_commands(),
    created_at=st.floats(
        min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
    ),
    # Approve strictly inside the 30-second confirmation window (Req 6.5), so
    # approval always executes rather than being cancelled as a timeout.
    approve_delay=st.floats(
        min_value=0.0, max_value=29.0, allow_nan=False, allow_infinity=False
    ),
    handler_raises=st.booleans(),
)
def test_approving_risky_action_executes_and_records_approval(
    command: StructuredCommand,
    created_at: float,
    approve_delay: float,
    handler_raises: bool,
) -> None:
    """Approving a pending risky prompt executes the action and records it.

    For any risky command, raising then approving its Confirmation_Prompt
    inside the timeout window MUST: (a) execute the action -- the matching OS
    handler is invoked and the result is exactly SUCCESS or FAILURE reflecting
    the handler outcome -- and (b) append a ``confirmation``/``approved`` audit
    entry for that command (Req 6.3).

    Validates: Requirements 6.3
    """
    handlers = _FakeOSHandlers(should_raise=handler_raises)
    audit = _CollectingAudit()
    executor = CommandExecutor(handlers, audit_sink=audit.append)
    manager = ConfirmationManager(executor, audit_sink=audit.append)

    registered = lookup(command.command_id)
    assert registered is not None and registered.risk_class is RiskClass.RISKY

    # Raise the prompt: execution is withheld pending confirmation (Req 6.1/6.2).
    pending = manager.require_confirmation(command, registered, now=created_at)
    assert pending.status is CommandStatus.CONFIRMATION_REQUIRED
    # Exactly one prompt is now pending; grab its id.
    prompt_ids = manager.pending_prompt_ids
    assert len(prompt_ids) == 1
    prompt_id = next(iter(prompt_ids))

    # Nothing has executed yet while the prompt is unresolved.
    assert handlers.calls == []

    # Approve within the confirmation window.
    result = manager.approve(prompt_id, now=created_at + approve_delay)

    # (a) The action was executed: exactly one OS-seam call to the command's
    # own handler, and the result is exactly SUCCESS or FAILURE reflecting it.
    assert len(handlers.calls) == 1, "approval must execute the risky action once"
    assert handlers.calls[0][0] == _EXPECTED_SEAM[command.command_id]
    assert result.status in (CommandStatus.SUCCESS, CommandStatus.FAILURE)
    assert result.status is (
        CommandStatus.FAILURE if handler_raises else CommandStatus.SUCCESS
    )

    # The prompt is resolved and no longer pending (cannot be double-approved).
    assert not manager.is_pending(prompt_id)

    # (b) The approval is recorded in the Audit_Log for this command.
    approvals = [
        e
        for e in audit.entries
        if e.event_type == EVENT_CONFIRMATION and e.outcome == "approved"
    ]
    assert len(approvals) == 1, "approval must be recorded exactly once"
    approval = approvals[0]
    assert approval.command_id == command.command_id
    assert approval.parameters == command.parameters
    assert approval.timestamp  # a timestamp is always recorded


# Feature: friday-desktop-agent, Property 15: Approval executes and records
@settings(max_examples=200)
@given(
    command=_risky_commands(),
    created_at=st.floats(
        min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
    ),
    approve_delay=st.floats(
        min_value=0.0, max_value=29.0, allow_nan=False, allow_infinity=False
    ),
)
def test_approval_recorded_before_execution_record(
    command: StructuredCommand,
    created_at: float,
    approve_delay: float,
) -> None:
    """The approval record precedes the execution record for the same command.

    On approval the manager first records the ``approved`` confirmation entry,
    then delegates to the executor which records the ``execute`` outcome. Both
    entries for the command are present in the Audit_Log, confirming the
    approval is durably recorded alongside the execution (Req 6.3).

    Validates: Requirements 6.3
    """
    handlers = _FakeOSHandlers(should_raise=False)
    audit = _CollectingAudit()
    executor = CommandExecutor(handlers, audit_sink=audit.append)
    manager = ConfirmationManager(executor, audit_sink=audit.append)

    registered = lookup(command.command_id)
    assert registered is not None

    manager.require_confirmation(command, registered, now=created_at)
    prompt_id = next(iter(manager.pending_prompt_ids))
    manager.approve(prompt_id, now=created_at + approve_delay)

    kinds = [(e.event_type, e.outcome) for e in audit.entries]
    assert (EVENT_CONFIRMATION, "approved") in kinds
    assert ("execute", "success") in kinds
    # The approval is recorded ahead of the execution outcome.
    assert kinds.index((EVENT_CONFIRMATION, "approved")) < kinds.index(
        ("execute", "success")
    )
