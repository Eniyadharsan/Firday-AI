"""Command_Registry allow-list for the FRIDAY Desktop Agent.

The Command_Registry is the immutable allow-list of every action the
Desktop_Agent is permitted to execute. Only actions represented here as a
``RegisteredCommand`` may run; arbitrary shell or OS command strings are not
registered and are therefore structurally unsupported (least-privilege by
construction).

Design references: design.md, "Command_Registry" and "Data Models".

Enforced non-goal: this registry excludes, *by construction*, any command
whose purpose is to unlock the PC or bypass operating-system authentication.
There is no unlock/lock-screen-bypass/login-bypass entry, and none may be
added, so such capabilities cannot be executed (Req 12.1, 12.4).

**Validates: Requirements 3.1, 3.2, 3.3, 3.5, 12.1, 12.4**
"""

from __future__ import annotations

from typing import Optional

from friday.desktop_agent.models import RegisteredCommand, RiskClass

# ---------------------------------------------------------------------------
# Registered command definitions
#
# Each entry declares a stable ``command_id``, a human-readable description, a
# JSON Schema ``parameters`` object (``"type": "object"`` with ``properties``
# and ``required``), a risk classification (standard | risky), and the
# ``handler_name`` mapping to the OS handler that executes it.
#
# Parameter schemas follow the same JSON Schema conventions used by
# ``friday/modules/tool_calling/registry.py`` (properties, required, enum,
# minLength/maxLength, minimum/maximum).
# ---------------------------------------------------------------------------

_LAUNCH_APP = RegisteredCommand(
    command_id="launch_app",
    description=(
        "Launch an installed application by name. Use for requests like "
        "'open Chrome', 'start Notepad', or 'launch Spotify'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "description": "The name of the application to launch.",
            }
        },
        "required": ["app_name"],
    },
    risk_class=RiskClass.STANDARD,
    handler_name="launch_app",
)

_OPEN_PATH = RegisteredCommand(
    command_id="open_path",
    description=(
        "Open a file or folder with its default handler. Use for 'open my "
        "Documents folder' or 'open report.pdf'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4096,
                "description": "The absolute or user-relative path to open.",
            }
        },
        "required": ["path"],
    },
    risk_class=RiskClass.STANDARD,
    handler_name="open_path",
)

_WEB_SEARCH = RegisteredCommand(
    command_id="web_search",
    description=(
        "Open search results for a query in the default browser. Use for "
        "'search for X' or 'look up Y online'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2048,
                "description": "The search query text.",
            }
        },
        "required": ["query"],
    },
    risk_class=RiskClass.STANDARD,
    handler_name="web_search",
)

_MEDIA_CONTROL = RegisteredCommand(
    command_id="media_control",
    description=(
        "Control media playback: play, pause, next, previous, or set the "
        "volume. Use for 'pause the music', 'next track', or 'set volume to 40'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["play", "pause", "next", "previous", "volume"],
                "description": "The media action to perform.",
            },
            "volume": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": (
                    "Target volume level, inclusive 0 to 100. Required only "
                    "when action is 'volume'."
                ),
            },
        },
        "required": ["action"],
    },
    risk_class=RiskClass.STANDARD,
    handler_name="media_control",
)

_DICTATION = RegisteredCommand(
    command_id="dictation",
    description=(
        "Type transcribed text into the active input target. Use for 'type "
        "hello world' or dictating a sentence."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "minLength": 1,
                "maxLength": 8192,
                "description": "The text to type into the active input target.",
            }
        },
        "required": ["text"],
    },
    risk_class=RiskClass.STANDARD,
    handler_name="dictation",
)

_WINDOW_MANAGEMENT = RegisteredCommand(
    command_id="window_management",
    description=(
        "Perform a window action: minimize, maximize, restore, focus, or "
        "close. Use for 'minimize this window' or 'close the window'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["minimize", "maximize", "restore", "focus", "close"],
                "description": "The window action to perform.",
            },
            "target": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "description": (
                    "Optional title or identifier of the target window; "
                    "defaults to the active window when omitted."
                ),
            },
        },
        "required": ["action"],
    },
    # Closing a window can discard unsaved work, so window management is
    # treated as a Risky_Action requiring confirmation before execution.
    risk_class=RiskClass.RISKY,
    handler_name="window_management",
)

_LOCK_PC = RegisteredCommand(
    command_id="lock_pc",
    description=(
        "Lock the operating-system session. Use for 'lock my PC' or 'lock the "
        "screen'. This does NOT unlock the PC or bypass any login."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    # Locking is disruptive (interrupts the current session), so it requires
    # confirmation. Note: locking is permitted; unlocking is excluded entirely.
    risk_class=RiskClass.RISKY,
    handler_name="lock_pc",
)


# The complete, ordered allow-list. This tuple is immutable, and the module
# exposes only read access to it via ``all_commands()`` and ``lookup()``.
#
# By construction, this list contains NO command that unlocks the PC or
# bypasses OS authentication (Req 12.1, 12.4). ``lock_pc`` only locks.
_REGISTERED_COMMANDS: tuple[RegisteredCommand, ...] = (
    _LAUNCH_APP,
    _OPEN_PATH,
    _WEB_SEARCH,
    _MEDIA_CONTROL,
    _DICTATION,
    _WINDOW_MANAGEMENT,
    _LOCK_PC,
)

# Index for O(1) lookups by command identifier.
_REGISTRY_INDEX: dict[str, RegisteredCommand] = {
    command.command_id: command for command in _REGISTERED_COMMANDS
}


def lookup(command_id: str) -> Optional[RegisteredCommand]:
    """Return the RegisteredCommand for ``command_id``, or ``None``.

    This is the single allow-list gate used by the enforcement gauntlet: a
    Structured_Command may be executed only if this returns a non-``None``
    entry (Req 3.2). Any identifier absent from the registry -- including
    arbitrary shell/OS command strings and any unlock/bypass request -- yields
    ``None`` and must be declined as unsupported (Req 3.3, 3.4, 12.2).

    Args:
        command_id: The command identifier referenced by a Structured_Command.

    Returns:
        The matching immutable RegisteredCommand, or ``None`` when no such
        command exists in the Command_Registry.

    **Validates: Requirements 3.2, 3.3**
    """
    return _REGISTRY_INDEX.get(command_id)


def all_commands() -> tuple[RegisteredCommand, ...]:
    """Return the complete immutable allow-list of RegisteredCommands.

    The returned tuple is the full set of actions the Desktop_Agent is
    permitted to execute (Req 3.1). It is immutable, so callers cannot mutate
    the registry.

    **Validates: Requirements 3.1**
    """
    return _REGISTERED_COMMANDS
