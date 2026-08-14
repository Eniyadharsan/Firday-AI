"""Authorization Manager for the FRIDAY Desktop Agent.

Holds the ``User_Authorization`` state and its granted scope, and provides the
gate that blocks command execution while authorization is absent. Every
authorization grant and revocation is recorded via an audit seam so the
Desktop_Agent keeps a complete local record of consent changes.

Design reference: design.md, "Desktop_Agent components" -> "Authorization
Manager".

Behavior summary:
    * ``require_authorization()`` blocks execution while authorization is
      absent, returning an ``authorization-required`` status (Req 2.1, 2.2).
    * The manager tracks the granted scope so callers can enforce least
      privilege and request only the permissions required by the
      Registered_Commands (Req 2.3).
    * ``grant(scope, now)`` records the authorization event, its scope, and its
      timestamp (Req 2.4).
    * ``revoke(now)`` immediately stops command acceptance, well within the
      1-second bound (Req 2.5).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from friday.desktop_agent.models import (
    AuditEntry,
    CommandStatus,
    ExecutionResult,
)

# Seam for recording audit events. The Audit_Log (implemented separately)
# provides an ``append(entry)`` method whose reference can be passed directly
# as this callback, or tests may pass a simple collecting fake.
AuditSink = Callable[[AuditEntry], None]


def _to_iso8601(epoch_seconds: float) -> str:
    """Convert epoch seconds to an ISO 8601 UTC timestamp string.

    The ``now`` values used across the Desktop_Agent are epoch seconds
    (matching ``SessionToken`` and ``ConfirmationPrompt``), while
    ``AuditEntry.timestamp`` is an ISO 8601 string.
    """

    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


class AuthorizationManager:
    """Holds ``User_Authorization`` state/scope and gates command execution.

    The manager starts unauthorized: on first start the Desktop_Agent requires
    explicit User_Authorization before executing any command (Req 2.1). While
    authorization is absent (or after it has been revoked), the gate declines
    every command execution request with an ``authorization-required`` status
    (Req 2.2). Grants and revocations are recorded through the audit seam
    (Req 2.4).

    Args:
        audit_sink: Optional callback invoked with an :class:`AuditEntry` for
            every grant and revoke. Pass the Audit_Log's ``append`` method to
            persist events, or omit it to disable recording (e.g., in unit
            tests that inspect the returned entry directly).
    """

    def __init__(self, audit_sink: Optional[AuditSink] = None) -> None:
        self._audit_sink = audit_sink
        self._authorized: bool = False
        self._scope: frozenset[str] = frozenset()
        self._granted_at: Optional[float] = None
        self._revoked_at: Optional[float] = None

    @property
    def is_authorized(self) -> bool:
        """Whether User_Authorization is currently present.

        Because :meth:`revoke` flips this synchronously, the gate reflects a
        revocation immediately (Req 2.5).
        """

        return self._authorized

    @property
    def scope(self) -> frozenset[str]:
        """The set of permissions granted by the current authorization.

        Empty while unauthorized. Supports least-privilege enforcement so the
        agent requests only the permissions required by the
        Registered_Commands (Req 2.3).
        """

        return self._scope

    @property
    def granted_at(self) -> Optional[float]:
        """Epoch seconds when the current authorization was granted, if any."""

        return self._granted_at

    @property
    def revoked_at(self) -> Optional[float]:
        """Epoch seconds of the most recent revocation, if any."""

        return self._revoked_at

    def has_scope(self, permission: str) -> bool:
        """Return True if ``permission`` is within the current granted scope.

        Enables callers to enforce least privilege by checking that a command's
        required permission was actually consented to (Req 2.3). Returns False
        while unauthorized.
        """

        return self._authorized and permission in self._scope

    def require_authorization(self) -> Optional[ExecutionResult]:
        """Gate that blocks execution while authorization is absent.

        Returns ``None`` when authorization is present, allowing the request to
        proceed through the rest of the enforcement gauntlet. Otherwise returns
        an :class:`ExecutionResult` with an ``authorization-required`` status so
        the caller declines the command (Req 2.1, 2.2).
        """

        if self._authorized:
            return None
        return ExecutionResult(
            status=CommandStatus.AUTHORIZATION_REQUIRED,
            detail="User_Authorization is required before executing commands.",
        )

    def grant(self, scope: Iterable[str], now: float) -> AuditEntry:
        """Grant User_Authorization for ``scope`` and record the event.

        Records the authorization event, its scope, and its timestamp in the
        Audit_Log via the audit seam (Req 2.4).

        Args:
            scope: The permissions the user consents to. Normalized to a
                frozenset of strings.
            now: The grant time in epoch seconds.

        Returns:
            The :class:`AuditEntry` recorded for this grant.
        """

        self._scope = frozenset(scope)
        self._authorized = True
        self._granted_at = now
        self._revoked_at = None

        entry = AuditEntry(
            timestamp=_to_iso8601(now),
            event_type="authorize",
            parameters={"scope": sorted(self._scope)},
            outcome="granted",
        )
        self._emit(entry)
        return entry

    def revoke(self, now: float) -> AuditEntry:
        """Revoke User_Authorization and stop accepting commands immediately.

        Flips the authorization state synchronously so subsequent
        :meth:`require_authorization` calls decline execution, satisfying the
        within-1-second bound (Req 2.5). Records the revocation event and its
        timestamp via the audit seam.

        Args:
            now: The revocation time in epoch seconds.

        Returns:
            The :class:`AuditEntry` recorded for this revocation.
        """

        revoked_scope = sorted(self._scope)
        self._authorized = False
        self._scope = frozenset()
        self._revoked_at = now

        entry = AuditEntry(
            timestamp=_to_iso8601(now),
            event_type="revoke",
            parameters={"scope": revoked_scope},
            outcome="revoked",
        )
        self._emit(entry)
        return entry

    def _emit(self, entry: AuditEntry) -> None:
        """Send an audit entry to the configured sink, if any."""

        if self._audit_sink is not None:
            self._audit_sink(entry)
