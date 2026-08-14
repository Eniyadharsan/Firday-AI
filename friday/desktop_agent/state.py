"""Agent State Machine for the FRIDAY Desktop Agent.

Models the Desktop_Agent's operating state as one of three values -
``enabled``, ``observing``, or ``disabled`` - and enforces the Kill_Switch
disabled behavior. Every state transition is published to a UI seam so the
Active_Indicator can reflect the current state within the required 1-second
bound, and Kill_Switch activations are recorded through an audit seam.

Design reference: design.md, "Desktop_Agent components" -> "Agent State
Machine".

Behavior summary:
    * The machine tracks the current :class:`AgentState` and only permits
      well-defined transitions between ``enabled`` and ``observing`` while
      allowing the Kill_Switch to force ``disabled`` from any state.
    * Each transition invokes the state-publisher seam synchronously so the
      Active_Indicator updates within 1 second of the transition (Req 9.4).
    * ``activate_kill_switch(now)`` transitions to ``disabled`` and records the
      activation and its timestamp via the audit seam (Req 8.4). Because the
      transition is synchronous, the agent stops accepting new command
      execution requests well within the 1-second bound (Req 8.2).
    * ``require_enabled()`` gates command execution: while ``disabled`` it
      returns a ``disabled`` status so the caller declines every command
      execution request (Req 8.5).

**Validates: Requirements 8.2, 8.4, 8.5, 9.4**
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from friday.desktop_agent.models import (
    AgentState,
    AuditEntry,
    CommandStatus,
    ExecutionResult,
)

# Seam for recording audit events. The Audit_Log provides an ``append(entry)``
# method whose reference can be passed directly as this callback, or tests may
# pass a simple collecting fake.
AuditSink = Callable[[AuditEntry], None]

# Seam for publishing state transitions to the FRIDAY_UI so the
# Active_Indicator can reflect the new state. Invoked synchronously on every
# transition to satisfy the within-1-second update bound (Req 9.4).
StatePublisher = Callable[[AgentState], None]


def _to_iso8601(epoch_seconds: float) -> str:
    """Convert epoch seconds to an ISO 8601 UTC timestamp string.

    The ``now`` values used across the Desktop_Agent are epoch seconds
    (matching ``SessionToken`` and ``ConfirmationPrompt``), while
    ``AuditEntry.timestamp`` is an ISO 8601 string.
    """

    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class StateTransition:
    """An immutable record of a single state transition.

    Returned by the transition methods so callers can observe exactly what
    changed and when.

    Attributes:
        from_state: The state the machine was in before the transition.
        to_state: The state the machine is in after the transition.
        at: The transition time in epoch seconds.
    """

    from_state: AgentState
    to_state: AgentState
    at: float


class AgentStateMachine:
    """Tracks the Desktop_Agent state and enforces Kill_Switch behavior.

    The machine drives the Active_Indicator through the ``state_publisher``
    seam and gates command execution while disabled. It starts in
    ``enabled`` by default, representing a running, non-kill-switched agent;
    callers may override the initial state (for example, to start disabled
    until User_Authorization is granted).

    Args:
        audit_sink: Optional callback invoked with an :class:`AuditEntry` for
            every Kill_Switch activation. Pass the Audit_Log's ``append``
            method to persist events, or omit it to disable recording.
        state_publisher: Optional callback invoked with the new
            :class:`AgentState` on every transition so the Active_Indicator
            updates within 1 second (Req 9.4).
        initial_state: The state the machine starts in. Defaults to
            :attr:`AgentState.ENABLED`.
    """

    def __init__(
        self,
        audit_sink: Optional[AuditSink] = None,
        state_publisher: Optional[StatePublisher] = None,
        initial_state: AgentState = AgentState.ENABLED,
    ) -> None:
        self._audit_sink = audit_sink
        self._state_publisher = state_publisher
        self._state: AgentState = initial_state
        self._last_transition_at: Optional[float] = None

    # -- State inspection -----------------------------------------------------

    @property
    def state(self) -> AgentState:
        """The current :class:`AgentState`."""

        return self._state

    @property
    def is_enabled(self) -> bool:
        """True while the agent is enabled (accepting commands, not observing)."""

        return self._state is AgentState.ENABLED

    @property
    def is_observing(self) -> bool:
        """True while the Screen_Observer is capturing (observing state)."""

        return self._state is AgentState.OBSERVING

    @property
    def is_disabled(self) -> bool:
        """True while the agent is disabled by the Kill_Switch (Req 8.5)."""

        return self._state is AgentState.DISABLED

    @property
    def last_transition_at(self) -> Optional[float]:
        """Epoch seconds of the most recent transition, if any."""

        return self._last_transition_at

    # -- Execution gate -------------------------------------------------------

    def require_enabled(self) -> Optional[ExecutionResult]:
        """Gate that declines execution while the agent is disabled.

        Returns ``None`` when the agent is enabled or observing, allowing the
        request to proceed through the rest of the enforcement gauntlet.
        Otherwise returns an :class:`ExecutionResult` with a ``disabled``
        status so the caller declines the command (Req 8.5).
        """

        if self._state is AgentState.DISABLED:
            return ExecutionResult(
                status=CommandStatus.DISABLED,
                detail="The Desktop_Agent is disabled by the Kill_Switch.",
            )
        return None

    # -- Transitions ----------------------------------------------------------

    def enable(self, now: float) -> StateTransition:
        """Transition to the ``enabled`` state.

        Used to bring the agent back online after a Kill_Switch activation, or
        to leave the observing state. Publishes the new state so the
        Active_Indicator updates within 1 second (Req 9.4).

        Args:
            now: The transition time in epoch seconds.
        """

        return self._transition(AgentState.ENABLED, now)

    def start_observing(self, now: float) -> StateTransition:
        """Transition to the ``observing`` state.

        Only valid from the ``enabled`` state; the Screen_Observer cannot begin
        capturing while the agent is disabled by the Kill_Switch.

        Args:
            now: The transition time in epoch seconds.

        Raises:
            ValueError: If invoked while the agent is disabled.
        """

        if self._state is AgentState.DISABLED:
            raise ValueError(
                "Cannot start observing while the agent is disabled by the Kill_Switch."
            )
        return self._transition(AgentState.OBSERVING, now)

    def stop_observing(self, now: float) -> StateTransition:
        """Transition from ``observing`` back to ``enabled``.

        Args:
            now: The transition time in epoch seconds.
        """

        return self._transition(AgentState.ENABLED, now)

    def activate_kill_switch(self, now: float) -> AuditEntry:
        """Activate the Kill_Switch: disable the agent and record it.

        Transitions to the ``disabled`` state synchronously so the agent stops
        accepting new command execution requests within the 1-second bound
        (Req 8.2), publishes the new state so the Active_Indicator reflects it
        within 1 second (Req 9.4), and records the activation and its timestamp
        via the audit seam (Req 8.4).

        Args:
            now: The activation time in epoch seconds.

        Returns:
            The :class:`AuditEntry` recorded for this Kill_Switch activation.
        """

        self._transition(AgentState.DISABLED, now)

        entry = AuditEntry(
            timestamp=_to_iso8601(now),
            event_type="kill_switch",
            outcome="disabled",
        )
        self._emit_audit(entry)
        return entry

    # -- Internals ------------------------------------------------------------

    def _transition(self, to_state: AgentState, now: float) -> StateTransition:
        """Apply a state change and publish it to the Active_Indicator seam.

        The state is updated synchronously and the publisher is invoked
        immediately, guaranteeing the Active_Indicator can reflect the new
        state within 1 second of the transition (Req 9.4).
        """

        transition = StateTransition(
            from_state=self._state,
            to_state=to_state,
            at=now,
        )
        self._state = to_state
        self._last_transition_at = now
        self._publish_state(to_state)
        return transition

    def _publish_state(self, state: AgentState) -> None:
        """Publish the new state to the configured publisher seam, if any."""

        if self._state_publisher is not None:
            self._state_publisher(state)

    def _emit_audit(self, entry: AuditEntry) -> None:
        """Send an audit entry to the configured audit sink, if any."""

        if self._audit_sink is not None:
            self._audit_sink(entry)
