"""Wiring tests for the full Desktop_Agent request lifecycle (task 16.1).

These example tests verify that the pieces built in tasks 8-14 are wired
together into a single working lifecycle:

    transcribed text
        -> Intent_Parser
        -> client bridge
        -> Desktop_Agent enforcement gauntlet
        -> mocked OS handler
        -> execution-result relayed back.

The agent is assembled by :func:`build_desktop_agent` with a *mocked*
``OSHandlers`` seam so no real OS action occurs, and the backend pipeline is
wired to that agent in-process via :func:`build_in_process_pipeline` (the same
client-bridge/gauntlet code paths as the HTTP transport, without opening a
socket). The socket-level end-to-end test is task 16.2.

Validates: Requirements 4.8, 5.1, 2.1
"""

from __future__ import annotations

import time
from typing import Optional

from friday.desktop_agent.executor import OSHandlers
from friday.desktop_agent.intent_parser import CandidateEngine, CandidateMapping
from friday.desktop_agent.models import AgentState, CommandStatus
from friday.desktop_agent.pipeline import build_in_process_pipeline
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


class _StubEngine(CandidateEngine):
    """Deterministic candidate engine standing in for the LLM tool selection."""

    def __init__(self, candidates: list[CandidateMapping]) -> None:
        self._candidates = candidates

    def propose(self, text: str) -> list[CandidateMapping]:
        return list(self._candidates)


def _build(candidates, *, authorized=True, initial_state=AgentState.ENABLED):
    """Assemble a mocked agent + in-process pipeline for the given candidates.

    The token is issued at the current wall-clock time because the in-process
    transport forwards to ``handle_command`` without an injected clock, so the
    gauntlet validates the token against real time.
    """
    now = time.time()
    handlers = _MockOSHandlers()
    runtime = build_desktop_agent(handlers, initial_state=initial_state)
    if authorized:
        runtime.authorization.grant(["desktop"], now=now)
    token = runtime.authenticator.issue_token(now=now).value
    pipeline = build_in_process_pipeline(
        _StubEngine(candidates), runtime.server, token
    )
    return handlers, runtime, pipeline


def test_recognized_command_flows_through_to_mocked_os_handler() -> None:
    """A recognized command reaches the mocked OS handler and returns success.

    Exercises the whole chain: parse -> bridge -> gauntlet -> executor ->
    mocked handler -> execution-result (Req 5.1, 4.8, 2.1).
    """
    handlers, runtime, pipeline = _build(
        [CandidateMapping("launch_app", {"app_name": "Chrome"}, 0.95)]
    )

    result = pipeline.handle_text("open chrome")

    assert result.status == CommandStatus.SUCCESS
    assert result.command_id == "launch_app"
    assert ("launch_app", ("Chrome",)) in handlers.calls
    # The execution was recorded in the shared audit log.
    events = [e.event_type for e in runtime.audit.read_reverse_chronological()]
    assert "execute" in events


def test_web_search_builds_url_and_opens_browser() -> None:
    """web_search flows through to the mocked browser handler with a URL."""
    handlers, _runtime, pipeline = _build(
        [CandidateMapping("web_search", {"query": "hello world"}, 0.9)]
    )

    result = pipeline.handle_text("search for hello world")

    assert result.status == CommandStatus.SUCCESS
    opened = [c for c in handlers.calls if c[0] == "open_browser"]
    assert len(opened) == 1
    assert "hello" in opened[0][1][0]


def test_unrecognized_text_is_not_a_desktop_command() -> None:
    """Text mapping to nothing relays UNRECOGNIZED and never touches the OS.

    This is what lets /chat fall through to its normal flow (Req 5.2).
    """
    handlers, _runtime, pipeline = _build([])

    result = pipeline.handle_text("what's the weather like today")

    assert result.status == CommandStatus.UNRECOGNIZED
    assert pipeline.is_desktop_command(result) is False
    assert handlers.calls == []


def test_missing_authorization_is_relayed_and_withholds_execution() -> None:
    """Without User_Authorization the gauntlet declines before any OS call.

    The authorization-required status is relayed back to the UI (Req 2.1, 2.2).
    """
    handlers, _runtime, pipeline = _build(
        [CandidateMapping("launch_app", {"app_name": "Chrome"}, 0.95)],
        authorized=False,
    )

    result = pipeline.handle_text("open chrome")

    assert result.status == CommandStatus.AUTHORIZATION_REQUIRED
    assert handlers.calls == []


def test_disabled_agent_relays_disabled_status() -> None:
    """A kill-switched agent declines with a disabled status (Req 8.5)."""
    handlers, _runtime, pipeline = _build(
        [CandidateMapping("launch_app", {"app_name": "Chrome"}, 0.95)],
        initial_state=AgentState.DISABLED,
    )

    result = pipeline.handle_text("open chrome")

    assert result.status == CommandStatus.DISABLED
    assert handlers.calls == []


def test_risky_command_is_withheld_pending_confirmation() -> None:
    """A risky command (lock_pc) is withheld and never executes unconfirmed.

    The risk gate returns confirmation-required; the mocked lock handler is
    never invoked while the prompt is unresolved (Req 6.1, 6.2).
    """
    handlers, _runtime, pipeline = _build(
        [CandidateMapping("lock_pc", {}, 0.99)]
    )

    result = pipeline.handle_text("lock my pc")

    assert result.status == CommandStatus.CONFIRMATION_REQUIRED
    assert ("lock_workstation", ()) not in handlers.calls


def test_ambiguous_parse_is_relayed_without_contacting_agent() -> None:
    """Two near-tied candidates yield an ambiguous status and no OS call.

    The ambiguity is surfaced to the UI without forwarding to the agent
    (Req 5.3, 5.4).
    """
    handlers, _runtime, pipeline = _build(
        [
            CandidateMapping("launch_app", {"app_name": "Chrome"}, 0.90),
            CandidateMapping("web_search", {"query": "chrome"}, 0.88),
        ]
    )

    result = pipeline.handle_text("chrome")

    assert result.status == CommandStatus.AMBIGUOUS
    assert handlers.calls == []
