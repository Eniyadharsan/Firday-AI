"""Confirmation Manager for Risky_Actions in the FRIDAY Desktop Agent.

A ``Risky_Action`` is a Registered_Command classified as destructive,
irreversible, or high-impact. Before such an action runs, the Desktop_Agent
must obtain explicit user confirmation. This module implements that flow as the
risk gate (Layer 7) of the enforcement gauntlet.

Design reference: design.md, "Desktop_Agent components" -> "Confirmation
Manager", and "Trust and Enforcement Layers" -> step 7 (Risk gate).

Behavior summary:
    * When a Structured_Command references a Risky_Action, the manager raises a
      pending :class:`ConfirmationPrompt` and withholds execution, returning a
      ``CONFIRMATION_REQUIRED`` result to the caller (Req 6.1, 6.2).
    * :meth:`approve` resolves a pending prompt by executing the associated
      action and recording the approval in the Audit_Log (Req 6.3).
    * :meth:`decline` resolves a pending prompt by cancelling the action
      without executing it and recording the cancellation (Req 6.4).
    * A prompt that receives no response within 30 seconds is cancelled without
      executing and the timeout is recorded (Req 6.5); :meth:`check_timeouts`
      sweeps stale prompts, and :meth:`approve` fails closed by never executing
      an already-expired prompt.

The manager implements the ``ConfirmationManager`` Protocol defined in
``friday.desktop_agent.server`` (the method
``require_confirmation(command, registered, now) -> Optional[ExecutionResult]``)
so it can be injected directly into :class:`LoopbackCommandServer` as the
risk-gate seam. Execution is delegated to the same :class:`CommandExecutor`
the gauntlet uses, so an approved risky action runs through the identical
handler/audit path as a standard command.

All timing is driven by injected ``now`` values (epoch seconds), so the flow is
fully deterministic and testable without real clocks.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from friday.desktop_agent.executor import CommandExecutor
from friday.desktop_agent.models import (
    AuditEntry,
    CommandStatus,
    ConfirmationPrompt,
    ExecutionResult,
    RegisteredCommand,
    StructuredCommand,
)

# Seam for recording audit events, matching the AuthorizationManager /
# CommandExecutor pattern. Pass the Audit_Log's ``append`` method to persist
# confirmation events, or a collecting fake in tests.
AuditSink = Callable[[AuditEntry], None]

# Factory for generating unique prompt identifiers; injectable for tests.
PromptIdFactory = Callable[[], str]

# The confirmation window: a prompt with no response within this many seconds
# is cancelled (Req 6.5).
DEFAULT_TIMEOUT_SECONDS: float = 30.0

# Audit event type recorded for every confirmation resolution.
EVENT_CONFIRMATION = "confirmation"

# Cancellation reasons recorded on the audit entry.
REASON_DECLINED = "declined"
REASON_TIMEOUT = "timeout"


def _to_iso8601(epoch_seconds: float) -> str:
    """Convert epoch seconds to an ISO 8601 UTC timestamp string.

    The ``now`` values used across the Desktop_Agent are epoch seconds
    (matching :class:`SessionToken` and :class:`ConfirmationPrompt`), while
    :attr:`AuditEntry.timestamp` is an ISO 8601 string.
    """
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


class ConfirmationManager:
    """Raises, tracks, and resolves Confirmation_Prompts for Risky_Actions.

    The manager holds the set of currently-pending prompts keyed by their
    ``prompt_id``. A pending prompt withholds its action's execution until it
    is explicitly approved, explicitly declined, or times out (Req 6.2). It
    implements the risk-gate seam consumed by :class:`LoopbackCommandServer`,
    so injecting an instance wires confirmation into the enforcement gauntlet
    without any further changes.

    Args:
        executor: The :class:`CommandExecutor` used to run an approved risky
            action. Should be the same executor the gauntlet uses so approved
            commands follow the identical handler/audit path.
        audit_sink: Optional callback invoked with an :class:`AuditEntry` for
            every confirmation resolution (approval or cancellation). Pass the
            Audit_Log's ``append`` method to persist events, or omit it.
        timeout_seconds: The confirmation window in seconds. Defaults to 30
            (Req 6.5).
        prompt_id_factory: Optional factory producing unique prompt ids.
            Defaults to :func:`secrets.token_urlsafe`; injectable for tests.
    """

    def __init__(
        self,
        executor: CommandExecutor,
        audit_sink: Optional[AuditSink] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        prompt_id_factory: Optional[PromptIdFactory] = None,
    ) -> None:
        self._executor = executor
        self._audit_sink = audit_sink
        self._timeout_seconds = float(timeout_seconds)
        self._id_factory: PromptIdFactory = (
            prompt_id_factory
            if prompt_id_factory is not None
            else (lambda: secrets.token_urlsafe(16))
        )
        self._pending: dict[str, ConfirmationPrompt] = {}

    # -- Introspection --------------------------------------------------------

    @property
    def pending_prompt_ids(self) -> frozenset[str]:
        """The ids of all prompts currently awaiting a response."""
        return frozenset(self._pending)

    def is_pending(self, prompt_id: str) -> bool:
        """Return True if ``prompt_id`` references an unresolved prompt."""
        return prompt_id in self._pending

    def get_prompt(self, prompt_id: str) -> Optional[ConfirmationPrompt]:
        """Return the pending :class:`ConfirmationPrompt`, or ``None``."""
        return self._pending.get(prompt_id)

    # -- Risk-gate seam (Layer 7 of the enforcement gauntlet) ----------------

    def require_confirmation(
        self,
        command: StructuredCommand,
        registered: RegisteredCommand,
        now: float,
    ) -> Optional[ExecutionResult]:
        """Raise a Confirmation_Prompt for a Risky_Action and withhold it.

        Implements the ``ConfirmationManager`` Protocol consumed by
        :class:`LoopbackCommandServer`. The gauntlet calls this only for a
        command classified as ``RISKY``. A new pending prompt is created and
        execution is withheld: the returned result carries a
        ``CONFIRMATION_REQUIRED`` status and the generated ``prompt_id`` (in its
        ``detail``) so the FRIDAY_UI can raise the corresponding prompt and
        later approve or decline it (Req 6.1, 6.2).

        Args:
            command: The Structured_Command referencing a Risky_Action.
            registered: The matching Registered_Command from the allow-list.
            now: The current time in epoch seconds; used as the prompt's
                ``created_at`` for the 30-second timeout (Req 6.5).

        Returns:
            An :class:`ExecutionResult` with a ``CONFIRMATION_REQUIRED`` status.
            Never returns ``None``: a freshly-arrived risky action always
            withholds execution pending explicit confirmation (fail closed).

        **Validates: Requirements 6.1, 6.2**
        """
        prompt_id = self._new_prompt_id()
        prompt = ConfirmationPrompt(
            prompt_id=prompt_id,
            command=command,
            created_at=float(now),
        )
        self._pending[prompt_id] = prompt
        return ExecutionResult(
            status=CommandStatus.CONFIRMATION_REQUIRED,
            command_id=command.command_id,
            detail=(
                "This action is classified as risky and requires explicit "
                f"confirmation before it will be executed. prompt_id={prompt_id}"
            ),
        )

    # -- Resolution -----------------------------------------------------------

    def approve(
        self, prompt_id: str, now: Optional[float] = None
    ) -> ExecutionResult:
        """Approve a pending prompt: execute the action and record it.

        Resolves the prompt identified by ``prompt_id`` by executing its
        associated Risky_Action through the injected executor and recording the
        approval in the Audit_Log (Req 6.3). Fails closed: if the prompt is
        unknown/already resolved, or has already exceeded the 30-second window,
        the action is not executed. An expired prompt is cancelled and recorded
        as a timeout (Req 6.5).

        Args:
            prompt_id: The id returned when the prompt was raised.
            now: The current time in epoch seconds. Defaults to wall-clock time.

        Returns:
            The executor's :class:`ExecutionResult` (``SUCCESS``/``FAILURE``)
            when the action runs; a ``FAILURE`` result for an unknown prompt; or
            a ``CANCELLED`` result if the prompt had already timed out.

        **Validates: Requirements 6.3**
        """
        current = time.time() if now is None else float(now)
        prompt = self._pending.get(prompt_id)
        if prompt is None:
            return self._unknown_prompt(prompt_id)

        if self._is_expired(prompt, current):
            # The window elapsed before approval landed: cancel, never execute.
            return self._cancel(prompt, current, REASON_TIMEOUT)

        # Resolve the prompt before executing so it cannot be double-resolved.
        del self._pending[prompt_id]
        self._record(
            command_id=prompt.command.command_id,
            parameters=prompt.command.parameters,
            outcome="approved",
            reason=None,
            now=current,
        )
        return self._executor.execute(prompt.command)

    def decline(
        self, prompt_id: str, now: Optional[float] = None
    ) -> ExecutionResult:
        """Decline a pending prompt: cancel the action and record it.

        Resolves the prompt identified by ``prompt_id`` by cancelling its
        associated Risky_Action without executing it and recording the
        cancellation in the Audit_Log (Req 6.4).

        Args:
            prompt_id: The id returned when the prompt was raised.
            now: The current time in epoch seconds. Defaults to wall-clock time.

        Returns:
            A ``CANCELLED`` :class:`ExecutionResult`, or a ``FAILURE`` result
            when the prompt is unknown or already resolved.

        **Validates: Requirements 6.4**
        """
        current = time.time() if now is None else float(now)
        prompt = self._pending.get(prompt_id)
        if prompt is None:
            return self._unknown_prompt(prompt_id)
        return self._cancel(prompt, current, REASON_DECLINED)

    def check_timeouts(self, now: Optional[float] = None) -> list[ExecutionResult]:
        """Cancel and record every pending prompt past its 30-second window.

        Sweeps all pending prompts and cancels each one whose confirmation
        window has elapsed, recording a timeout for each (Req 6.5). Intended to
        be called periodically by the server; approval/decline paths also guard
        against acting on an expired prompt.

        Args:
            now: The current time in epoch seconds. Defaults to wall-clock time.

        Returns:
            A ``CANCELLED`` :class:`ExecutionResult` for each prompt that timed
            out during this sweep (empty when none expired).

        **Validates: Requirements 6.5**
        """
        current = time.time() if now is None else float(now)
        expired = [
            prompt
            for prompt in self._pending.values()
            if self._is_expired(prompt, current)
        ]
        return [self._cancel(prompt, current, REASON_TIMEOUT) for prompt in expired]

    # -- Internal helpers -----------------------------------------------------

    def _new_prompt_id(self) -> str:
        """Generate a unique, not-currently-pending prompt id."""
        prompt_id = self._id_factory()
        # Guard against an id collision with an in-flight prompt.
        while prompt_id in self._pending:
            prompt_id = self._id_factory()
        return prompt_id

    def _is_expired(self, prompt: ConfirmationPrompt, now: float) -> bool:
        """Return True if ``prompt`` has exceeded the confirmation window."""
        return now >= prompt.created_at + self._timeout_seconds

    def _cancel(
        self, prompt: ConfirmationPrompt, now: float, reason: str
    ) -> ExecutionResult:
        """Remove a prompt, record the cancellation, and return CANCELLED."""
        self._pending.pop(prompt.prompt_id, None)
        self._record(
            command_id=prompt.command.command_id,
            parameters=prompt.command.parameters,
            outcome="cancelled",
            reason=reason,
            now=now,
        )
        detail = (
            "Risky action cancelled: no response within the confirmation window."
            if reason == REASON_TIMEOUT
            else "Risky action cancelled: the user declined the confirmation."
        )
        return ExecutionResult(
            status=CommandStatus.CANCELLED,
            command_id=prompt.command.command_id,
            detail=detail,
        )

    def _unknown_prompt(self, prompt_id: str) -> ExecutionResult:
        """Return a FAILURE result for an unknown/already-resolved prompt."""
        return ExecutionResult(
            status=CommandStatus.FAILURE,
            detail=f"Unknown or already-resolved confirmation prompt: {prompt_id!r}",
        )

    def _record(
        self,
        command_id: str,
        parameters: dict,
        outcome: str,
        reason: Optional[str],
        now: float,
    ) -> None:
        """Record a confirmation resolution through the audit seam, if set."""
        if self._audit_sink is None:
            return
        self._audit_sink(
            AuditEntry(
                timestamp=_to_iso8601(now),
                event_type=EVENT_CONFIRMATION,
                command_id=command_id,
                parameters=dict(parameters),
                outcome=outcome,
                reason=reason,
            )
        )
