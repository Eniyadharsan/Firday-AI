# Feature: friday-desktop-agent, Property 1: Loopback-only origin enforcement
"""Property-based tests for the Desktop_Agent loopback-only origin gate.

Property 1: Loopback-only origin enforcement
For any inbound connection remote address, the Desktop_Agent SHALL accept the
request only if the address is a loopback address, and SHALL decline and record
every non-loopback origin.

Validates: Requirements 1.3, 11.1, 11.2
"""

from __future__ import annotations

import ipaddress
from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.audit import AuditLog  # noqa: F401 (documents the seam)
from friday.desktop_agent.auth import SessionTokenAuthenticator
from friday.desktop_agent.authorization import AuthorizationManager
from friday.desktop_agent.models import (
    AgentState,
    AuditEntry,
    CommandStatus,
    ExecutionResult,
    StructuredCommand,
)
from friday.desktop_agent.server import LoopbackCommandServer, is_loopback
from friday.desktop_agent.state import AgentStateMachine

# ---------------------------------------------------------------------------
# Generators for arbitrary IP addresses (loopback and non-loopback, v4/v6).
# ---------------------------------------------------------------------------

# Any IPv4 or IPv6 address. ``st.ip_addresses`` covers the whole address space
# including loopback, so downstream tests filter on ``.is_loopback``.
_any_ip = st.ip_addresses()

# Loopback addresses: the whole IPv4 ``127.0.0.0/8`` block plus IPv6 ``::1``.
_loopback_ips = st.one_of(
    st.ip_addresses(v=4, network="127.0.0.0/8"),
    st.just(ipaddress.ip_address("::1")),
)

# Non-loopback addresses: any address that is not on the loopback interface.
_non_loopback_ips = _any_ip.filter(lambda ip: not ip.is_loopback)

# Arbitrary Structured_Commands carried on the request. The origin gate must
# decide purely on the remote address, regardless of the command payload.
_commands = st.builds(
    StructuredCommand,
    command_id=st.text(min_size=0, max_size=24),
    parameters=st.dictionaries(
        keys=st.text(min_size=1, max_size=12),
        values=st.text(max_size=24),
        max_size=4,
    ),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)

_TIME = 1_600_000_000.0


class _ExecutorSpy:
    """Stands in for the Command Executor and records whether it ran.

    The origin gate is the first layer of the enforcement gauntlet: a
    non-loopback request must be declined before it can reach the executor, so
    ``executed`` must remain False for every rejected origin.
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


class _FakeAudit:
    """In-memory Audit_Log stand-in capturing recorded declines/lockouts.

    Duck-types the subset of the :class:`AuditLog` interface the enforcement
    gauntlet touches so we can assert that every non-loopback origin is
    recorded (Req 11.2) without touching the filesystem.
    """

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def record_decline(
        self,
        command_id: Optional[str],
        reason: str,
        timestamp: Optional[str] = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            timestamp=timestamp or "t",
            event_type="decline",
            command_id=command_id,
            reason=reason,
        )
        self.entries.append(entry)
        return entry

    def record_lockout(
        self, reason: str = "too-many-invalid-tokens", timestamp: Optional[str] = None
    ) -> AuditEntry:
        entry = AuditEntry(
            timestamp=timestamp or "t", event_type="lockout", reason=reason
        )
        self.entries.append(entry)
        return entry

    def append(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    def _non_loopback_declines(self) -> list[AuditEntry]:
        return [
            e
            for e in self.entries
            if e.event_type == "decline"
            and e.reason is not None
            and "non-loopback" in e.reason
        ]


def _make_server(
    audit: _FakeAudit, executor: _ExecutorSpy, *, authorized: bool
) -> LoopbackCommandServer:
    """Build a loopback server wired with the given audit sink and executor."""
    authenticator = SessionTokenAuthenticator()
    authorization = AuthorizationManager()
    if authorized:
        authorization.grant(["desktop"], now=_TIME)
    state = AgentStateMachine(initial_state=AgentState.ENABLED)
    return LoopbackCommandServer(
        authenticator=authenticator,
        authorization=authorization,
        state=state,
        executor=executor,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# The pure origin classifier agrees with the standard-library definition.
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(ip=_any_ip)
def test_is_loopback_matches_stdlib_classification(ip: ipaddress._BaseAddress) -> None:
    """``is_loopback`` classifies any IP exactly as the stdlib does.

    For any generated IPv4 or IPv6 address, the agent's origin gate agrees with
    ``ipaddress``'s own ``is_loopback`` determination, so loopback addresses are
    admitted and all others are rejected (Req 1.3, 11.1, 11.2).
    """
    assert is_loopback(str(ip)) is bool(ip.is_loopback)


# ---------------------------------------------------------------------------
# Non-loopback origins are declined, never executed, and always recorded.
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(ip=_non_loopback_ips, command=_commands)
def test_non_loopback_origin_is_declined_and_recorded(
    ip: ipaddress._BaseAddress, command: StructuredCommand
) -> None:
    """Every non-loopback origin is refused, unexecuted, and audited.

    A request from any non-loopback address is declined at the transport gate
    with a ``connection-refused`` status, never reaches the executor, and is
    recorded in the Audit_Log (Req 1.3, 11.2).
    """
    audit = _FakeAudit()
    executor = _ExecutorSpy()
    # Authorize + valid setup so that ONLY the origin gate can be the reason a
    # request is refused; any rejection here must stem from the address.
    server = _make_server(audit, executor, authorized=True)

    result = server.handle_command(str(ip), token="anything", command=command, now=_TIME)

    assert result.status == CommandStatus.CONNECTION_REFUSED
    assert executor.executed is False
    assert executor.calls == []
    # The non-loopback origin was recorded in the Audit_Log (Req 11.2).
    declines = audit._non_loopback_declines()
    assert len(declines) == 1
    assert declines[0].reason is not None and repr(str(ip)) in declines[0].reason


# ---------------------------------------------------------------------------
# Loopback origins pass the origin gate and reach execution.
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(ip=_loopback_ips)
def test_loopback_origin_passes_origin_gate_and_executes(
    ip: ipaddress._BaseAddress,
) -> None:
    """A loopback origin is accepted at the transport gate and proceeds.

    With a valid token and granted authorization, a request from any loopback
    address passes the origin gate and runs a valid Registered_Command through
    to the executor, and no non-loopback rejection is recorded (Req 1.3, 11.1).
    """
    audit = _FakeAudit()
    executor = _ExecutorSpy()
    server = _make_server(audit, executor, authorized=True)
    # Issue a valid token for this session so the request clears the token gate.
    token = server.issue_token(now=_TIME)["token"]

    command = StructuredCommand(
        command_id="web_search",
        parameters={"query": "hello world"},
        confidence=1.0,
    )
    result = server.handle_command(str(ip), token=token, command=command, now=_TIME)

    # Origin gate admitted the request: it was never connection-refused and it
    # reached the executor.
    assert result.status != CommandStatus.CONNECTION_REFUSED
    assert result.status == CommandStatus.SUCCESS
    assert executor.executed is True
    assert audit._non_loopback_declines() == []
