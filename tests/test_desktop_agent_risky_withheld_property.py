"""Property-based test for withholding Risky_Actions until approved.

Property 14: Risky action withheld until approved
- For any Structured_Command referencing a Risky_Action, the Desktop_Agent
  SHALL present a Confirmation_Prompt and SHALL NOT perform the action's
  execution side effect while the prompt remains unresolved.

The Confirmation Manager (friday/desktop_agent/confirmation.py) implements the
risk gate (Layer 7) of the enforcement gauntlet. This property drives
``require_confirmation`` across every risky Registered_Command in the
Command_Registry, with arbitrary parameters and creation times, and asserts:

    1. A Confirmation_Prompt is presented -- the call returns a
       ``CONFIRMATION_REQUIRED`` result and a matching prompt becomes pending
       (Req 6.1).
    2. No execution side effect occurs while the prompt is unresolved -- the
       injected OS seam records zero calls, so the risky action's handler is
       never invoked as long as the prompt has not been approved (Req 6.2).

Real OS side effects are isolated behind the same injectable ``OSHandlers``
seam used elsewhere; a recording fake stands in for it so the property tests
our withholding logic, not the OS.

Validates: Requirements 6.1, 6.2
"""

from __future__ import annotations

from typing import Any, Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.confirmation import ConfirmationManager
from friday.desktop_agent.executor import CommandExecutor
from friday.desktop_agent.models import CommandStatus, RiskClass, StructuredCommand
from friday.desktop_agent.registry import all_commands


class _RecordingOSHandlers:
    """Recording stand-in for the ``OSHandlers`` seam (no real OS actions).

    Every method appends to ``calls`` instead of performing a side effect, so
    a test can assert that *no* handler ran while a Confirmation_Prompt is
    still pending. Mirrors the recording-fake approach used across the
    desktop-agent tests.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def launch_app(self, app_name: str) -> None:
        self.calls.append("launch_app")

    def open_path(self, path: str) -> None:
        self.calls.append("open_path")

    def open_browser(self, url: str) -> None:
        self.calls.append("open_browser")

    def set_volume(self, level: int) -> None:
        self.calls.append("set_volume")

    def media_action(self, action: str) -> None:
        self.calls.append("media_action")

    def type_text(self, text: str) -> None:
        self.calls.append("type_text")

    def window_action(self, action: str, target: Optional[str]) -> None:
        self.calls.append("window_action")

    def lock_workstation(self) -> None:
        self.calls.append("lock_workstation")


# The set of risky command identifiers taken directly from the live registry,
# so the property tracks the registry rather than a hard-coded list.
_RISKY_COMMAND_IDS = sorted(
    command.command_id
    for command in all_commands()
    if command.risk_class is RiskClass.RISKY
)

# Sanity guard: the property is only meaningful if the registry actually
# classifies at least one command as risky.
assert _RISKY_COMMAND_IDS, "Expected at least one risky command in the registry"


# Arbitrary parameter maps: keys and JSON-ish values. Parameters are
# irrelevant to withholding -- a risky action must be withheld regardless of
# what it carries -- so we generate a broad, unconstrained space.
_parameters = st.dictionaries(
    keys=st.text(min_size=0, max_size=12),
    values=st.one_of(
        st.text(max_size=32),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
        st.none(),
    ),
    max_size=5,
)


@st.composite
def _risky_commands(draw: st.DrawFn) -> StructuredCommand:
    """Generate a Structured_Command referencing a risky Registered_Command."""
    command_id = draw(st.sampled_from(_RISKY_COMMAND_IDS))
    parameters = draw(_parameters)
    confidence = draw(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
    )
    return StructuredCommand(
        command_id=command_id,
        parameters=parameters,
        confidence=confidence,
    )


# Feature: friday-desktop-agent, Property 14: Risky action withheld until approved
@settings(max_examples=200)
@given(
    command=_risky_commands(),
    now=st.floats(
        min_value=0.0, max_value=1e10, allow_nan=False, allow_infinity=False
    ),
)
def test_risky_action_presents_prompt_and_withholds_execution(
    command: StructuredCommand, now: float
) -> None:
    """A risky command raises a prompt and never executes while unresolved.

    Validates: Requirements 6.1, 6.2
    """
    handlers = _RecordingOSHandlers()
    executor = CommandExecutor(handlers=handlers)
    audited: list[Any] = []
    manager = ConfirmationManager(executor=executor, audit_sink=audited.append)

    registered = next(
        c for c in all_commands() if c.command_id == command.command_id
    )

    result = manager.require_confirmation(command, registered, now=now)

    # (Req 6.1) A Confirmation_Prompt is presented: the gate withholds
    # execution and asks for confirmation rather than returning a terminal
    # success/failure.
    assert result is not None
    assert result.status is CommandStatus.CONFIRMATION_REQUIRED
    assert result.command_id == command.command_id

    # A matching prompt is now pending, carrying the exact command awaiting
    # confirmation.
    pending_ids = manager.pending_prompt_ids
    assert len(pending_ids) == 1
    (prompt_id,) = tuple(pending_ids)
    assert manager.is_pending(prompt_id)
    prompt = manager.get_prompt(prompt_id)
    assert prompt is not None
    assert prompt.command == command

    # (Req 6.2) While the prompt remains unresolved, NO execution side effect
    # occurs: the OS seam recorded zero handler invocations.
    assert handlers.calls == []
