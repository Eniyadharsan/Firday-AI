"""Backend request-lifecycle pipeline for the FRIDAY Desktop Agent.

This module is the backend half of task 16.1. It ties the FRIDAY_Backend
components of the request lifecycle together:

    transcribed text
        -> Intent_Parser  (map free text to a StructuredCommand)
        -> client bridge  (forward the command over the Local_Channel)
        -> Desktop_Agent  (enforcement gauntlet -> OS handler -> result)
        -> execution-result relayed back to the FRIDAY_UI.

Two seams make the lifecycle testable and deployable:

* :class:`InProcessAgentTransport` is an :class:`HttpTransport` that dispatches
  a forwarded command *directly* to a :class:`LoopbackCommandServer`'s
  near-pure ``handle_command`` gauntlet, without opening a socket. This lets the
  backend talk to a co-located agent (and lets tests exercise the whole chain
  through a mocked OS handler) while reusing the exact same bridge/gauntlet code
  paths as the real HTTP transport.
* :class:`DesktopCommandPipeline` composes an :class:`IntentParser` with a
  :class:`DesktopAgentClient` and exposes a single ``handle_text`` entry point
  that the ``/chat`` route calls.

Non-execution guarantee
-----------------------
The pipeline performs no OS actions. Parsing produces a Structured_Command; the
bridge forwards it; all enforcement and every side effect happen inside the
Desktop_Agent behind the allow-listed executor and its OS-handler seam.

**Validates: Requirements 4.8, 5.1, 2.1**
"""

from __future__ import annotations

import json
from typing import Optional

from friday.desktop_agent.client_bridge import (
    COMMAND_PATH,
    SESSION_TOKEN_HEADER,
    DesktopAgentClient,
    HttpResponse,
)
from friday.desktop_agent.intent_parser import CandidateEngine, IntentParser
from friday.desktop_agent.models import (
    CommandStatus,
    ExecutionResult,
    IntentResult,
    StructuredCommand,
)
from friday.desktop_agent.server import LOOPBACK_HOST, LoopbackCommandServer


class InProcessAgentTransport:
    """:class:`HttpTransport` that dispatches to a co-located agent gauntlet.

    Instead of serializing over a socket, this transport decodes the request
    body the client bridge produced and forwards it straight to the target
    server's :meth:`LoopbackCommandServer.handle_command`, then re-encodes the
    resulting :class:`ExecutionResult` into the same JSON envelope the loopback
    HTTP handler returns. The bridge cannot tell the difference, so the exact
    same forwarding, status-mapping, and error-handling code paths run.

    Only the ``/command`` endpoint is supported; any other path yields a 404
    envelope, mirroring the HTTP handler.

    Args:
        server: The :class:`LoopbackCommandServer` to dispatch commands to.
        remote_addr: The origin address presented to the gauntlet's loopback
            gate. Defaults to ``127.0.0.1`` because an in-process, co-located
            backend is, by definition, on the loopback interface.
    """

    def __init__(
        self, server: LoopbackCommandServer, remote_addr: str = LOOPBACK_HOST
    ) -> None:
        self._server = server
        self._remote_addr = remote_addr

    def post(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        """Dispatch the forwarded command to the agent gauntlet in-process.

        Args:
            url: The command URL produced by the bridge; only its path matters.
            body: The UTF-8 JSON body the bridge serialized.
            headers: The request headers, including the session-token header.
            timeout: Ignored for the in-process path (no network wait).

        Returns:
            An :class:`HttpResponse` carrying the gauntlet's result envelope.

        **Validates: Requirements 4.8, 2.1**
        """
        if not url.rstrip("/").endswith(COMMAND_PATH):
            return HttpResponse(
                status_code=404,
                body=json.dumps({"detail": "Unknown endpoint."}),
            )

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        token = headers.get(SESSION_TOKEN_HEADER) or payload.get("token")
        command = StructuredCommand(
            command_id=str(payload.get("command_id", "")),
            parameters=dict(payload.get("parameters", {}) or {}),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
        )

        result = self._server.handle_command(self._remote_addr, token, command)
        return HttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "status": result.status.value,
                    "command_id": result.command_id,
                    "detail": result.detail,
                }
            ),
        )


class DesktopCommandPipeline:
    """Wires Intent_Parser -> client bridge into a single lifecycle entry point.

    The pipeline is the object the ``/chat`` route uses to attempt desktop
    command handling. It parses transcribed text into an :class:`IntentResult`
    and relays it through the :class:`DesktopAgentClient`: recognized commands
    are forwarded to the agent and their execution-result is returned;
    ambiguous and unrecognized parses are relayed straight back to the UI
    without contacting the agent.

    Args:
        parser: The :class:`IntentParser` mapping free text to a
            Structured_Command.
        client: The :class:`DesktopAgentClient` bridge forwarding commands to
            the Desktop_Agent.
    """

    def __init__(self, parser: IntentParser, client: DesktopAgentClient) -> None:
        self._parser = parser
        self._client = client

    def parse(self, text: str) -> IntentResult:
        """Parse ``text`` into an :class:`IntentResult` (no forwarding)."""
        return self._parser.parse_intent(text)

    def handle_text(self, text: str) -> ExecutionResult:
        """Run the full lifecycle for ``text`` and return the relayed result.

        Parses the transcribed text, then relays the intent through the client
        bridge: a recognized command is forwarded to the Desktop_Agent's
        gauntlet (and its ``execution-result`` returned), while an ambiguous or
        unrecognized parse is relayed straight back to the UI (Req 5.1, 5.4,
        4.8).

        Args:
            text: The natural-language voice input transcribed by the UI.

        Returns:
            An :class:`ExecutionResult` to surface to the FRIDAY_UI.

        **Validates: Requirements 5.1, 4.8, 2.1**
        """
        intent = self._parser.parse_intent(text)
        return self._client.relay_intent(intent)

    def is_desktop_command(self, result: ExecutionResult) -> bool:
        """Whether ``result`` represents a handled desktop command.

        Used by the ``/chat`` route to decide whether to short-circuit with the
        desktop response or fall through to the normal chat flow. An
        ``UNRECOGNIZED`` result means the text was not a desktop command, so the
        route should continue with its existing behavior (Req 5.2).

        Args:
            result: The :class:`ExecutionResult` returned by :meth:`handle_text`.

        Returns:
            ``True`` when the desktop pipeline handled the request, ``False``
            when the text did not map to any Registered_Command.
        """
        return result.status is not CommandStatus.UNRECOGNIZED


def build_in_process_pipeline(
    engine: CandidateEngine,
    server: LoopbackCommandServer,
    session_token: str,
    *,
    remote_addr: str = LOOPBACK_HOST,
) -> DesktopCommandPipeline:
    """Build a pipeline wired to a co-located agent via the in-process transport.

    Convenience assembly connecting an :class:`IntentParser` (over the given
    candidate engine) to a :class:`DesktopAgentClient` whose transport
    dispatches directly to ``server``'s enforcement gauntlet. This is the
    end-to-end wiring for a backend co-located with the Desktop_Agent and the
    seam tests use to exercise the lifecycle through a mocked OS handler.

    Args:
        engine: The :class:`CandidateEngine` supplying candidate mappings.
        server: The :class:`LoopbackCommandServer` to dispatch commands to.
        session_token: The per-session token attached to forwarded commands.
        remote_addr: The origin presented to the loopback gate; defaults to
            ``127.0.0.1``.

    Returns:
        A ready-to-use :class:`DesktopCommandPipeline`.

    **Validates: Requirements 5.1, 4.8, 2.1**
    """
    parser = IntentParser(engine)
    transport = InProcessAgentTransport(server, remote_addr=remote_addr)
    # host/port are only used to build the command URL; the in-process
    # transport keys solely off the path, so any loopback host/port is fine.
    client = DesktopAgentClient(
        host=remote_addr,
        port=0,
        session_token=session_token,
        transport=transport,
    )
    return DesktopCommandPipeline(parser, client)
