"""Command Executor for the FRIDAY Desktop Agent.

The Command Executor is the final stage of the enforcement gauntlet: it takes
a *validated* ``StructuredCommand`` (one that has already passed the loopback,
token, enabled, authorization, allow-list, parameter-validation, and risk
gates) and dispatches it to the matching operating-system handler. Every
execution returns an ``ExecutionResult`` whose status is exactly one of
``SUCCESS`` or ``FAILURE`` (Req 4.8).

Design reference: design.md, "Desktop_Agent components" -> "Command
Executor".

Least-privilege / testability by construction
---------------------------------------------
All real OS side effects are isolated behind a single injectable seam,
:class:`OSHandlers`. The executor never touches ``os.startfile``,
``subprocess``, ``webbrowser``, Win32/``ctypes``, or keyboard injection
directly; it only calls methods on the injected seam. Tests pass a fake
implementation (mirroring the ``tests/_adapter_fakes.py`` pattern) so the
executor's dispatch/clamp/error logic is verified without performing any real
OS action. Production wiring passes :class:`WindowsOSHandlers`.

Handlers dispatched (Req 4.1-4.7):
    * ``launch_app``        -> launch an installed application (Req 4.1)
    * ``open_path``         -> open a file/folder via the default handler (Req 4.2)
    * ``web_search``        -> open search results in the default browser (Req 4.3)
    * ``media_control``     -> play/pause/next/previous/volume, volume clamped
                               to [0, 100] (Req 4.4)
    * ``dictation``         -> type text into the active input target (Req 4.5)
    * ``window_management`` -> minimize/maximize/restore/focus/close (Req 4.6)
    * ``lock_pc``           -> lock the OS session (Req 4.7)

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8**
"""

from __future__ import annotations

import os
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol, runtime_checkable

from friday.desktop_agent.models import (
    AuditEntry,
    CommandStatus,
    ExecutionResult,
    StructuredCommand,
)
from friday.desktop_agent.registry import lookup
from friday.desktop_agent.validator import clamp_volume

# Seam for recording audit events, matching the AuthorizationManager pattern.
# Pass the Audit_Log's ``append`` method to persist executions, or omit it.
AuditSink = Callable[[AuditEntry], None]

# Default search-engine endpoint used to build web-search URLs (Req 4.3).
SEARCH_URL_TEMPLATE = "https://www.google.com/search?q={query}"

# Maximum length of an error detail recorded on a FAILURE result, mirroring
# the ``_truncate_error_message`` convention in tool_calling/router.py.
_MAX_ERROR_DETAIL = 1000


def _truncate_error(message: str, max_length: int = _MAX_ERROR_DETAIL) -> str:
    """Truncate an error message, preserving useful leading content."""
    if len(message) <= max_length:
        return message
    return message[: max_length - 3] + "..."


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def build_search_url(query: str) -> str:
    """Construct a well-formed search URL containing the URL-encoded query.

    The query is percent-encoded with :func:`urllib.parse.quote_plus` so that
    spaces become ``+`` and every reserved/special character is escaped,
    yielding a URL that is safe to hand to the default browser regardless of
    the query text (Req 4.3).

    Args:
        query: The raw search query text.

    Returns:
        A fully-formed ``https`` search URL whose ``q`` parameter is the
        URL-encoded ``query``.

    **Validates: Requirements 4.3**
    """
    encoded = urllib.parse.quote_plus(query)
    return SEARCH_URL_TEMPLATE.format(query=encoded)


@runtime_checkable
class OSHandlers(Protocol):
    """Injectable seam for every real operating-system side effect.

    The executor depends only on this protocol, never on concrete OS APIs, so
    all side effects are mockable. A production implementation
    (:class:`WindowsOSHandlers`) wraps ``os.startfile``/``subprocess``/
    ``webbrowser``/Win32/keyboard injection; tests substitute a fake that
    records calls instead of performing them.
    """

    def launch_app(self, app_name: str) -> None:
        """Launch the installed application identified by ``app_name`` (Req 4.1)."""
        ...

    def open_path(self, path: str) -> None:
        """Open a file/folder ``path`` with its default handler (Req 4.2)."""
        ...

    def open_browser(self, url: str) -> None:
        """Open ``url`` in the user's default browser (Req 4.3)."""
        ...

    def set_volume(self, level: int) -> None:
        """Set the system volume to ``level`` in the range [0, 100] (Req 4.4)."""
        ...

    def media_action(self, action: str) -> None:
        """Perform a transport media ``action`` (play/pause/next/previous) (Req 4.4)."""
        ...

    def type_text(self, text: str) -> None:
        """Type ``text`` into the active input target (Req 4.5)."""
        ...

    def window_action(self, action: str, target: Optional[str]) -> None:
        """Perform a window ``action`` on ``target`` (or the active window) (Req 4.6)."""
        ...

    def lock_workstation(self) -> None:
        """Lock the operating-system session (Req 4.7)."""
        ...


class CommandExecutor:
    """Dispatches a validated Structured_Command to its OS handler.

    The executor resolves the referenced Registered_Command to obtain its
    ``handler_name``, dispatches to the matching handler on the injected
    :class:`OSHandlers` seam, and returns an :class:`ExecutionResult` whose
    status is exactly ``SUCCESS`` or ``FAILURE`` (Req 4.8). Any exception
    raised by a handler is caught and converted into a ``FAILURE`` result so a
    handler error can never escape to crash the agent (Req 4.8).

    Args:
        handlers: The OS side-effect seam. Inject :class:`WindowsOSHandlers`
            in production or a fake in tests.
        audit_sink: Optional callback invoked with an :class:`AuditEntry` for
            every execution outcome. Pass the Audit_Log's ``append`` method to
            persist executions (Req 7.1), or omit it.
    """

    def __init__(
        self,
        handlers: OSHandlers,
        audit_sink: Optional[AuditSink] = None,
    ) -> None:
        self._handlers = handlers
        self._audit_sink = audit_sink

    def execute(self, command: StructuredCommand) -> ExecutionResult:
        """Execute a validated Structured_Command via its OS handler.

        Resolves the command through the Command_Registry allow-list, clamps
        any media volume to [0, 100] (Req 4.4), dispatches to the matching
        handler, and records the outcome. The returned status is exactly one
        of ``SUCCESS`` or ``FAILURE`` for any command that reaches a handler
        (Req 4.8); an unknown handler yields ``FAILURE``.

        Args:
            command: The validated Structured_Command to execute.

        Returns:
            An :class:`ExecutionResult` with ``SUCCESS`` on a clean handler
            invocation or ``FAILURE`` when the handler raises or the command
            cannot be dispatched.

        **Validates: Requirements 4.1-4.8**
        """
        registered = lookup(command.command_id)
        if registered is None:
            # Defensive: the gauntlet declines unknown commands before they
            # reach the executor, but never trust that invariant blindly.
            return self._fail(
                command.command_id,
                command.parameters,
                f"Unknown command: {command.command_id}",
            )

        dispatch: dict[str, Callable[[StructuredCommand], None]] = {
            "launch_app": self._handle_launch_app,
            "open_path": self._handle_open_path,
            "web_search": self._handle_web_search,
            "media_control": self._handle_media_control,
            "dictation": self._handle_dictation,
            "window_management": self._handle_window_management,
            "lock_pc": self._handle_lock_pc,
        }

        handler = dispatch.get(registered.handler_name)
        if handler is None:
            return self._fail(
                command.command_id,
                command.parameters,
                f"No handler registered for '{registered.handler_name}'",
            )

        try:
            handler(command)
        except Exception as exc:  # noqa: BLE001 - convert every error to FAILURE (Req 4.8)
            return self._fail(
                command.command_id,
                command.parameters,
                f"{type(exc).__name__}: {exc}",
            )

        return self._succeed(command.command_id, command.parameters)

    # -- Individual handlers --------------------------------------------------

    def _handle_launch_app(self, command: StructuredCommand) -> None:
        """Launch an application (Req 4.1)."""
        self._handlers.launch_app(command.parameters["app_name"])

    def _handle_open_path(self, command: StructuredCommand) -> None:
        """Open a file or folder via the default handler (Req 4.2)."""
        self._handlers.open_path(command.parameters["path"])

    def _handle_web_search(self, command: StructuredCommand) -> None:
        """Open web-search results in the default browser (Req 4.3)."""
        url = build_search_url(command.parameters["query"])
        self._handlers.open_browser(url)

    def _handle_media_control(self, command: StructuredCommand) -> None:
        """Perform a media action; clamp volume to [0, 100] (Req 4.4)."""
        action = command.parameters["action"]
        if action == "volume":
            # Any requested level is constrained to the inclusive range
            # [0, 100] before being applied (Req 4.4).
            level = clamp_volume(command.parameters.get("volume", 0))
            self._handlers.set_volume(level)
        else:
            self._handlers.media_action(action)

    def _handle_dictation(self, command: StructuredCommand) -> None:
        """Type transcribed text into the active input target (Req 4.5)."""
        self._handlers.type_text(command.parameters["text"])

    def _handle_window_management(self, command: StructuredCommand) -> None:
        """Perform a window-management action (Req 4.6)."""
        self._handlers.window_action(
            command.parameters["action"],
            command.parameters.get("target"),
        )

    def _handle_lock_pc(self, command: StructuredCommand) -> None:
        """Lock the operating-system session (Req 4.7)."""
        self._handlers.lock_workstation()

    # -- Result helpers -------------------------------------------------------

    def _succeed(
        self, command_id: str, parameters: dict
    ) -> ExecutionResult:
        """Build and audit a SUCCESS result (Req 4.8, 7.1)."""
        self._emit(command_id, parameters, outcome="success")
        return ExecutionResult(status=CommandStatus.SUCCESS, command_id=command_id)

    def _fail(
        self, command_id: str, parameters: dict, detail: str
    ) -> ExecutionResult:
        """Build and audit a FAILURE result (Req 4.8, 7.1)."""
        truncated = _truncate_error(detail)
        self._emit(command_id, parameters, outcome=f"failure: {truncated}")
        return ExecutionResult(
            status=CommandStatus.FAILURE,
            command_id=command_id,
            detail=truncated,
        )

    def _emit(self, command_id: str, parameters: dict, outcome: str) -> None:
        """Record an execution outcome through the audit seam, if configured."""
        if self._audit_sink is None:
            return
        self._audit_sink(
            AuditEntry(
                timestamp=_now_iso(),
                event_type="execute",
                command_id=command_id,
                parameters=dict(parameters),
                outcome=outcome,
            )
        )


class WindowsOSHandlers:
    """Concrete Windows implementation of the :class:`OSHandlers` seam.

    Wraps the real OS integration points named in the design: ``subprocess``
    for launching apps, ``os.startfile`` for opening paths with the default
    handler, ``webbrowser`` for web search, and Win32 (``ctypes``/``user32``)
    plus keyboard injection for volume/media/dictation/window/lock actions.

    The heavier Windows-only dependencies (``ctypes.windll``, keyboard
    injection libraries) are imported lazily inside each method so importing
    this module never fails on non-Windows hosts (e.g., CI running the
    property tests against a fake seam).
    """

    def launch_app(self, app_name: str) -> None:
        """Launch an application by name (Req 4.1)."""
        # ``start`` resolves app names/aliases via the shell without opening a
        # console window; the empty title argument is required by ``start``.
        subprocess.Popen(["cmd", "/c", "start", "", app_name], shell=False)

    def open_path(self, path: str) -> None:
        """Open a file/folder with its default handler (Req 4.2)."""
        # ``os.startfile`` exists only on Windows; resolve dynamically so this
        # module imports cleanly elsewhere.
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise OSError("os.startfile is only available on Windows")
        startfile(path)

    def open_browser(self, url: str) -> None:
        """Open a URL in the default browser (Req 4.3)."""
        webbrowser.open(url)

    def set_volume(self, level: int) -> None:
        """Set the system master volume to ``level`` in [0, 100] (Req 4.4)."""
        # Volume level is already clamped by the executor; apply it via the
        # keyboard media seam. A real deployment would use the Core Audio API
        # (e.g., pycaw); we fall back to relative volume key presses.
        self._send_media_key("volume", level)

    def media_action(self, action: str) -> None:
        """Perform a transport media action via media keys (Req 4.4)."""
        self._send_media_key(action, None)

    def type_text(self, text: str) -> None:
        """Type text into the active input target via keyboard injection (Req 4.5)."""
        keyboard = self._import_keyboard()
        keyboard.write(text)

    def window_action(self, action: str, target: Optional[str]) -> None:
        """Perform a window-management action via Win32 (Req 4.6)."""
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        # ShowWindow command codes for the supported window actions.
        commands = {
            "minimize": 6,   # SW_MINIMIZE
            "maximize": 3,   # SW_MAXIMIZE
            "restore": 9,    # SW_RESTORE
            "focus": 5,      # SW_SHOW
        }
        if action == "close":
            # WM_CLOSE = 0x0010
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
            return
        code = commands.get(action)
        if code is None:
            raise ValueError(f"Unsupported window action: {action}")
        user32.ShowWindow(hwnd, code)
        if action == "focus":
            user32.SetForegroundWindow(hwnd)

    def lock_workstation(self) -> None:
        """Lock the OS session via ``user32.LockWorkStation`` (Req 4.7)."""
        import ctypes

        # LockWorkStation only locks; it can never unlock or bypass login,
        # consistent with the enforced non-goal (Req 12.1).
        if not ctypes.windll.user32.LockWorkStation():  # type: ignore[attr-defined]
            raise OSError("LockWorkStation call failed")

    # -- Windows helpers ------------------------------------------------------

    def _import_keyboard(self):
        """Import the keyboard-injection library lazily."""
        import keyboard  # type: ignore

        return keyboard

    def _send_media_key(self, action: str, level: Optional[int]) -> None:
        """Send a media/volume key event via keyboard injection."""
        keyboard = self._import_keyboard()
        key_map = {
            "play": "play/pause media",
            "pause": "play/pause media",
            "next": "next track",
            "previous": "previous track",
        }
        if action == "volume":
            # Approximate an absolute target by issuing relative key presses.
            # A production build should use the Core Audio API for exactness.
            steps = max(0, min(100, int(level or 0))) // 2
            for _ in range(steps):
                keyboard.send("volume up")
            return
        key = key_map.get(action)
        if key is None:
            raise ValueError(f"Unsupported media action: {action}")
        keyboard.send(key)
