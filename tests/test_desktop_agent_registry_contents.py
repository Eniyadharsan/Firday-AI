"""Unit tests for the Command_Registry contents.

These example-based tests assert that the Command_Registry allow-list contains
exactly the documented command set (launch app, open path, web search, media
control, dictation, window management, lock PC) and that it exposes no
arbitrary-shell / raw-OS-command capability. Only actions represented as a
RegisteredCommand may be executed, so an absent arbitrary-shell command means
such commands are structurally unsupported (least-privilege by construction).

Design references: design.md, "Command_Registry" and "Testing Strategy"
(unit test: "Registry contains the documented command set (Req 3.1)").

Validates: Requirements 3.1, 3.4
"""

from __future__ import annotations

from friday.desktop_agent.models import RegisteredCommand
from friday.desktop_agent.registry import all_commands, lookup

# The complete documented command set the registry must expose (Req 3.1).
_DOCUMENTED_COMMAND_IDS = frozenset(
    {
        "launch_app",
        "open_path",
        "web_search",
        "media_control",
        "dictation",
        "window_management",
        "lock_pc",
    }
)

# Identifiers that would represent an arbitrary shell / raw OS command surface.
# None of these may appear in the allow-list (Req 3.4): arbitrary command
# strings must be structurally unsupported, not registered.
_ARBITRARY_SHELL_IDS = (
    "shell",
    "exec",
    "execute",
    "run",
    "run_command",
    "run_shell",
    "shell_exec",
    "command",
    "cmd",
    "powershell",
    "bash",
    "eval",
    "system",
    "subprocess",
    "os_command",
)


def test_registry_contains_exactly_the_documented_command_set() -> None:
    """The registry exposes exactly the documented command set, no more.

    Validates: Requirements 3.1
    """
    registered_ids = {command.command_id for command in all_commands()}

    assert registered_ids == _DOCUMENTED_COMMAND_IDS, (
        "Command_Registry must contain exactly the documented command set; "
        f"missing={_DOCUMENTED_COMMAND_IDS - registered_ids}, "
        f"unexpected={registered_ids - _DOCUMENTED_COMMAND_IDS}."
    )


def test_each_documented_command_is_lookup_resolvable() -> None:
    """Every documented command id resolves to a RegisteredCommand.

    Validates: Requirements 3.1
    """
    for command_id in _DOCUMENTED_COMMAND_IDS:
        command = lookup(command_id)
        assert isinstance(command, RegisteredCommand), (
            f"Documented command '{command_id}' must resolve via lookup()."
        )
        assert command.command_id == command_id


def test_registry_has_no_duplicate_command_ids() -> None:
    """Command identifiers in the allow-list are unique.

    Validates: Requirements 3.1
    """
    ids = [command.command_id for command in all_commands()]
    assert len(ids) == len(set(ids)), f"Duplicate command ids present: {ids}"


def test_registry_excludes_arbitrary_shell_commands() -> None:
    """No registered command exposes an arbitrary-shell / raw-OS surface.

    Arbitrary shell or OS command strings are not represented as a
    RegisteredCommand, so they are structurally unsupported.

    Validates: Requirements 3.4
    """
    registered_ids = {command.command_id for command in all_commands()}
    registered_handlers = {command.handler_name for command in all_commands()}

    for forbidden in _ARBITRARY_SHELL_IDS:
        assert forbidden not in registered_ids, (
            f"Arbitrary-shell command id '{forbidden}' must not be registered "
            f"(Req 3.4)."
        )
        assert forbidden not in registered_handlers, (
            f"Arbitrary-shell handler '{forbidden}' must not be registered "
            f"(Req 3.4)."
        )
        # Absent identifiers must not resolve through the allow-list gate.
        assert lookup(forbidden) is None, (
            f"lookup('{forbidden}') must return None; arbitrary-shell commands "
            f"are unsupported (Req 3.4)."
        )
