"""Unit tests for Command Executor dispatch to each OS handler.

These example tests verify that the Command Executor
(``friday/desktop_agent/executor.py``) dispatches a validated
Structured_Command to the correct method on its injectable OS seam
(:class:`friday.desktop_agent.executor.OSHandlers`), passing through the
command's parameters. All real OS side effects are replaced by a recording
fake (mirroring the ``tests/_adapter_fakes.py`` pattern), so the tests confirm
dispatch/routing logic without performing any real OS action.

Handlers covered here map directly to acceptance criteria:
    * launch_app        -> Req 4.1 (launch an application)
    * open_path         -> Req 4.2 (open a file/folder via default handler)
    * dictation         -> Req 4.5 (type text into the active input target)
    * window_management -> Req 4.6 (minimize/maximize/restore/focus/close)
    * lock_pc           -> Req 4.7 (lock the OS session)

Each successful dispatch also returns a SUCCESS ExecutionResult (Req 4.8).

Validates: Requirements 4.1, 4.2, 4.5, 4.6, 4.7
"""

from __future__ import annotations

from typing import Any, Optional

from friday.desktop_agent.executor import CommandExecutor
from friday.desktop_agent.models import CommandStatus, StructuredCommand


class FakeOSHandlers:
    """Recording stand-in for the ``OSHandlers`` seam.

    Every method records its arguments instead of performing a real OS side
    effect, so tests can assert exactly which handler was invoked and with
    what parameters. This mirrors the recording-fake approach used elsewhere
    in ``tests/_adapter_fakes.py``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def launch_app(self, app_name: str) -> None:
        self.calls.append(("launch_app", (app_name,)))

    def open_path(self, path: str) -> None:
        self.calls.append(("open_path", (path,)))

    def open_browser(self, url: str) -> None:
        self.calls.append(("open_browser", (url,)))

    def set_volume(self, level: int) -> None:
        self.calls.append(("set_volume", (level,)))

    def media_action(self, action: str) -> None:
        self.calls.append(("media_action", (action,)))

    def type_text(self, text: str) -> None:
        self.calls.append(("type_text", (text,)))

    def window_action(self, action: str, target: Optional[str]) -> None:
        self.calls.append(("window_action", (action, target)))

    def lock_workstation(self) -> None:
        self.calls.append(("lock_workstation", ()))


def _make_executor() -> tuple[CommandExecutor, FakeOSHandlers]:
    """Build a CommandExecutor wired to a fresh recording fake seam."""
    handlers = FakeOSHandlers()
    return CommandExecutor(handlers=handlers), handlers


def _cmd(command_id: str, parameters: dict[str, Any]) -> StructuredCommand:
    """Construct a validated Structured_Command with full confidence."""
    return StructuredCommand(
        command_id=command_id,
        parameters=parameters,
        confidence=1.0,
    )


def test_dispatch_launch_app_invokes_launch_handler() -> None:
    """launch_app dispatches to the OS launch seam with the app name.

    Validates: Requirements 4.1
    """
    executor, handlers = _make_executor()

    result = executor.execute(_cmd("launch_app", {"app_name": "Chrome"}))

    assert handlers.calls == [("launch_app", ("Chrome",))]
    assert result.status is CommandStatus.SUCCESS
    assert result.command_id == "launch_app"


def test_dispatch_open_path_invokes_open_path_handler() -> None:
    """open_path dispatches to the OS open-path seam with the path.

    Validates: Requirements 4.2
    """
    executor, handlers = _make_executor()

    result = executor.execute(_cmd("open_path", {"path": r"C:\Users\me\Documents"}))

    assert handlers.calls == [("open_path", (r"C:\Users\me\Documents",))]
    assert result.status is CommandStatus.SUCCESS
    assert result.command_id == "open_path"


def test_dispatch_dictation_invokes_type_text_handler() -> None:
    """dictation dispatches to the keyboard type-text seam with the text.

    Validates: Requirements 4.5
    """
    executor, handlers = _make_executor()

    result = executor.execute(_cmd("dictation", {"text": "hello world"}))

    assert handlers.calls == [("type_text", ("hello world",))]
    assert result.status is CommandStatus.SUCCESS
    assert result.command_id == "dictation"


def test_dispatch_window_management_invokes_window_action_handler() -> None:
    """window_management dispatches to the window-action seam with action/target.

    Validates: Requirements 4.6
    """
    executor, handlers = _make_executor()

    result = executor.execute(
        _cmd("window_management", {"action": "minimize", "target": "Notepad"})
    )

    assert handlers.calls == [("window_action", ("minimize", "Notepad"))]
    assert result.status is CommandStatus.SUCCESS
    assert result.command_id == "window_management"


def test_dispatch_window_management_defaults_target_to_none() -> None:
    """window_management passes target=None when omitted (active window).

    Validates: Requirements 4.6
    """
    executor, handlers = _make_executor()

    result = executor.execute(_cmd("window_management", {"action": "close"}))

    assert handlers.calls == [("window_action", ("close", None))]
    assert result.status is CommandStatus.SUCCESS


def test_dispatch_lock_pc_invokes_lock_workstation_handler() -> None:
    """lock_pc dispatches to the OS lock-workstation seam.

    Validates: Requirements 4.7
    """
    executor, handlers = _make_executor()

    result = executor.execute(_cmd("lock_pc", {}))

    assert handlers.calls == [("lock_workstation", ())]
    assert result.status is CommandStatus.SUCCESS
    assert result.command_id == "lock_pc"


def test_each_handler_is_invoked_exactly_once_per_command() -> None:
    """Dispatching a command triggers exactly one OS-seam call, not others.

    Confirms routing is isolated: each command reaches only its own handler.

    Validates: Requirements 4.1, 4.2, 4.5, 4.6, 4.7
    """
    cases = [
        (_cmd("launch_app", {"app_name": "Spotify"}), "launch_app"),
        (_cmd("open_path", {"path": "report.pdf"}), "open_path"),
        (_cmd("dictation", {"text": "note"}), "type_text"),
        (_cmd("window_management", {"action": "maximize"}), "window_action"),
        (_cmd("lock_pc", {}), "lock_workstation"),
    ]

    for command, expected_seam in cases:
        executor, handlers = _make_executor()

        result = executor.execute(command)

        assert len(handlers.calls) == 1, (
            f"{command.command_id} should trigger exactly one OS-seam call"
        )
        assert handlers.calls[0][0] == expected_seam
        assert result.status is CommandStatus.SUCCESS
