"""Desktop_Agent runtime assembly (the local agent process wiring).

This module wires the independent Desktop_Agent components into a single,
ready-to-run agent. It is the local-process half of task 16.1: it assembles the
Local_Channel loopback server together with the session-token authenticator,
authorization manager, agent state machine, command executor (behind an
injectable OS-handler seam), the Confirmation_Manager risk gate, and a single
shared append-only Audit_Log so every component records into the *same* log.

Design references:
- design.md, "Architecture" -> the Desktop_Agent subgraph.
- design.md, "Trust and Enforcement Layers" (the ordered gauntlet the assembled
  :class:`~friday.desktop_agent.server.LoopbackCommandServer` runs).

The assembly is deliberately parameterized on the :class:`OSHandlers` seam so a
mock handler can be injected in tests (task 16.1 wires the lifecycle through to
a *mocked* OS handler) while production uses :class:`WindowsOSHandlers`. All
side effects remain reachable only through the allow-listed executor.

**Validates: Requirements 4.8, 5.1, 2.1**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from friday.desktop_agent.audit import AuditLog
from friday.desktop_agent.auth import SessionTokenAuthenticator
from friday.desktop_agent.authorization import AuthorizationManager
from friday.desktop_agent.confirmation import ConfirmationManager
from friday.desktop_agent.executor import CommandExecutor, OSHandlers, WindowsOSHandlers
from friday.desktop_agent.models import AgentState
from friday.desktop_agent.server import LOOPBACK_HOST, LoopbackCommandServer
from friday.desktop_agent.state import AgentStateMachine


@dataclass
class DesktopAgentRuntime:
    """A fully-wired Desktop_Agent ready to serve on the Local_Channel.

    Holds the assembled :class:`LoopbackCommandServer` plus references to the
    individual components so callers (and tests) can drive the agent's
    lifecycle: issue a session token, grant/revoke authorization, activate the
    Kill_Switch, resolve confirmation prompts, and read the audit history.

    Attributes:
        server: The loopback command server running the enforcement gauntlet.
        audit: The single shared append-only Audit_Log all components write to.
        authenticator: The session-token authenticator/rate limiter.
        authorization: The User_Authorization manager.
        state: The agent state machine (enabled/observing/disabled).
        executor: The command executor dispatching to the OS-handler seam.
        confirmation: The Confirmation_Manager risk gate for Risky_Actions.
    """

    server: LoopbackCommandServer
    audit: AuditLog
    authenticator: SessionTokenAuthenticator
    authorization: AuthorizationManager
    state: AgentStateMachine
    executor: CommandExecutor
    confirmation: ConfirmationManager


def build_desktop_agent(
    os_handlers: Optional[OSHandlers] = None,
    *,
    audit: Optional[AuditLog] = None,
    host: str = LOOPBACK_HOST,
    port: int = 0,
    initial_state: AgentState = AgentState.ENABLED,
    confirmation_timeout_seconds: Optional[float] = None,
) -> DesktopAgentRuntime:
    """Assemble a fully-wired Desktop_Agent.

    Constructs the shared Audit_Log first, then wires every component to write
    into it, and finally builds the :class:`LoopbackCommandServer` that runs the
    ordered enforcement gauntlet (origin -> token -> enabled -> authorization ->
    registry -> validation -> risk gate -> execute + audit). The OS side-effect
    surface is reached only through the injected :class:`OSHandlers` seam, which
    defaults to :class:`WindowsOSHandlers` in production and can be a mock in
    tests.

    Args:
        os_handlers: The OS side-effect seam the executor dispatches to. Defaults
            to :class:`WindowsOSHandlers`. Inject a mock to exercise the full
            lifecycle without touching the real operating system.
        audit: An existing Audit_Log to share. Defaults to a fresh
            :class:`AuditLog` at the agent data directory.
        host: The loopback host to bind. Validated to be a loopback address by
            the server so the agent can never be network-exposed.
        port: The TCP port to bind; ``0`` selects an ephemeral free port.
        initial_state: The state the agent starts in. Defaults to ``ENABLED``.
        confirmation_timeout_seconds: Optional override for the risky-action
            confirmation window (defaults to the manager's 30-second bound).

    Returns:
        A :class:`DesktopAgentRuntime` holding the wired server and components.

    **Validates: Requirements 4.8, 5.1, 2.1**
    """
    shared_audit = audit if audit is not None else AuditLog()
    handlers = os_handlers if os_handlers is not None else WindowsOSHandlers()

    authenticator = SessionTokenAuthenticator()
    authorization = AuthorizationManager(audit_sink=shared_audit.append)
    state = AgentStateMachine(
        audit_sink=shared_audit.append, initial_state=initial_state
    )
    executor = CommandExecutor(handlers, audit_sink=shared_audit.append)

    confirmation_kwargs = {"audit_sink": shared_audit.append}
    if confirmation_timeout_seconds is not None:
        confirmation_kwargs["timeout_seconds"] = float(confirmation_timeout_seconds)
    confirmation = ConfirmationManager(executor, **confirmation_kwargs)

    server = LoopbackCommandServer(
        authenticator=authenticator,
        authorization=authorization,
        state=state,
        executor=executor,
        audit=shared_audit,
        confirmation=confirmation,
        host=host,
        port=port,
    )

    return DesktopAgentRuntime(
        server=server,
        audit=shared_audit,
        authenticator=authenticator,
        authorization=authorization,
        state=state,
        executor=executor,
        confirmation=confirmation,
    )
