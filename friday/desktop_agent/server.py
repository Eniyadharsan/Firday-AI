"""Local_Channel loopback server and ordered enforcement gauntlet.

This module implements the Desktop_Agent's Local_Channel: an HTTP server bound
exclusively to the loopback interface (``127.0.0.1``) that exposes the command,
authorization, kill-switch, screen-awareness, and audit-history endpoints, plus
the ordered *enforcement gauntlet* every inbound command must pass before it can
reach the operating system.

Design references:
- design.md, "Local_Channel (loopback server)".
- design.md, "Trust and Enforcement Layers" (the ordered gauntlet).

The gauntlet applies the design's layers in order; each layer can reject and
records the rejection in the Audit_Log, and only a request that passes every
layer reaches the executor:

    1. Transport origin check  -> connection must originate from ``127.0.0.1``
       (Req 1.3, 11.1, 11.2).
    2. Session token check     -> a valid, unexpired token must be present;
       repeated failures trigger a lockout (Req 11.3, 11.4, 1.7).
    3. Enabled / kill-switch   -> the agent must not be disabled (Req 8.5).
    4. Authorization check     -> User_Authorization must be present (Req 2.2).
    5. Registry allow-list     -> the referenced command must exist; arbitrary
       shell strings and unlock/bypass requests are unsupported (Req 3.2-3.4,
       12.2).
    6. Parameter validation    -> parameters must satisfy the schema (Req 3.6).
    7. Risk gate               -> a Risky_Action requires an approved
       Confirmation_Prompt (Req 6.1, 6.2) via an injectable confirmation seam.
    8. Execution + audit       -> dispatch to the executor and record the
       outcome (Req 4.x, 7.1).

The core decision logic lives in :meth:`LoopbackCommandServer.handle_command`,
which is written as a near-pure method taking a remote address, a token, and a
:class:`StructuredCommand`. It performs no socket I/O, so it can be unit- and
property-tested directly. The HTTP layer (:meth:`LoopbackCommandServer.start`)
is a thin adapter that binds the loopback socket and forwards decoded requests
to that method.

**Validates: Requirements 1.2, 1.3, 3.2, 3.3, 3.4, 11.1, 11.2, 12.2**
"""

from __future__ import annotations

import ipaddress
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional, Protocol, runtime_checkable

from friday.desktop_agent.audit import AuditLog
from friday.desktop_agent.auth import SessionTokenAuthenticator
from friday.desktop_agent.authorization import AuthorizationManager
from friday.desktop_agent.executor import CommandExecutor
from friday.desktop_agent.models import (
    CommandStatus,
    ExecutionResult,
    RegisteredCommand,
    RiskClass,
    StructuredCommand,
)
from friday.desktop_agent.registry import lookup as registry_lookup
from friday.desktop_agent.state import AgentStateMachine
from friday.desktop_agent.validator import validate as validate_parameters_result

# The one and only interface the command server binds to (Req 1.2, 11.1).
LOOPBACK_HOST = "127.0.0.1"


def is_loopback(remote_addr: Optional[str]) -> bool:
    """Return True only if ``remote_addr`` is a loopback address.

    This is the transport-origin gate of the enforcement gauntlet. Any inbound
    connection whose remote address is not on the loopback interface must be
    declined and recorded (Req 1.3, 11.2). The check accepts both IPv4 loopback
    (the ``127.0.0.0/8`` block) and the IPv6 loopback (``::1``), tolerates an
    optional IPv6 zone identifier and surrounding brackets, and treats the
    literal ``"localhost"`` as loopback.

    Args:
        remote_addr: The remote address of the inbound connection, e.g.
            ``"127.0.0.1"``, ``"::1"``, or a public address. May be ``None``.

    Returns:
        True if the address is a loopback address, otherwise False. A missing,
        empty, or unparseable address is treated as non-loopback (fail closed).

    **Validates: Requirements 1.3, 11.1, 11.2**
    """
    if not remote_addr:
        return False

    addr = remote_addr.strip()
    if not addr:
        return False
    if addr.lower() == "localhost":
        return True

    # Strip surrounding brackets from an IPv6 literal (e.g. "[::1]") and any
    # scope/zone identifier (e.g. "fe80::1%eth0" or "::1%lo").
    addr = addr.strip("[]")
    if "%" in addr:
        addr = addr.split("%", 1)[0]

    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        # Anything that is not a valid IP literal is not loopback (fail closed).
        return False

    return ip.is_loopback


@runtime_checkable
class ConfirmationManager(Protocol):
    """Injectable seam for the risk gate (step 7 of the gauntlet).

    A ``Risky_Action`` must not execute until its Confirmation_Prompt is
    approved (Req 6.1, 6.2). The full confirmation flow (approve / decline /
    30-second timeout) is implemented separately; the gauntlet depends only on
    this seam so it can be wired incrementally and tested in isolation.

    Implementations return ``None`` to allow a risky command to proceed to
    execution (the prompt has been approved), or an :class:`ExecutionResult`
    to withhold or decline it. The gauntlet only consults this seam for
    commands classified as :attr:`RiskClass.RISKY`; standard commands bypass it.
    """

    def require_confirmation(
        self,
        command: StructuredCommand,
        registered: RegisteredCommand,
        now: float,
    ) -> Optional[ExecutionResult]:
        """Gate a Risky_Action on an approved Confirmation_Prompt.

        Args:
            command: The Structured_Command referencing a Risky_Action.
            registered: The matching Registered_Command from the allow-list.
            now: The current time in epoch seconds.

        Returns:
            ``None`` when the action is approved and may execute, otherwise an
            :class:`ExecutionResult` describing why execution is withheld.
        """
        ...


class PendingConfirmationManager:
    """Default risk-gate seam that withholds every Risky_Action.

    Until the full Confirmation_Manager (with the approve / decline / timeout
    flow) is wired in, this default fails closed: every risky command is
    withheld pending explicit confirmation and never executes (Req 6.1, 6.2).
    It returns a ``CONFIRMATION_REQUIRED`` result so the FRIDAY_UI knows to
    raise a Confirmation_Prompt.
    """

    def require_confirmation(
        self,
        command: StructuredCommand,
        registered: RegisteredCommand,
        now: float,
    ) -> Optional[ExecutionResult]:
        """Withhold the risky command pending confirmation (Req 6.1, 6.2)."""
        return ExecutionResult(
            status=CommandStatus.CONFIRMATION_REQUIRED,
            command_id=command.command_id,
            detail=(
                "This action is classified as risky and requires explicit "
                "confirmation before it will be executed."
            ),
        )


def _now_iso(epoch_seconds: float) -> str:
    """Convert epoch seconds to an ISO 8601 UTC timestamp string."""
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


class LoopbackCommandServer:
    """Loopback-only command server wiring the enforcement gauntlet together.

    Binds the Local_Channel to ``127.0.0.1`` only (Req 1.2, 11.1) and routes
    every inbound command through the ordered enforcement gauntlet before it can
    reach the operating system. The dependencies are injected so the server can
    be exercised with fakes in tests and with the real components in production.

    Args:
        authenticator: Issues and validates per-session tokens and enforces the
            invalid-token lockout.
        authorization: Holds User_Authorization state and gates execution.
        state: The agent state machine enforcing the Kill_Switch disabled
            behavior.
        executor: The command executor that dispatches to OS handlers.
        audit: The append-only Audit_Log; every rejection and outcome is
            recorded here.
        confirmation: The risk-gate seam. Defaults to
            :class:`PendingConfirmationManager`, which withholds all risky
            commands pending confirmation.
        host: The interface to bind. Defaults to ``127.0.0.1`` and is validated
            to be a loopback address so the server can never be exposed to the
            network.
        port: The TCP port to bind. ``0`` selects an ephemeral free port.
    """

    def __init__(
        self,
        authenticator: SessionTokenAuthenticator,
        authorization: AuthorizationManager,
        state: AgentStateMachine,
        executor: CommandExecutor,
        audit: AuditLog,
        confirmation: Optional[ConfirmationManager] = None,
        host: str = LOOPBACK_HOST,
        port: int = 0,
    ) -> None:
        if not is_loopback(host):
            # Refuse to ever bind to a non-loopback interface (Req 1.2, 11.1).
            raise ValueError(
                f"Local_Channel may only bind to a loopback address, got {host!r}"
            )
        self._authenticator = authenticator
        self._authorization = authorization
        self._state = state
        self._executor = executor
        self._audit = audit
        self._confirmation: ConfirmationManager = (
            confirmation if confirmation is not None else PendingConfirmationManager()
        )
        self._host = host
        self._port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # -- Enforcement gauntlet (near-pure, socket-free) ------------------------

    def handle_command(
        self,
        remote_addr: Optional[str],
        token: Optional[str],
        command: StructuredCommand,
        now: Optional[float] = None,
    ) -> ExecutionResult:
        """Run a command request through the ordered enforcement gauntlet.

        Applies the design's trust-and-enforcement layers in order. Each layer
        that rejects records a decline in the Audit_Log and returns a status;
        only a request that passes every layer reaches the executor and is
        executed with its outcome audited.

        This method performs no socket I/O, making it directly unit- and
        property-testable independent of the HTTP transport.

        Args:
            remote_addr: The remote address of the inbound connection.
            token: The session token presented on the request, or ``None``.
            command: The Structured_Command to evaluate and (if allowed)
                execute.
            now: The current time in epoch seconds. Defaults to wall-clock time.

        Returns:
            An :class:`ExecutionResult` carrying the outcome status: a
            gauntlet-rejection status when a layer declines, or the executor's
            ``SUCCESS``/``FAILURE`` result when the command runs.

        **Validates: Requirements 1.3, 3.2, 3.3, 3.4, 11.2, 12.2**
        """
        current = time.time() if now is None else float(now)
        command_id = command.command_id

        # Layer 1: transport origin check (Req 1.3, 11.1, 11.2).
        if not is_loopback(remote_addr):
            self._audit.record_decline(
                command_id,
                reason=f"non-loopback origin rejected: {remote_addr!r}",
            )
            return ExecutionResult(
                status=CommandStatus.CONNECTION_REFUSED,
                command_id=command_id,
                detail="Requests are accepted only from the loopback interface.",
            )

        # Layer 2: session token check + lockout (Req 11.3, 11.4, 1.7).
        if self._authenticator.is_locked_out(current):
            self._audit.record_decline(
                command_id,
                reason="temporarily refused: authentication lockout active",
            )
            return ExecutionResult(
                status=CommandStatus.LOCKED_OUT,
                command_id=command_id,
                detail="Too many invalid tokens; new attempts are temporarily refused.",
            )

        auth_result = self._authenticator.validate_token(token, current)
        if not auth_result.valid:
            locked_now = self._authenticator.register_failure(current)
            self._audit.record_decline(
                command_id,
                reason=f"invalid session token ({auth_result.reason})",
            )
            if locked_now:
                # The failure just triggered a lockout; record it (Req 1.7).
                self._audit.record_lockout()
            return ExecutionResult(
                status=CommandStatus.AUTHENTICATION_ERROR,
                command_id=command_id,
                detail=f"Session token {auth_result.reason}.",
            )

        # Layer 3: enabled / kill-switch check (Req 8.5).
        disabled = self._state.require_enabled()
        if disabled is not None:
            self._audit.record_decline(
                command_id,
                reason="agent disabled by kill-switch",
            )
            return ExecutionResult(
                status=disabled.status,
                command_id=command_id,
                detail=disabled.detail,
            )

        # Layer 4: authorization check (Req 2.1, 2.2).
        unauthorized = self._authorization.require_authorization()
        if unauthorized is not None:
            self._audit.record_decline(
                command_id,
                reason="User_Authorization absent or revoked",
            )
            return ExecutionResult(
                status=unauthorized.status,
                command_id=command_id,
                detail=unauthorized.detail,
            )

        # Layer 5: registry allow-list check (Req 3.2, 3.3, 3.4, 12.2).
        registered = registry_lookup(command_id)
        if registered is None:
            self._audit.record_decline(
                command_id,
                reason="command not in Command_Registry allow-list",
            )
            return ExecutionResult(
                status=CommandStatus.UNSUPPORTED,
                command_id=command_id,
                detail=(
                    "The referenced command is not in the allow-list. Arbitrary "
                    "shell/OS strings and unlock/bypass requests are unsupported."
                ),
            )

        # Layer 6: parameter validation (Req 3.6).
        validation = validate_parameters_result(registered, command.parameters)
        if not validation.valid:
            self._audit.record_decline(
                command_id,
                reason=f"parameter validation failed: {validation.error}",
            )
            return ExecutionResult(
                status=CommandStatus.VALIDATION_ERROR,
                command_id=command_id,
                detail=validation.error or "Parameter validation failed.",
            )

        # Layer 7: risk gate for Risky_Actions (Req 6.1, 6.2).
        if registered.risk_class is RiskClass.RISKY:
            withheld = self._confirmation.require_confirmation(
                command, registered, current
            )
            if withheld is not None:
                self._audit.record_decline(
                    command_id,
                    reason="risky action withheld pending confirmation",
                )
                return withheld

        # Layer 8: execution + audit (the executor records the outcome).
        return self._executor.execute(command)

    # -- HTTP transport (thin adapter over handle_command) --------------------

    def start(self) -> tuple[str, int]:
        """Bind the loopback socket and start serving in a background thread.

        Creates a threading HTTP server bound to the loopback ``host``/``port``
        (Req 1.2, 11.1) and serves requests on a daemon thread so callers retain
        control. Idempotent: calling ``start`` again while already running
        returns the current bound address.

        Returns:
            The ``(host, port)`` the server is actually bound to. When ``port``
            was ``0`` this reflects the OS-assigned ephemeral port.
        """
        if self._httpd is not None:
            return self.bound_address  # already running

        handler = _make_request_handler(self)
        self._httpd = ThreadingHTTPServer((self._host, self._port), handler)
        # Reflect the actually-bound port back (relevant when port == 0).
        self._host, self._port = self._httpd.server_address[:2]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="friday-desktop-agent-loopback",
            daemon=True,
        )
        self._thread.start()
        return self.bound_address

    def stop(self) -> None:
        """Stop serving and release the loopback socket."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    @property
    def bound_address(self) -> tuple[str, int]:
        """The ``(host, port)`` the server is bound to."""
        return (self._host, self._port)

    # -- Endpoint operations invoked by the HTTP handler ----------------------

    def issue_token(self, now: Optional[float] = None) -> dict[str, Any]:
        """Issue a new per-session token for a connecting FRIDAY_UI session."""
        token = self._authenticator.issue_token(now)
        return {
            "token": token.value,
            "issued_at": token.issued_at,
            "expires_at": token.expires_at,
        }

    def grant_authorization(
        self, scope: list[str], now: Optional[float] = None
    ) -> dict[str, Any]:
        """Grant User_Authorization for ``scope`` (authorization endpoint)."""
        moment = time.time() if now is None else float(now)
        entry = self._authorization.grant(scope, moment)
        return {"status": "authorized", "scope": sorted(set(scope)), "timestamp": entry.timestamp}

    def revoke_authorization(self, now: Optional[float] = None) -> dict[str, Any]:
        """Revoke User_Authorization (authorization endpoint)."""
        moment = time.time() if now is None else float(now)
        entry = self._authorization.revoke(moment)
        return {"status": "revoked", "timestamp": entry.timestamp}

    def activate_kill_switch(self, now: Optional[float] = None) -> dict[str, Any]:
        """Activate the Kill_Switch, disabling the agent (kill-switch endpoint)."""
        moment = time.time() if now is None else float(now)
        entry = self._state.activate_kill_switch(moment)
        return {"status": "disabled", "timestamp": entry.timestamp}

    def audit_history(self) -> list[dict[str, Any]]:
        """Return the Audit_Log entries newest-first (audit-history endpoint)."""
        entries = self._audit.read_reverse_chronological()
        return [
            {
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "command_id": e.command_id,
                "parameters": e.parameters,
                "outcome": e.outcome,
                "reason": e.reason,
            }
            for e in entries
        ]


def _make_request_handler(server: LoopbackCommandServer) -> type[BaseHTTPRequestHandler]:
    """Build a request-handler class bound to a specific server facade.

    The handler is a thin adapter: it enforces the loopback origin at the
    transport edge, decodes JSON request bodies, and forwards the work to the
    server's endpoint operations (including :meth:`handle_command` for the
    command endpoint). All decision logic remains in the server facade.
    """

    class _LoopbackRequestHandler(BaseHTTPRequestHandler):
        # Silence default stderr logging to keep the agent quiet.
        def log_message(self, *_args: Any) -> None:  # noqa: D401
            return

        @property
        def _remote_addr(self) -> str:
            return self.client_address[0] if self.client_address else ""

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}
            return data if isinstance(data, dict) else {}

        def _send_json(self, status_code: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _reject_non_loopback(self) -> bool:
            """Reject at the transport edge if the origin is not loopback."""
            if is_loopback(self._remote_addr):
                return False
            self._send_json(
                403,
                {
                    "status": CommandStatus.CONNECTION_REFUSED.value,
                    "detail": "Only loopback connections are accepted.",
                },
            )
            return True

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self._reject_non_loopback():
                return
            body = self._read_json_body()
            path = self.path.rstrip("/") or "/"

            if path == "/command":
                token = self.headers.get("X-Session-Token") or body.get("token")
                command = StructuredCommand(
                    command_id=str(body.get("command_id", "")),
                    parameters=dict(body.get("parameters", {}) or {}),
                    confidence=float(body.get("confidence", 0.0) or 0.0),
                )
                result = server.handle_command(self._remote_addr, token, command)
                self._send_json(
                    200,
                    {
                        "status": result.status.value,
                        "command_id": result.command_id,
                        "detail": result.detail,
                    },
                )
                return

            if path == "/authorization":
                action = body.get("action")
                if action == "grant":
                    self._send_json(
                        200, server.grant_authorization(list(body.get("scope", [])))
                    )
                elif action == "revoke":
                    self._send_json(200, server.revoke_authorization())
                else:
                    self._send_json(400, {"detail": "Unknown authorization action."})
                return

            if path == "/kill-switch":
                self._send_json(200, server.activate_kill_switch())
                return

            if path == "/screen-awareness":
                # The Screen_Observer opt-in flow is implemented separately; the
                # endpoint is exposed here as a documented, not-yet-wired hook.
                self._send_json(
                    501,
                    {"detail": "Screen awareness is not yet available."},
                )
                return

            self._send_json(404, {"detail": "Unknown endpoint."})

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self._reject_non_loopback():
                return
            path = self.path.rstrip("/") or "/"
            if path == "/audit-history":
                self._send_json(200, {"entries": server.audit_history()})
                return
            self._send_json(404, {"detail": "Unknown endpoint."})

    return _LoopbackRequestHandler
