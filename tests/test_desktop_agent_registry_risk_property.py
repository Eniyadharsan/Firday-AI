"""Property-based tests for the Command_Registry risk classification invariant.

Property 7: Risk classification invariant
- For any command in the Command_Registry, the command SHALL carry a risk
  classification that is exactly one of standard or risky
  (RiskClass.STANDARD or RiskClass.RISKY).

Validates: Requirements 3.5
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.models import RegisteredCommand, RiskClass
from friday.desktop_agent.registry import all_commands

# The exhaustive set of valid risk classifications per the acceptance criteria.
VALID_RISK_CLASSES = {RiskClass.STANDARD, RiskClass.RISKY}

# The full allow-list, sampled by the property test below.
_ALL_COMMANDS = list(all_commands())


# Feature: friday-desktop-agent, Property 7: Risk classification invariant
@settings(max_examples=100)
@given(command=st.sampled_from(_ALL_COMMANDS))
def test_registry_command_risk_classification_is_valid(
    command: RegisteredCommand,
) -> None:
    """Every registered command carries exactly one valid risk classification.

    Validates: Requirements 3.5
    """
    assert isinstance(command.risk_class, RiskClass)
    assert command.risk_class in VALID_RISK_CLASSES
