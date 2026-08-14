# Feature: friday-desktop-agent, Property 19: History is reverse chronological
"""Property-based test for the Desktop_Agent Audit_Log history view.

Property 19: History is reverse chronological
For any set of audit entries, the history view SHALL return them ordered by
timestamp from newest to oldest.

Validates: Requirements 7.5
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.audit import ISO_TIMESTAMP_FORMAT, AuditLog
from friday.desktop_agent.models import AuditEntry

# Epoch-second range kept finite/positive so ISO conversion stays well-behaved.
# Roughly year 2001..2035.
_epoch_seconds = st.integers(min_value=1_000_000_000, max_value=2_000_000_000)

# Event types the Audit_Log records (mirrors audit.py constants).
_event_types = st.sampled_from(
    [
        "execute",
        "decline",
        "authorize",
        "revoke",
        "kill_switch",
        "capture",
        "vision_failure",
        "lockout",
    ]
)


def _iso(epoch: int) -> str:
    """Format an epoch second as the audit log's ISO-8601 UTC timestamp."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(ISO_TIMESTAMP_FORMAT)


@st.composite
def _audit_entries(draw: st.DrawFn) -> list[AuditEntry]:
    """Generate a set of audit entries with varied timestamps.

    Timestamps are drawn independently so the append order deliberately does
    not match chronological order; the history view is responsible for the
    newest-first ordering.
    """
    epochs = draw(st.lists(_epoch_seconds, min_size=0, max_size=25))
    entries: list[AuditEntry] = []
    for index, epoch in enumerate(epochs):
        event_type = draw(_event_types)
        entries.append(
            AuditEntry(
                timestamp=_iso(epoch),
                event_type=event_type,
                command_id=f"cmd-{index}",
                reason=None,
            )
        )
    return entries


@settings(max_examples=200)
@given(entries=_audit_entries())
def test_history_is_reverse_chronological(entries: list[AuditEntry]) -> None:
    """read_reverse_chronological returns entries newest-first (Req 7.5).

    For any set of appended audit entries, the history view returns exactly
    those entries ordered by timestamp from newest to oldest.
    """
    with tempfile.TemporaryDirectory() as data_dir:
        log = AuditLog(data_dir=data_dir)
        for entry in entries:
            log.append(entry)

        history = log.read_reverse_chronological()

        # Every appended entry is present, and nothing extra is introduced.
        # Compare as multisets using a total-order key (timestamp + command_id)
        # so entries sharing a timestamp still compare deterministically.
        def _key(e: AuditEntry) -> tuple[str, str]:
            return (e.timestamp, e.command_id or "")

        assert len(history) == len(entries)
        assert sorted(history, key=_key) == sorted(entries, key=_key)

        # Timestamps are non-increasing: each entry is at least as new as the
        # one that follows it (newest to oldest).
        timestamps = [e.timestamp for e in history]
        assert timestamps == sorted(timestamps, reverse=True)
