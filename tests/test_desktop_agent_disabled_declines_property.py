# Feature: friday-desktop-agent, Property 20: Disabled agent declines all commands
"""Property-based tests for the Desktop_Agent disabled-state behavior.

Property 20: Disabled agent declines all commands
For any command execution request while the Desktop_Agent is disabled by the
Kill_Switch, the Desktop_Agent SHALL decline execution, return a disabled
status, and perform no execution side effect.

Validates: Requirements 8.2, 8.5
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.models import (
    AgentState,
    CommandStatus,
    ExecutionResult,
    StructuredCommand,
)
from friday.desktop_agent.state import AgentStateMachine

# Epoch-second range kept finite/positive so timestamp arithmetic and ISO
# conversion stay well-behaved. Roughly year 2001..2035.
_times = st.floats(
    min_value=1_000_000_000.0,
    max_value=2_000_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Arbitrary command identifiers, including ones that would otherwise map to a
# real Registered_Command. The disabled gate must decline regardless.
_command_ids = st.text(min_size=0, max_size=32)

# Arbitrary parameter maps forwarded with the request.
_parameters = st.dictionaries(
    keys=st.text(min_size=1, max_size=16),
    values=st.one_of(
        st.text(max_size=32),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
    ),
    max_size=5,
)

# Confidence values in the valid inclusive range [0.0, 1.0].
_confidences = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)


def _structured_commands() -> st.SearchStrategy[StructuredCommand]:
    """Generate arbitrary Structured_Commands for execution requests."""
    return st.builds(
        StructuredCommand,
        command_id=_command_ids,
        parameters=_parameters,
        confidence=_confidences,
    )


class _ExecutorSpy:
    """A spy standing in for the Command Executor.

    Records whether execution was ever attempted. In a disabled agent the
    enforcement gauntlet must never reach the executor, so ``executed`` must
    remain False (Property 20: "perform no execution side effect").
    """

    def __init__(self) -> None:
        self.executed = False
        self.calls: list[StructuredCommand] = []

    def execute(self, command: StructuredCommand) -> ExecutionResult:
        self.executed = True
        self.calls.append(command)
        return ExecutionResult(
            status=CommandStatus.SUCCESS, command_id=command.command_id
        )


def _handle_request(
    machine: AgentStateMachine, executor: _ExecutorSpy, command: StructuredCommand
) -> ExecutionResult:
    """Model the enabled/kill-switch stage of the enforcement gauntlet.

    The gauntlet consults ``require_enabled()`` before any execution. When the
    agent is disabled the gate returns a ``disabled`` ExecutionResult and the
    request is declined without ever invoking the executor (Req 8.2, 8.5).
    """
    gate = machine.require_enabled()
    if gate is not None:
        return gate
    return executor.execute(command)


@settings(max_examples=200)
@given(command=_structured_commands())
def test_kill_switched_agent_declines_every_command(
    command: StructuredCommand,
) -> None:
    """After the Kill_Switch fires, any command is declined with no side effect.

    Activating the Kill_Switch disables the agent synchronously (Req 8.2). Every
    subsequent execution request is declined with a ``disabled`` status and the
    executor is never invoked (Req 8.5).
    """
    machine = AgentStateMachine(initial_state=AgentState.ENABLED)
    machine.activate_kill_switch(now=1_500_000_000.0)
    assert machine.is_disabled is True

    executor = _ExecutorSpy()
    result = _handle_request(machine, executor, command)

    assert result.status == CommandStatus.DISABLED
    assert executor.executed is False
    assert executor.calls == []


@settings(max_examples=200)
@given(command=_structured_commands())
def test_agent_started_disabled_declines_every_command(
    command: StructuredCommand,
) -> None:
    """An agent already in the disabled state declines every command.

    Regardless of how the disabled state was reached, ``require_enabled()``
    returns a ``disabled`` status and no execution side effect occurs.
    """
    machine = AgentStateMachine(initial_state=AgentState.DISABLED)

    executor = _ExecutorSpy()
    result = _handle_request(machine, executor, command)

    assert result.status == CommandStatus.DISABLED
    assert result.command_id is None  # gate result carries no command id
    assert executor.executed is False


@settings(max_examples=200)
@given(commands=st.lists(_structured_commands(), min_size=1, max_size=8), now=_times)
def test_disabled_declines_a_sequence_of_commands(
    commands: list[StructuredCommand], now: float
) -> None:
    """A disabled agent declines an entire sequence of requests with no effect.

    While kill-switched the agent must decline *every* request, not just the
    first, and must never perform an execution side effect (Req 8.5).
    """
    machine = AgentStateMachine(initial_state=AgentState.ENABLED)
    machine.activate_kill_switch(now=now)

    executor = _ExecutorSpy()
    for command in commands:
        result = _handle_request(machine, executor, command)
        assert result.status == CommandStatus.DISABLED

    assert executor.executed is False
    assert executor.calls == []
