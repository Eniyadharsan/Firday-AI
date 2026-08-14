"""Core data models for the FRIDAY Desktop Agent.

This module defines the immutable data structures and enums shared across the
Desktop_Agent components: the loopback server, session token authenticator,
authorization manager, command registry, parameter validator, command
executor, confirmation manager, screen observer, audit log, and state machine.

All models are frozen dataclasses designed for type safety and clarity,
following the conventions established in
``friday/modules/tool_calling/models.py``.

**Validates: Requirements 1.4, 1.6, 1.8, 3.5, 4.8, 5.5**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class RiskClass(Enum):
    """Risk classification for a Registered_Command.

    Every command in the Command_Registry carries exactly one classification.
    A ``RISKY`` command requires an approved Confirmation_Prompt before the
    Desktop_Agent will execute it.

    **Validates: Requirements 3.5**
    """

    STANDARD = "standard"
    RISKY = "risky"


class CommandStatus(Enum):
    """Status returned for command parsing and execution outcomes.

    Covers the full set of statuses the Intent_Parser and Desktop_Agent may
    return to the FRIDAY_UI across the enforcement gauntlet and execution.

    Members:
        SUCCESS: A Registered_Command executed successfully (Req 4.8).
        FAILURE: A Registered_Command's handler failed during execution (Req 4.8).
        UNSUPPORTED: The referenced command is absent from the Command_Registry,
            including arbitrary shell strings and unlock/bypass requests
            (Req 3.3, 3.4, 12.2).
        VALIDATION_ERROR: Supplied parameters failed schema validation (Req 3.6).
        AUTHORIZATION_REQUIRED: User_Authorization is absent or revoked (Req 2.2).
        DISABLED: The agent is disabled by the Kill_Switch (Req 8.5).
        UNRECOGNIZED: The Intent_Parser could not map the input to any
            Registered_Command (Req 5.2).
        AMBIGUOUS: The Intent_Parser mapped the input to multiple close
            candidates (Req 5.3).
        VISION_UNAVAILABLE: The Vision_Provider request failed (Req 10.5).
        CONNECTION_REFUSED: The request originated from a non-loopback address
            and was rejected at the transport-origin gate (Req 1.3, 11.2).
        AUTHENTICATION_ERROR: The request presented a missing, invalid, or
            expired session token (Req 1.5, 11.4).
        LOCKED_OUT: New connection attempts are temporarily refused after
            repeated invalid-token attempts (Req 1.7).
        CONFIRMATION_REQUIRED: The request references a Risky_Action whose
            Confirmation_Prompt has not yet been approved, so execution is
            withheld pending confirmation (Req 6.1, 6.2).
        CANCELLED: A Risky_Action's Confirmation_Prompt was declined by the
            user or received no response within 30 seconds, so the action was
            cancelled without executing (Req 6.4, 6.5).
    """

    SUCCESS = "success"
    FAILURE = "failure"
    UNSUPPORTED = "unsupported-command"
    VALIDATION_ERROR = "validation-error"
    AUTHORIZATION_REQUIRED = "authorization-required"
    DISABLED = "disabled"
    UNRECOGNIZED = "unrecognized-command"
    AMBIGUOUS = "ambiguous-command"
    VISION_UNAVAILABLE = "vision-unavailable"
    CONNECTION_REFUSED = "connection-refused"
    AUTHENTICATION_ERROR = "authentication-error"
    LOCKED_OUT = "locked-out"
    CONFIRMATION_REQUIRED = "confirmation-required"
    CANCELLED = "cancelled"


class AgentState(Enum):
    """Operating state of the Desktop_Agent.

    Drives the Active_Indicator and enforces the kill-switch disabled
    behavior. Each state maps to a distinct visible indicator state.

    **Validates: Requirements 1.8, 8.5, 9.1, 9.2, 9.3**
    """

    ENABLED = "enabled"
    OBSERVING = "observing"
    DISABLED = "disabled"


@dataclass(frozen=True)
class RegisteredCommand:
    """An entry in the Command_Registry allow-list.

    Only actions represented by a RegisteredCommand may be executed by the
    Desktop_Agent. Arbitrary shell or OS command strings are not registered
    and are therefore structurally unsupported.

    Attributes:
        command_id: Unique identifier for the allowed action.
        description: Human-readable description of the action.
        parameters: JSON Schema object defining the command's parameters.
            Must contain ``"type": "object"`` at minimum.
        risk_class: Risk classification, exactly one of standard or risky
            (Req 3.5).
        handler_name: Maps to the OS handler that executes this command.

    **Validates: Requirements 3.5**
    """

    command_id: str
    description: str
    parameters: dict[str, Any]
    risk_class: RiskClass
    handler_name: str


@dataclass(frozen=True)
class StructuredCommand:
    """Machine-readable user intent forwarded to the Desktop_Agent.

    Produced by the Intent_Parser and forwarded over the Local_Channel. It
    references a RegisteredCommand identifier and carries validated parameters
    plus the mapping confidence.

    Attributes:
        command_id: References a RegisteredCommand identifier (Req 5.1).
        parameters: Parameters to pass to the command handler.
        confidence: Mapping confidence in the inclusive range 0.0 to 1.0
            (Req 5.5).

    **Validates: Requirements 5.1, 5.5**
    """

    command_id: str
    parameters: dict[str, Any]
    confidence: float


@dataclass(frozen=True)
class IntentResult:
    """Output of the Intent_Parser.

    Carries the parse status and, depending on the status, either a single
    Structured_Command (recognized) or a list of candidate commands
    (ambiguous).

    Attributes:
        status: The parse outcome (recognized/unrecognized/ambiguous).
        command: The mapped Structured_Command when recognized, else None.
        candidates: The candidate commands when ambiguous (Req 5.3).

    **Validates: Requirements 5.1, 5.2, 5.3**
    """

    status: CommandStatus
    command: Optional[StructuredCommand] = None
    candidates: list[StructuredCommand] = field(default_factory=list)


@dataclass(frozen=True)
class SessionToken:
    """Per-session authentication token.

    Issued to a connecting FRIDAY_UI session and required on every command
    request. Carries at least 128 bits of entropy and a bounded lifetime.

    Attributes:
        value: The token string with >=128 bits of entropy (Req 1.4).
        issued_at: Issuance time in epoch seconds.
        expires_at: Expiry time in epoch seconds; must be no more than
            ``issued_at + 3600`` (Req 1.6).

    **Validates: Requirements 1.4, 1.6**
    """

    value: str
    issued_at: float
    expires_at: float


@dataclass(frozen=True)
class AuthResult:
    """Result of validating a presented session token.

    Attributes:
        valid: True if the token is currently-issued and unexpired.
        reason: Why validation failed, one of "missing", "invalid", or
            "expired"; None when valid.
    """

    valid: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class ExecutionResult:
    """Result returned to the FRIDAY_UI after a command request.

    Attributes:
        status: The outcome status (e.g., success/failure or a decline
            status from the enforcement gauntlet).
        command_id: The referenced command identifier, when applicable.
        detail: Human-readable detail about the outcome.

    **Validates: Requirements 4.8**
    """

    status: CommandStatus
    command_id: Optional[str] = None
    detail: str = ""


@dataclass(frozen=True)
class AuditEntry:
    """Append-only audit record.

    A single immutable entry in the local Audit_Log. Entries are only ever
    appended; prior entries are never mutated or removed.

    Attributes:
        timestamp: ISO 8601 timestamp of the event.
        event_type: The kind of event, one of "execute", "decline",
            "authorize", "revoke", "kill_switch", "capture",
            "vision_failure", or "lockout".
        command_id: The referenced command identifier, when applicable.
        parameters: Parameters recorded for executed commands.
        outcome: The execution outcome, when applicable.
        reason: The decline/cancellation reason, when applicable.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    timestamp: str
    event_type: str
    command_id: Optional[str] = None
    parameters: dict[str, Any] = field(default_factory=dict)
    outcome: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class ConfirmationPrompt:
    """Pending confirmation for a Risky_Action.

    Raised when a Structured_Command references a risky command. Execution is
    withheld while the prompt remains unresolved.

    Attributes:
        prompt_id: Unique identifier for this pending prompt.
        command: The Structured_Command awaiting confirmation.
        created_at: Creation time in epoch seconds, used to enforce the
            30-second timeout (Req 6.5).

    **Validates: Requirements 6.1, 6.2, 6.5**
    """

    prompt_id: str
    command: StructuredCommand
    created_at: float
