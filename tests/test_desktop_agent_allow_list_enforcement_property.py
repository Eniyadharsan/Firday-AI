# Feature: friday-desktop-agent, Property 6: Allow-list enforcement
"""Property-based tests for the Desktop_Agent allow-list enforcement.

Property 6: Allow-list enforcement
For any Structured_Command, the Desktop_Agent SHALL execute it only if its
referenced command identifier exists in the Command_Registry; every command
identifier absent from the registry -- including arbitrary shell/OS strings and
any unlock/bypass request -- SHALL be declined with an unsupported-command
status and recorded in the Audit_Log.

Validates: Requirements 3.2, 3.3, 3.4, 12.2
"""

from __future__ import annotations

import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.audit import AuditLog
from friday.desktop_agent.authorization import AuthorizationManager
from friday.desktop_agent.auth import SessionTokenAuthenticator
from friday.desktop_agent.executor import CommandExecutor
from friday.desktop_agent.models import (
    AgentState,
    CommandStatus,
    ExecutionResult,
    StructuredCommand,
)
from friday.desktop_agent.registry import all_commands
from friday.desktop_agent.server import LoopbackCommandServer
from friday.desktop_agent.state import AgentStateMachine

# The complete set of identifiers that DO exist in the Command_Registry
# allow-list. Any identifier outside this set is "absent from the registry".
_REGISTERED_IDS: frozenset[str] = frozenset(
    cmd.command_id for cmd in all_commands()
)

# A fixed epoch second used as the injected clock so token/authorization state
# is consistent across the gauntlet. Roughly year 2020.
_NOW = 1_600_000_000.0

# Confidence values in the valid inclusive range [0.0, 1.0].
_confidences = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Non-whitespace visible-ASCII strings so required string parameters pass the
# validator's non-empty check.
_nonempty_text = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=50,
)

# Arbitrary parameter maps forwarded with a rejected request. Since the
# allow-list gate runs before parameter validation, params are irrelevant to
# the outcome for absent commands.
_arbitrary_parameters = st.dictionaries(
    keys=st.text(min_size=1, max_size=16),
    values=st.one_of(
        st.text(max_size=32),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
    ),
    max_size=5,
)

# Arbitrary shell / OS command strings that are NOT Registered_Commands. These
# must be treated as unsupported and declined (Req 3.4, 12.2).
_SHELL_LIKE = [
    "rm -rf /",
    "del /f /q C:\\Windows",
    "format C:",
    "cmd.exe /c dir",
    "powershell -Command Get-Process",
    "bash -c 'ls -la'",
    "sudo shutdown now",
    ":(){ :|:& };:",
    "; DROP TABLE users;--",
    "$(reboot)",
    "`whoami`",
    "regedit /s payload.reg",
    "net user administrator /active:yes",
    "wscript evil.vbs",
]

# Unlock / bypass requests that the agent must decline; the registry excludes
# any such capability by construction (Req 12.2).
_UNLOCK_LIKE = [
    "unlock_pc",
    "unlock",
    "bypass_lock_screen",
    "bypass_login",
    "disable_lockscreen",
    "unlock the pc",
    "skip_login",
    "override_password",
    "unlock_workstation",
    "logon_bypass",
]

# Command identifiers that are guaranteed absent from the registry: arbitrary
# free text (filtered to exclude any real id), shell-like strings, and
# unlock/bypass requests.
_absent_command_ids = st.one_of(
    st.text(max_size=40).filter(lambda s: s not in _REGISTERED_IDS),
    st.sampled_from(_SHELL_LIKE),
    st.sampled_from(_UNLOCK_LIKE),
)


class _ExecutorSpy:
    """A spy standing in for the Command Executor.

    Records whether execution was ever attempted so tests can assert that a
    command absent from the registry never reaches the OS handler layer, while
    a registered command does.
    """

    def __init__(self) -> None:
        self.calls: list[StructuredCommand] = []

    @property
    def executed(self) -> bool:
        return bool(self.calls)

    def execute(self, command: StructuredCommand) -> ExecutionResult:
        self.calls.append(command)
        return ExecutionResult(
            status=CommandStatus.SUCCESS, command_id=command.command_id
        )


def _build_server(
    audit: AuditLog, executor: object
) -> LoopbackCommandServer:
    """Wire a gauntlet whose pre-registry layers all pass.

    A valid token is issued, User_Authorization is granted, and the agent is
    enabled, so a request reaches the registry allow-list gate. This isolates
    Property 6: the only remaining decision is whether the referenced command
    exists in the Command_Registry.

    Returns the wired server; the issued token value is available via the
    authenticator, so callers issue their own token before use.
    """
    authenticator = SessionTokenAuthenticator()
    authorization = AuthorizationManager()
    authorization.grant(["desktop"], now=_NOW)
    state = AgentStateMachine(initial_state=AgentState.ENABLED)
    return LoopbackCommandServer(
        authenticator=authenticator,
        authorization=authorization,
        state=state,
        executor=executor,  # type: ignore[arg-type]
        audit=audit,
    )


def _valid_registered_command(draw: st.DrawFn) -> StructuredCommand:
    """Draw a Structured_Command for a STANDARD registered command with valid
    parameters, so it passes validation and reaches the executor."""
    command_id = draw(
        st.sampled_from(
            ["launch_app", "open_path", "web_search", "media_control", "dictation"]
        )
    )
    confidence = draw(_confidences)
    if command_id == "launch_app":
        parameters = {"app_name": draw(_nonempty_text)}
    elif command_id == "open_path":
        parameters = {"path": draw(_nonempty_text)}
    elif command_id == "web_search":
        parameters = {"query": draw(_nonempty_text)}
    elif command_id == "media_control":
        parameters = {"action": draw(st.sampled_from(["play", "pause", "next", "previous"]))}
    else:  # dictation
        parameters = {"text": draw(_nonempty_text)}
    return StructuredCommand(
        command_id=command_id, parameters=parameters, confidence=confidence
    )


_registered_standard_commands = st.composite(_valid_registered_command)()


def _has_decline_for(audit: AuditLog, command_id: str) -> bool:
    """True if the Audit_Log records a decline for ``command_id`` citing the
    allow-list gate, with the required identifier, reason, and timestamp."""
    for entry in audit.read_reverse_chronological():
        if (
            entry.event_type == "decline"
            and entry.command_id == command_id
            and entry.reason is not None
            and "allow-list" in entry.reason
            and entry.timestamp
        ):
            return True
    return False


@settings(max_examples=200)
@given(command_id=_absent_command_ids, parameters=_arbitrary_parameters, confidence=_confidences)
def test_absent_command_is_declined_unsupported_and_audited(
    command_id: str, parameters: dict, confidence: float
) -> None:
    """A command absent from the registry is declined and never executes.

    For any identifier not in the Command_Registry -- including arbitrary
    shell/OS strings and unlock/bypass requests -- the gauntlet returns an
    ``unsupported-command`` status, records the decline in the Audit_Log, and
    never invokes the executor (Req 3.2, 3.3, 3.4, 12.2).
    """
    with tempfile.TemporaryDirectory() as tmp:
        audit = AuditLog(data_dir=tmp)
        executor = _ExecutorSpy()
        server = _build_server(audit, executor)
        token = server._authenticator.issue_token(now=_NOW)  # noqa: SLF001

        command = StructuredCommand(
            command_id=command_id, parameters=parameters, confidence=confidence
        )
        result = server.handle_command("127.0.0.1", token.value, command, now=_NOW)

        assert result.status == CommandStatus.UNSUPPORTED
        assert result.command_id == command_id
        # The command absent from the allow-list never reaches the OS handler.
        assert executor.executed is False
        # The decline is recorded in the Audit_Log with the required fields.
        assert _has_decline_for(audit, command_id)


@settings(max_examples=200)
@given(command_id=st.sampled_from(_UNLOCK_LIKE), parameters=_arbitrary_parameters)
def test_unlock_bypass_requests_are_declined_and_audited(
    command_id: str, parameters: dict
) -> None:
    """Any unlock/bypass request is declined as unsupported and recorded.

    The Command_Registry excludes unlock/lock-screen-bypass/login-bypass
    capabilities by construction, so such requests are structurally
    unsupported and are declined with an audited entry (Req 3.4, 12.2).
    """
    with tempfile.TemporaryDirectory() as tmp:
        audit = AuditLog(data_dir=tmp)
        executor = _ExecutorSpy()
        server = _build_server(audit, executor)
        token = server._authenticator.issue_token(now=_NOW)  # noqa: SLF001

        command = StructuredCommand(
            command_id=command_id, parameters=parameters, confidence=0.99
        )
        result = server.handle_command("127.0.0.1", token.value, command, now=_NOW)

        assert result.status == CommandStatus.UNSUPPORTED
        assert executor.executed is False
        assert _has_decline_for(audit, command_id)


@settings(max_examples=200)
@given(command=_registered_standard_commands)
def test_registered_command_passes_allow_list_and_executes(
    command: StructuredCommand,
) -> None:
    """A command present in the registry passes the allow-list gate.

    The complement of the property: a Structured_Command whose identifier
    exists in the Command_Registry (with valid parameters) is NOT declined as
    unsupported -- it passes the allow-list gate and reaches the executor,
    confirming the agent executes it because it exists in the registry
    (Req 3.2).
    """
    with tempfile.TemporaryDirectory() as tmp:
        audit = AuditLog(data_dir=tmp)
        executor = _ExecutorSpy()
        server = _build_server(audit, executor)
        token = server._authenticator.issue_token(now=_NOW)  # noqa: SLF001

        result = server.handle_command("127.0.0.1", token.value, command, now=_NOW)

        # A registered command is never rejected by the allow-list gate.
        assert result.status != CommandStatus.UNSUPPORTED
        # It reached the executor (proving execution is gated on registry
        # membership, not withheld for a registered standard command).
        assert executor.executed is True
        assert executor.calls[-1].command_id == command.command_id
        assert result.status == CommandStatus.SUCCESS
