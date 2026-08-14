"""Property-based tests for required audit fields on every outcome.

Property 17: Every outcome is audited with required fields
- For any command that is executed or declined, the Audit_Log SHALL contain an
  entry recording the command identifier, the outcome or decline reason, and a
  timestamp (plus parameters for executed commands).

Validates: Requirements 7.1, 7.3
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.audit import EVENT_DECLINE, EVENT_EXECUTE, AuditLog

# Command identifiers resemble the Command_Registry allow-list ids.
_command_ids = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=20,
)

# Free-form outcome/reason strings, including empty and whitespace values.
_outcomes = st.text(min_size=0, max_size=40)
_reasons = st.text(min_size=1, max_size=40)

# Parameter maps with simple JSON-serializable scalar values.
_parameters = st.dictionaries(
    keys=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=1,
        max_size=10,
    ),
    values=st.one_of(
        st.text(max_size=20),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
    ),
    max_size=5,
)


def _fresh_log(tmp_path: Path) -> AuditLog:
    """Create an AuditLog backed by a unique temporary directory."""
    return AuditLog(data_dir=tmp_path)


# Feature: friday-desktop-agent, Property 17: Every outcome is audited with required fields
@settings(max_examples=100)
@given(
    command_id=_command_ids,
    parameters=_parameters,
    outcome=_outcomes,
)
def test_executed_command_is_audited_with_required_fields(
    command_id: str,
    parameters: dict,
    outcome: str,
    tmp_path_factory,
) -> None:
    """Executing a command records id, parameters, outcome, and timestamp.

    Validates: Requirements 7.1
    """
    log = _fresh_log(tmp_path_factory.mktemp("audit_exec"))

    log.record_execution(command_id=command_id, parameters=parameters, outcome=outcome)

    entries = log.read_all()
    assert len(entries) == 1
    entry = entries[0]

    # Required fields for an executed command (Req 7.1).
    assert entry.event_type == EVENT_EXECUTE
    assert entry.command_id == command_id
    assert entry.outcome == outcome
    assert entry.parameters == parameters
    assert entry.timestamp  # non-empty ISO-8601 timestamp


# Feature: friday-desktop-agent, Property 17: Every outcome is audited with required fields
@settings(max_examples=100)
@given(
    command_id=st.one_of(st.none(), _command_ids),
    reason=_reasons,
)
def test_declined_command_is_audited_with_required_fields(
    command_id,
    reason: str,
    tmp_path_factory,
) -> None:
    """Declining a command records the command, decline reason, and timestamp.

    Validates: Requirements 7.3
    """
    log = _fresh_log(tmp_path_factory.mktemp("audit_decline"))

    log.record_decline(command_id=command_id, reason=reason)

    entries = log.read_all()
    assert len(entries) == 1
    entry = entries[0]

    # Required fields for a declined command (Req 7.3).
    assert entry.event_type == EVENT_DECLINE
    assert entry.command_id == command_id
    assert entry.reason == reason
    assert entry.timestamp  # non-empty ISO-8601 timestamp
