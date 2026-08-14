"""Property-based test for the Command_Registry excluded-capabilities guarantee.

Property 24: Registry excludes unlock/bypass capabilities
- For any command in the Command_Registry, no command SHALL have the purpose
  of unlocking the PC or bypassing operating-system authentication.

The Desktop_Agent enforces this non-goal *by construction*: there is no
registered command whose purpose is to unlock the PC, bypass the OS lock
screen, or bypass the OS login. Note that ``lock_pc`` (which only locks the
session) is permitted -- locking is allowed, unlocking is excluded.

Validates: Requirements 12.1, 12.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.models import RegisteredCommand
from friday.desktop_agent.registry import all_commands

# Machine-readable markers that would indicate an unlock/bypass purpose. These
# are matched against the authoritative purpose fields of a RegisteredCommand
# (its ``command_id`` and ``handler_name``). The token "unlock" is matched
# explicitly so the permitted "lock" purpose is never falsely flagged.
#
# We deliberately do NOT scan the free-text ``description`` for these markers:
# a description may legitimately mention unlocking/bypassing in a *negative*
# disclaimer (e.g. lock_pc's "This does NOT unlock the PC or bypass any
# login."). The command_id and handler_name are the authoritative, unambiguous
# encodings of a command's purpose.
_FORBIDDEN_PURPOSE_MARKERS = (
    "unlock",
    "bypass",
    "defeat",
    "crack",
    "circumvent",
)

# The exact set of command identifiers the registry is permitted to expose.
# Any drift that introduces an unlock/bypass command would fail this guard.
_ALLOWED_COMMAND_IDS = frozenset(
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


def _purpose_indicates_unlock_or_bypass(command: RegisteredCommand) -> bool:
    """Return True if the command's purpose is to unlock/bypass OS auth."""
    identifiers = f"{command.command_id} {command.handler_name}".lower()
    return any(marker in identifiers for marker in _FORBIDDEN_PURPOSE_MARKERS)


# Feature: friday-desktop-agent, Property 24: Registry excludes unlock/bypass capabilities
@settings(max_examples=200)
@given(command=st.sampled_from(all_commands()))
def test_registry_excludes_unlock_and_bypass_capabilities(
    command: RegisteredCommand,
) -> None:
    """No registered command has an unlock/bypass purpose.

    For any command drawn from the Command_Registry allow-list, its purpose
    must not be to unlock the PC or bypass operating-system authentication.

    Validates: Requirements 12.1, 12.4
    """
    assert not _purpose_indicates_unlock_or_bypass(command), (
        f"Command '{command.command_id}' (handler '{command.handler_name}') "
        f"appears to provide an unlock/bypass capability, which is an "
        f"explicit non-goal (Req 12.1, 12.4)."
    )

    # The command must also be one of the known, allow-listed identifiers, so
    # any newly introduced unlock/bypass command cannot slip in unnoticed.
    assert command.command_id in _ALLOWED_COMMAND_IDS, (
        f"Unexpected command '{command.command_id}' in the Command_Registry; "
        f"only allow-listed, non-bypass commands are permitted."
    )
