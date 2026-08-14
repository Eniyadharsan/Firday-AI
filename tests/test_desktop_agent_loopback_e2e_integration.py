"""End-to-end loopback integration test for the Desktop_Agent (task 16.2).

Unlike the in-process wiring tests in
``tests/test_desktop_agent_lifecycle_wiring.py`` (task 16.1), which dispatch
directly to :meth:`LoopbackCommandServer.handle_command` without opening a
socket, this test exercises a *real* socket-level loopback round trip:

    build_desktop_agent (mocked OSHandlers)
        -> server.start()            # binds a real socket on 127.0.0.1
        -> issue session token
        -> grant User_Authorization
        -> DesktopAgentClient.send_command  # real HTTP over the loopback
        -> POST /command over 127.0.0.1
        -> full enforcement gauntlet
        -> mocked OS handler
        -> execution-result relayed back == SUCCESS

The OS side-effect seam is mocked so no real operating-system action occurs,
and the server socket is always cleaned up with ``stop()``.

Validates: Requirements 1.2, 4.8, 11.1
"""

from __future__ import annotations

import ipaddress
import time
from typing import Optional

import pytest

from friday.desktop_agent.client_bridge import DesktopAgentClient
from friday.desktop_agent.executor import OSHandlers
from friday.desktop_agent.models import CommandStatus, StructuredCommand
from friday.desktop_agent.runtime import build_desktop_agent


class _MockOSHandlers(OSHandlers):
    """OS-handler seam that records calls instead of touching the OS."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

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


def _start_authorized_agent():
    """Build a mocked agent, grant authorization, issue a token, and start it.

    Returns the recording handlers, the runtime, the started ``(host, port)``,
    and a valid session token. The caller is responsible for ``stop()``.
    """
    now = time.time()
    handlers = _MockOSHandlers()
    runtime = build_desktop_agent(handlers)
    runtime.authorization.grant(["desktop"], now=now)
    token = runtime.authenticator.issue_token(now=now).value
    host, port = runtime.server.start()
    return handlers, runtime, (host, port), token


def test_valid_command_round_trips_over_real_loopback_socket() -> None:
    """A valid command survives a real HTTP loopback round trip and succeeds.

    Starts the LoopbackCommandServer on an actual 127.0.0.1 socket, then sends
    a valid, authorized command through the default urllib HTTP transport of
    the DesktopAgentClient. The full gauntlet runs and the mocked OS handler is
    reached, returning SUCCESS (Req 4.8). The server is asserted to be bound to
    the loopback interface (Req 1.2, 11.1).
    """
    handlers, runtime, (host, port), token = _start_authorized_agent()
    try:
        # The server bound a real socket on the loopback interface only.
        assert host == "127.0.0.1"
        assert ipaddress.ip_address(host).is_loopback is True
        assert isinstance(port, int) and port > 0

        client = DesktopAgentClient(host=host, port=port, session_token=token)
        result = client.send_command(
            StructuredCommand(
                command_id="launch_app",
                parameters={"app_name": "Chrome"},
                confidence=0.98,
            )
        )

        # The execution-result relayed back over the loopback is SUCCESS.
        assert result.status == CommandStatus.SUCCESS
        assert result.command_id == "launch_app"
        # The command reached the mocked OS handler (no real OS action).
        assert ("launch_app", ("Chrome",)) in handlers.calls
        # The outcome was recorded in the shared audit log.
        events = [e.event_type for e in runtime.audit.read_reverse_chronological()]
        assert "execute" in events
    finally:
        runtime.server.stop()


def test_web_search_round_trips_and_opens_mocked_browser() -> None:
    """A second representative command also round-trips to a mocked handler.

    Confirms the socket-level path works for more than one command shape: a
    web_search command travels over the real loopback transport, through the
    gauntlet, to the mocked browser handler with a built URL (Req 4.8).
    """
    handlers, runtime, (host, port), token = _start_authorized_agent()
    try:
        assert host == "127.0.0.1"

        client = DesktopAgentClient(host=host, port=port, session_token=token)
        result = client.send_command(
            StructuredCommand(
                command_id="web_search",
                parameters={"query": "hello world"},
                confidence=0.91,
            )
        )

        assert result.status == CommandStatus.SUCCESS
        assert result.command_id == "web_search"
        opened = [c for c in handlers.calls if c[0] == "open_browser"]
        assert len(opened) == 1
        assert "hello" in opened[0][1][0]
    finally:
        runtime.server.stop()
