"""Property-based tests for the append-only Audit_Log.

Property 18: Audit log is append-only
- For any sequence of audit appends, every previously recorded entry remains
  present, unmodified, and in its original order. In other words, the log is a
  strictly growing, prefix-preserving sequence: after appending entry N, the
  first N-1 entries read back exactly as they did before, and the whole log
  reads back as the entries in the exact order they were appended.

Validates: Requirements 7.2
"""

from __future__ import annotations

import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.audit import AuditLog
from friday.desktop_agent.models import AuditEntry

# Recognized audit event types, mirroring friday/desktop_agent/audit.py.
_EVENT_TYPES = [
    "execute",
    "decline",
    "authorize",
    "revoke",
    "kill_switch",
    "capture",
    "vision_failure",
    "lockout",
]

# JSON-round-trippable scalar values for recorded parameters. Floats are
# excluded to avoid NaN/inf which do not round-trip through strict JSON.
_param_values = st.one_of(
    st.text(max_size=20),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.booleans(),
    st.none(),
)

# A strategy that builds a single, JSON-serializable AuditEntry.
_audit_entries = st.builds(
    AuditEntry,
    timestamp=st.text(min_size=1, max_size=25),
    event_type=st.sampled_from(_EVENT_TYPES),
    command_id=st.one_of(st.none(), st.text(max_size=20)),
    parameters=st.dictionaries(st.text(max_size=10), _param_values, max_size=4),
    outcome=st.one_of(st.none(), st.text(max_size=20)),
    reason=st.one_of(st.none(), st.text(max_size=20)),
)


# Feature: friday-desktop-agent, Property 18: Audit log is append-only
@settings(max_examples=100)
@given(entries=st.lists(_audit_entries, max_size=25))
def test_audit_log_is_append_only(entries: list[AuditEntry]) -> None:
    """Appending never mutates, removes, or reorders prior entries.

    For every prefix of the append sequence, the log reads back exactly that
    prefix in order, proving the log is a growing, prefix-preserving sequence.

    Validates: Requirements 7.2
    """
    # Fresh temp directory per example so each run starts from an empty log.
    with tempfile.TemporaryDirectory() as tmp:
        log = AuditLog(data_dir=tmp)

        appended_so_far: list[AuditEntry] = []
        for entry in entries:
            log.append(entry)
            appended_so_far.append(entry)

            # The log read back must be exactly the entries appended so far,
            # in the exact order they were appended. This simultaneously
            # asserts: prior entries are still present, unmodified, and their
            # order is preserved (nothing before the new entry shifted).
            read_back = log.read_all()
            assert read_back == appended_so_far

        # Final full-log check: the complete read equals the full input order.
        assert log.read_all() == entries
