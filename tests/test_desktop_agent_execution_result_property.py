# Feature: friday-desktop-agent, Property 11: Execution result is success or failure
"""Property-based tests for the Command Executor's execution-result invariant.

Property 11: Execution result is success or failure
- For any executed Registered_Command, the returned execution-result status
  SHALL be exactly one of success or failure, reflecting the handler outcome
  (including when the handler raises).

The Command Executor (friday/desktop_agent/executor.py) is the final stage of
the enforcement gauntlet. It dispatches a validated Structured_Command to the
matching OS handler on an injected :class:`OSHandlers` seam and returns an
:class:`ExecutionResult`. This property drives the executor across every
registered command with valid parameters, against a fake OS seam that either
completes cleanly or raises, and asserts:

- the returned status is *exactly* ``SUCCESS`` or ``FAILURE`` (never any other
  ``CommandStatus`` member), and
- the status faithfully reflects the handler outcome: a clean handler yields
  ``SUCCESS`` and a raising handler yields ``FAILURE`` (Req 4.8).

All OS side effects are isolated behind the fake seam (mirroring the
``tests/_adapter_fakes.py`` pattern), so the property tests the executor's
dispatch/error logic, not the OS.

Validates: Requirements 4.8
"""

from __future__ import annotations

from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.executor import CommandExecutor
from friday.desktop_agent.models import (
    CommandStatus,
    StructuredCommand,
)
from friday.desktop_agent.registry import all_commands


class _FakeOSHandlers:
    """Fake OS seam standing in for every real operating-system side effect.

    Implements the full :class:`OSHandlers` protocol. Every handler either
    records the call and returns cleanly, or raises a configured exception,
    according to ``should_raise``. No real OS action is ever performed, so the
    executor's dispatch and error-handling logic is exercised in isolation
    (mirroring the ``tests/_adapter_fakes.py`` fake pattern).
    """

    def __init__(self, should_raise: bool = False) -> None:
        self._should_raise = should_raise
        self.calls: list[tuple] = []

    def _record(self, name: str, *args) -> None:
        self.calls.append((name, args))
        if self._should_raise:
            # Simulate an OS handler failure. The executor must catch this and
            # convert it into a FAILURE execution-result (Req 4.8).
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


# --------------------------------------------------------------------------- #
# Generators producing a valid Structured_Command for each Registered_Command.
#
# Each strategy yields parameters that satisfy the command's schema so the
# command reaches its handler (this property is about the *execution* outcome,
# not parameter validation). One strategy per registered command keeps the
# input space aligned with the real allow-list.
# --------------------------------------------------------------------------- #

_confidences = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)


def _launch_app() -> st.SearchStrategy[StructuredCommand]:
    return st.builds(
        StructuredCommand,
        command_id=st.just("launch_app"),
        parameters=st.fixed_dictionaries(
            {"app_name": st.text(min_size=1, max_size=64)}
        ),
        confidence=_confidences,
    )


def _open_path() -> st.SearchStrategy[StructuredCommand]:
    return st.builds(
        StructuredCommand,
        command_id=st.just("open_path"),
        parameters=st.fixed_dictionaries(
            {"path": st.text(min_size=1, max_size=128)}
        ),
        confidence=_confidences,
    )


def _web_search() -> st.SearchStrategy[StructuredCommand]:
    return st.builds(
        StructuredCommand,
        command_id=st.just("web_search"),
        parameters=st.fixed_dictionaries(
            {"query": st.text(min_size=1, max_size=128)}
        ),
        confidence=_confidences,
    )


def _media_control() -> st.SearchStrategy[StructuredCommand]:
    # Transport actions carry no volume; the "volume" action carries an
    # in-range integer level. Both paths reach a handler.
    transport = st.fixed_dictionaries(
        {"action": st.sampled_from(["play", "pause", "next", "previous"])}
    )
    volume = st.fixed_dictionaries(
        {
            "action": st.just("volume"),
            "volume": st.integers(min_value=0, max_value=100),
        }
    )
    return st.builds(
        StructuredCommand,
        command_id=st.just("media_control"),
        parameters=st.one_of(transport, volume),
        confidence=_confidences,
    )


def _dictation() -> st.SearchStrategy[StructuredCommand]:
    return st.builds(
        StructuredCommand,
        command_id=st.just("dictation"),
        parameters=st.fixed_dictionaries(
            {"text": st.text(min_size=1, max_size=128)}
        ),
        confidence=_confidences,
    )


def _window_management() -> st.SearchStrategy[StructuredCommand]:
    # ``target`` is optional; include both present and absent variants.
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


def _valid_commands() -> st.SearchStrategy[StructuredCommand]:
    """Generate a valid Structured_Command for any Registered_Command."""
    return st.one_of(
        _launch_app(),
        _open_path(),
        _web_search(),
        _media_control(),
        _dictation(),
        _window_management(),
        _lock_pc(),
    )


# Every registered command has a per-command generator above, so the property
# genuinely exercises the whole allow-list. Guard against drift if the registry
# grows without a matching generator.
def test_generators_cover_the_registry() -> None:
    """Sanity check: a generator exists for every Registered_Command."""
    covered = {
        "launch_app",
        "open_path",
        "web_search",
        "media_control",
        "dictation",
        "window_management",
        "lock_pc",
    }
    registered = {command.command_id for command in all_commands()}
    assert registered == covered


# Feature: friday-desktop-agent, Property 11: Execution result is success or failure
@settings(max_examples=200)
@given(command=_valid_commands(), should_raise=st.booleans())
def test_execution_result_is_exactly_success_or_failure(
    command: StructuredCommand, should_raise: bool
) -> None:
    """For any executed command, the status is exactly SUCCESS or FAILURE.

    The executor dispatches to a fake OS seam that either completes cleanly or
    raises. Regardless of the command and the handler outcome, the returned
    status must be exactly one of ``SUCCESS`` or ``FAILURE`` -- never any other
    ``CommandStatus`` member -- and must reflect the handler outcome (Req 4.8).

    Validates: Requirements 4.8
    """
    handlers = _FakeOSHandlers(should_raise=should_raise)
    executor = CommandExecutor(handlers)

    result = executor.execute(command)

    # The status is exactly one of the two execution outcomes.
    assert result.status in (CommandStatus.SUCCESS, CommandStatus.FAILURE)

    # The status faithfully reflects the handler outcome.
    if should_raise:
        assert result.status == CommandStatus.FAILURE
    else:
        assert result.status == CommandStatus.SUCCESS

    # A reachable handler was actually invoked (the command was executed).
    assert handlers.calls, "expected the executor to dispatch to a handler"

    # The result identifies the executed command.
    assert result.command_id == command.command_id


# Feature: friday-desktop-agent, Property 11: Execution result is success or failure
@settings(max_examples=200)
@given(command=_valid_commands())
def test_raising_handler_never_escapes_as_exception(
    command: StructuredCommand,
) -> None:
    """A handler that raises yields a FAILURE result, never a propagated error.

    Every handler exception is caught and converted into a ``FAILURE``
    execution-result so a handler error can never crash the agent (Req 4.8).

    Validates: Requirements 4.8
    """
    handlers = _FakeOSHandlers(should_raise=True)
    executor = CommandExecutor(handlers)

    # Must not raise; the executor converts the handler error to a result.
    result = executor.execute(command)

    assert result.status == CommandStatus.FAILURE
    # A FAILURE result carries a non-empty detail describing the failure.
    assert result.detail
