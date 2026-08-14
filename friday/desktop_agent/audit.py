"""Append-only local Audit_Log for the FRIDAY Desktop Agent.

The Audit_Log is a local, append-only record of everything the Desktop_Agent
does: command executions, declines, authorization grants/revocations,
kill-switch activations, screen captures, vision-provider failures, and
authentication lockouts. Entries are stored on the user's PC as JSON Lines
(one JSON object per line) so the log is trivially appendable and never
requires rewriting prior content.

Design references:
- "Audit_Log" component in design.md.
- Local-storage convention ``.friday-data/`` used across ``friday/``.

Guarantees:
- ``append(entry)`` only ever adds a new line; it never mutates or removes any
  previously written entry (Req 7.2).
- Entries are stored locally on the user's PC (Req 7.4).
- ``read_reverse_chronological()`` returns entries newest-first (Req 7.5).

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from friday.desktop_agent.models import AuditEntry

# ISO-8601 UTC timestamp format, matching ``friday/config.py``.
ISO_TIMESTAMP_FORMAT: str = "%Y-%m-%dT%H:%M:%SZ"

# Default file name for the audit log within the agent data directory.
DEFAULT_AUDIT_FILENAME: str = "audit.jsonl"

# Recognized audit event types (Req 7.1, 7.3 and related recording rules).
EVENT_EXECUTE = "execute"
EVENT_DECLINE = "decline"
EVENT_AUTHORIZE = "authorize"
EVENT_REVOKE = "revoke"
EVENT_KILL_SWITCH = "kill_switch"
EVENT_CAPTURE = "capture"
EVENT_VISION_FAILURE = "vision_failure"
EVENT_LOCKOUT = "lockout"


def _default_data_dir() -> Path:
    """Resolve the default agent data directory.

    Honors the ``FRIDAY_DATA_DIR`` environment variable when set; otherwise
    falls back to the project-local ``.friday-data`` directory, mirroring the
    existing local-storage convention.
    """
    override = os.getenv("FRIDAY_DATA_DIR")
    if override:
        return Path(override)
    # friday/desktop_agent/audit.py -> project root is three levels up.
    return Path(__file__).resolve().parent.parent.parent / ".friday-data"


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime(ISO_TIMESTAMP_FORMAT)


class AuditLog:
    """Append-only, locally-stored audit log backed by a JSON Lines file.

    The data directory is configurable via the constructor so tests can point
    the log at a temporary directory instead of the real ``.friday-data``
    location.

    Attributes:
        path: The absolute path to the backing JSON Lines file.
    """

    def __init__(
        self,
        data_dir: Optional[os.PathLike[str] | str] = None,
        filename: str = DEFAULT_AUDIT_FILENAME,
    ) -> None:
        """Create the audit log.

        Args:
            data_dir: Directory in which to store the audit file. Defaults to
                the agent data directory (``FRIDAY_DATA_DIR`` or
                ``.friday-data``). Made configurable so tests can use a temp
                directory (Req 7.4).
            filename: Name of the JSON Lines file within ``data_dir``.
        """
        self._data_dir: Path = Path(data_dir) if data_dir is not None else _default_data_dir()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path: Path = self._data_dir / filename

    @property
    def path(self) -> Path:
        """Absolute path to the backing audit file (stored locally, Req 7.4)."""
        return self._path

    # -- Core append-only API -------------------------------------------------

    def append(self, entry: AuditEntry) -> None:
        """Append a single audit entry to the log.

        Opens the backing file in append mode and writes exactly one JSON line.
        Prior entries are never read, mutated, or removed, so the log grows in a
        strictly prefix-preserving manner (Req 7.2).

        Args:
            entry: The immutable :class:`AuditEntry` to record.
        """
        line = json.dumps(asdict(entry), ensure_ascii=False, sort_keys=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read_all(self) -> list[AuditEntry]:
        """Read every audit entry in append (chronological) order.

        Returns an empty list when the log file does not yet exist. Blank lines
        are ignored so a partially-written trailing line cannot corrupt reads.
        """
        if not self._path.exists():
            return []
        entries: list[AuditEntry] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                data: dict[str, Any] = json.loads(raw)
                entries.append(AuditEntry(**data))
        return entries

    def read_reverse_chronological(self) -> list[AuditEntry]:
        """Return all audit entries ordered newest-first (Req 7.5).

        Entries are sorted by timestamp descending. For entries sharing the same
        timestamp, the most recently appended entry is returned first so ties
        still read newest-first.
        """
        entries = self.read_all()
        # ``reversed`` puts the last-appended entry first; the stable sort then
        # keeps that ordering among equal timestamps.
        return sorted(reversed(entries), key=lambda e: e.timestamp, reverse=True)

    # -- Convenience recorders for each audited event type --------------------

    def record_execution(
        self,
        command_id: str,
        parameters: dict[str, Any],
        outcome: str,
        timestamp: Optional[str] = None,
    ) -> AuditEntry:
        """Record a Registered_Command execution (Req 7.1).

        Captures the command identifier, parameters, outcome, and timestamp.
        """
        entry = AuditEntry(
            timestamp=timestamp or _now_iso(),
            event_type=EVENT_EXECUTE,
            command_id=command_id,
            parameters=dict(parameters),
            outcome=outcome,
        )
        self.append(entry)
        return entry

    def record_decline(
        self,
        command_id: Optional[str],
        reason: str,
        timestamp: Optional[str] = None,
    ) -> AuditEntry:
        """Record a declined command with its reason (Req 7.3)."""
        entry = AuditEntry(
            timestamp=timestamp or _now_iso(),
            event_type=EVENT_DECLINE,
            command_id=command_id,
            reason=reason,
        )
        self.append(entry)
        return entry

    def record_authorization(
        self,
        scope: str,
        timestamp: Optional[str] = None,
    ) -> AuditEntry:
        """Record a User_Authorization grant, its scope, and timestamp (Req 2.4)."""
        entry = AuditEntry(
            timestamp=timestamp or _now_iso(),
            event_type=EVENT_AUTHORIZE,
            outcome=scope,
        )
        self.append(entry)
        return entry

    def record_revocation(self, timestamp: Optional[str] = None) -> AuditEntry:
        """Record a User_Authorization revocation (Req 2.5)."""
        entry = AuditEntry(
            timestamp=timestamp or _now_iso(),
            event_type=EVENT_REVOKE,
        )
        self.append(entry)
        return entry

    def record_kill_switch(self, timestamp: Optional[str] = None) -> AuditEntry:
        """Record a Kill_Switch activation and its timestamp (Req 8.4)."""
        entry = AuditEntry(
            timestamp=timestamp or _now_iso(),
            event_type=EVENT_KILL_SWITCH,
        )
        self.append(entry)
        return entry

    def record_capture(self, timestamp: Optional[str] = None) -> AuditEntry:
        """Record a Screen_Observer capture event and timestamp (Req 10.8)."""
        entry = AuditEntry(
            timestamp=timestamp or _now_iso(),
            event_type=EVENT_CAPTURE,
        )
        self.append(entry)
        return entry

    def record_vision_failure(
        self,
        reason: str,
        timestamp: Optional[str] = None,
    ) -> AuditEntry:
        """Record a Vision_Provider failure (Req 10.5)."""
        entry = AuditEntry(
            timestamp=timestamp or _now_iso(),
            event_type=EVENT_VISION_FAILURE,
            reason=reason,
        )
        self.append(entry)
        return entry

    def record_lockout(
        self,
        reason: str = "too-many-invalid-tokens",
        timestamp: Optional[str] = None,
    ) -> AuditEntry:
        """Record an authentication lockout (Req 1.7)."""
        entry = AuditEntry(
            timestamp=timestamp or _now_iso(),
            event_type=EVENT_LOCKOUT,
            reason=reason,
        )
        self.append(entry)
        return entry
