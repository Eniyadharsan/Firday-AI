"""Desktop Agent client bridge (backend/UI -> Desktop_Agent).

This module implements the thin client bridge described in design.md,
"FRIDAY_Backend additions" -> "Desktop Agent client bridge". It forwards a
:class:`StructuredCommand` produced by the Intent_Parser to the Desktop_Agent
over the Local_Channel (the loopback ``POST /command`` endpoint), attaching the
current per-session token in the ``X-Session-Token`` header, and relays the
resulting status back to the FRIDAY_UI.

Responsibilities (per task 14.1):
    * Forward a ``StructuredCommand`` to the Desktop_Agent over the
      Local_Channel with the current session token (Req 4.8).
    * Relay the ``execution-result`` (success/failure, Req 4.8),
      ``authorization-required`` (Req 2.2), ``disabled`` (Req 8.5),
      ``unsupported-command`` (Req 3.3), ``validation-error`` (Req 3.6), and
      ``ambiguous-command`` (Req 5.4) statuses back to the UI.

The bridge is transport-agnostic: network I/O is isolated behind the injectable
:class:`HttpTransport` seam so tests can exercise the serialization, response
parsing, status mapping, and error handling without opening real sockets. The
default :class:`UrllibHttpTransport` uses the Python standard library.

Non-execution guarantee
-----------------------
The bridge performs no OS actions itself. It only serializes a command, sends
it to the agent, and maps the agent's JSON response back into an
:class:`ExecutionResult`. All enforcement (loopback origin, token, authorization,
allow-list, validation, risk gate) happens inside the Desktop_Agent's gauntlet.

**Validates: Requirements 4.8, 2.2, 8.5, 3.3, 3.6, 5.4**
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from friday.desktop_agent.models import (
    CommandStatus,
    ExecutionResult,
    IntentResult,
    StructuredCommand,
)

# The command endpoint exposed by the loopback server (see server.py).
COMMAND_PATH = "/command"

# The header the loopback server reads the per-session token from (see
# server.py ``do_POST`` handling of ``/command``).
SESSION_TOKEN_HEADER = "X-Session-Token"

# Default request timeout in seconds for a single command round trip.
DEFAULT_TIMEOUT_SECONDS = 5.0

# Statuses this bridge is responsible for relaying back to the FRIDAY_UI.
# ``ambiguous-command`` originates in the Intent_Parser (before forwarding);
# the rest are returned by the Desktop_Agent's enforcement gauntlet / executor.
RELAYABLE_STATUSES: frozenset[CommandStatus] = frozenset(
    {
        CommandStatus.SUCCESS,
        CommandStatus.FAILURE,
        CommandStatus.AUTHORIZATION_REQUIRED,
        CommandStatus.DISABLED,
        CommandStatus.UNSUPPORTED,
        CommandStatus.VALIDATION_ERROR,
        CommandStatus.AMBIGUOUS,
    }
)

# Fast lookup from a status wire value back to the enum member.
_STATUS_BY_VALUE: dict[str, CommandStatus] = {
    status.value: status for status in CommandStatus
}


class AgentUnreachableError(Exception):
    """Raised by an :class:`HttpTransport` when the Desktop_Agent is unreachable.

    Signals a transport-level failure (connection refused, DNS/socket error,
    timeout) as opposed to a well-formed HTTP response carrying a decline
    status. The bridge catches this and returns a ``FAILURE`` execution result
    so a down or not-yet-started agent never crashes the backend.
    """


@dataclass(frozen=True)
class HttpResponse:
    """A minimal HTTP response returned by an :class:`HttpTransport`.

    Attributes:
        status_code: The HTTP status code of the response.
        body: The raw response body decoded as UTF-8 text.
    """

    status_code: int
    body: str


@runtime_checkable
class HttpTransport(Protocol):
    """Injectable seam for sending an HTTP POST to the Desktop_Agent.

    Isolating network I/O behind this protocol lets tests substitute a fake
    that records the request and returns a canned response, so the bridge's
    serialization, header handling, response parsing, and error handling can be
    verified without real sockets.

    Implementations MUST raise :class:`AgentUnreachableError` when the agent
    cannot be contacted (connection refused, socket error, timeout). A
    well-formed HTTP response - including one with a non-2xx status that still
    carries a JSON decline body - MUST be returned as an :class:`HttpResponse`.
    """

    def post(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        """Send ``body`` to ``url`` via HTTP POST and return the response.

        Args:
            url: The absolute URL of the command endpoint.
            body: The request body (UTF-8 encoded JSON).
            headers: The request headers, including the session token header.
            timeout: The per-request timeout in seconds.

        Returns:
            The :class:`HttpResponse` produced by the agent.

        Raises:
            AgentUnreachableError: If the agent cannot be contacted.
        """
        ...


class UrllibHttpTransport:
    """Default :class:`HttpTransport` backed by the standard-library urllib.

    Treats a well-formed HTTP error response (e.g. the ``403`` the loopback
    server returns for a non-loopback origin, still carrying a JSON status
    body) as a normal response so the bridge can relay the decline status.
    Transport-level failures (no connection, socket error, timeout) are
    translated into :class:`AgentUnreachableError`.
    """

    def post(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        """Perform the POST using :func:`urllib.request.urlopen`.

        **Validates: Requirements 4.8**
        """
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return HttpResponse(
                    status_code=getattr(response, "status", 200) or 200,
                    body=raw.decode("utf-8", errors="replace"),
                )
        except HTTPError as exc:
            # A well-formed HTTP response with a non-2xx status. The server
            # still returns a JSON decline body, so surface it as a response.
            raw = exc.read() if hasattr(exc, "read") else b""
            return HttpResponse(
                status_code=exc.code,
                body=raw.decode("utf-8", errors="replace") if raw else "",
            )
        except (URLError, OSError, TimeoutError) as exc:
            # No usable HTTP response: the agent is down or unreachable.
            raise AgentUnreachableError(str(exc)) from exc


class DesktopAgentClient:
    """Client bridge that forwards commands to the Desktop_Agent.

    Holds the loopback address of the agent plus the current per-session token,
    serializes a :class:`StructuredCommand` to the ``POST /command`` endpoint,
    and maps the agent's JSON response back into an :class:`ExecutionResult` for
    the FRIDAY_UI.

    Args:
        host: The loopback host the Desktop_Agent is bound to (e.g.
            ``127.0.0.1``).
        port: The TCP port the Desktop_Agent's Local_Channel is listening on.
        session_token: The current per-session authentication token, sent in
            the ``X-Session-Token`` header on every request.
        transport: The :class:`HttpTransport` seam. Defaults to
            :class:`UrllibHttpTransport`.
        timeout: The per-request timeout in seconds.

    **Validates: Requirements 4.8, 2.2, 8.5, 3.3, 3.6, 5.4**
    """

    def __init__(
        self,
        host: str,
        port: int,
        session_token: str,
        transport: Optional[HttpTransport] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._session_token = session_token
        self._transport: HttpTransport = (
            transport if transport is not None else UrllibHttpTransport()
        )
        self._timeout = float(timeout)

    @property
    def command_url(self) -> str:
        """The absolute URL of the agent's command endpoint."""
        return f"http://{self._host}:{self._port}{COMMAND_PATH}"

    def send_command(self, command: StructuredCommand) -> ExecutionResult:
        """Forward ``command`` to the Desktop_Agent and relay the result.

        Serializes the :class:`StructuredCommand` to the JSON body the loopback
        server's ``/command`` endpoint expects (``command_id``, ``parameters``,
        ``confidence``) and attaches the current session token in the
        ``X-Session-Token`` header (Req 4.8). The agent's JSON response status
        is mapped back into a :class:`CommandStatus` and returned to the UI,
        relaying ``authorization-required`` (Req 2.2), ``disabled`` (Req 8.5),
        ``unsupported-command`` (Req 3.3), ``validation-error`` (Req 3.6), and
        the ``success``/``failure`` execution result (Req 4.8).

        If the agent is unreachable or returns a malformed/unknown response, a
        ``FAILURE`` result is returned so the backend degrades gracefully
        instead of raising.

        Args:
            command: The Structured_Command to forward to the agent.

        Returns:
            An :class:`ExecutionResult` carrying the relayed status.

        **Validates: Requirements 4.8, 2.2, 8.5, 3.3, 3.6**
        """
        payload = {
            "command_id": command.command_id,
            "parameters": dict(command.parameters or {}),
            "confidence": float(command.confidence),
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            SESSION_TOKEN_HEADER: self._session_token,
        }

        try:
            response = self._transport.post(
                self.command_url, body, headers, self._timeout
            )
        except AgentUnreachableError as exc:
            # Fail closed: a down/unreachable agent yields a failure result
            # rather than propagating an exception into the backend (Req 4.8).
            return ExecutionResult(
                status=CommandStatus.FAILURE,
                command_id=command.command_id,
                detail=f"Desktop_Agent unreachable: {exc}",
            )

        return self._parse_response(response, command.command_id)

    def relay_intent(self, intent: IntentResult) -> ExecutionResult:
        """Bridge an :class:`IntentResult` to the UI, forwarding when recognized.

        Encapsulates the request lifecycle from the Intent_Parser's perspective:

            * ``SUCCESS`` with a command  -> forward to the agent via
              :meth:`send_command` and relay the execution result (Req 4.8).
            * ``AMBIGUOUS``               -> relay the ambiguous-command status
              (and its candidate list) straight back to the UI without
              contacting the agent (Req 5.4).
            * anything else (e.g. ``UNRECOGNIZED``) -> relay the parser status
              straight back to the UI without contacting the agent (Req 5.2).

        Args:
            intent: The :class:`IntentResult` produced by the Intent_Parser.

        Returns:
            An :class:`ExecutionResult` to surface to the FRIDAY_UI.

        **Validates: Requirements 5.4, 4.8**
        """
        if intent.status is CommandStatus.SUCCESS and intent.command is not None:
            return self.send_command(intent.command)

        if intent.status is CommandStatus.AMBIGUOUS:
            candidate_ids = [c.command_id for c in intent.candidates]
            return ExecutionResult(
                status=CommandStatus.AMBIGUOUS,
                command_id=None,
                detail=(
                    "Multiple matching commands; ask the user to choose: "
                    + ", ".join(candidate_ids)
                ),
            )

        # Relay any other parser status (e.g. unrecognized-command) as-is.
        return ExecutionResult(
            status=intent.status,
            command_id=intent.command.command_id if intent.command else None,
            detail="",
        )

    def _parse_response(
        self, response: HttpResponse, command_id: str
    ) -> ExecutionResult:
        """Map the agent's JSON response into an :class:`ExecutionResult`.

        The loopback server returns ``{"status", "command_id", "detail"}`` on
        the command endpoint. The status string is mapped back to a
        :class:`CommandStatus`; an unknown status or a malformed body yields a
        ``FAILURE`` result so the bridge never propagates a decoding error.

        Args:
            response: The :class:`HttpResponse` returned by the transport.
            command_id: The originating command identifier, used as a fallback.

        Returns:
            The mapped :class:`ExecutionResult`.
        """
        try:
            data = json.loads(response.body) if response.body else {}
        except ValueError:
            return ExecutionResult(
                status=CommandStatus.FAILURE,
                command_id=command_id,
                detail="Malformed response from Desktop_Agent.",
            )

        if not isinstance(data, dict):
            return ExecutionResult(
                status=CommandStatus.FAILURE,
                command_id=command_id,
                detail="Unexpected response payload from Desktop_Agent.",
            )

        status = _STATUS_BY_VALUE.get(str(data.get("status", "")))
        if status is None:
            return ExecutionResult(
                status=CommandStatus.FAILURE,
                command_id=command_id,
                detail=f"Unknown status from Desktop_Agent: {data.get('status')!r}",
            )

        return ExecutionResult(
            status=status,
            command_id=data.get("command_id") or command_id,
            detail=str(data.get("detail", "") or ""),
        )
