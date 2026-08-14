"""Property-based tests for Parameter Validator schema validation.

Property 8: Parameter schema validation
- For any Structured_Command whose parameters violate the referenced command's
  parameter schema (missing required field, out-of-bounds length, or invalid
  enum value), the Desktop_Agent SHALL decline execution and return a
  validation-error status; parameters that satisfy the schema SHALL pass
  validation.

Validates: Requirements 3.6
"""

from __future__ import annotations

import string
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.models import CommandStatus, RegisteredCommand
from friday.desktop_agent.registry import all_commands
from friday.desktop_agent.validator import validate

# The full allow-list under test.
_ALL_COMMANDS = list(all_commands())

# A safe alphabet of non-whitespace characters. Non-empty strings drawn from
# this alphabet always satisfy the validator's required-non-empty check.
_SAFE_ALPHABET = string.ascii_letters + string.digits

# Commands that declare at least one required parameter (candidates for the
# "missing required field" violation).
_COMMANDS_WITH_REQUIRED: list[RegisteredCommand] = [
    command
    for command in _ALL_COMMANDS
    if (command.parameters or {}).get("required")
]

# (command, field_name) pairs for string properties that declare a maxLength
# bound (candidates for the "out-of-bounds length" violation).
_STRING_MAXLEN_FIELDS: list[tuple[RegisteredCommand, str]] = [
    (command, name)
    for command in _ALL_COMMANDS
    for name, prop in (command.parameters or {}).get("properties", {}).items()
    if prop.get("type") == "string" and prop.get("maxLength") is not None
]

# (command, field_name, enum_values) triples for enum properties (candidates
# for the "invalid enum value" violation).
_ENUM_FIELDS: list[tuple[RegisteredCommand, str, list[Any]]] = [
    (command, name, prop["enum"])
    for command in _ALL_COMMANDS
    for name, prop in (command.parameters or {}).get("properties", {}).items()
    if prop.get("enum") is not None
]


def _valid_value(prop_schema: dict[str, Any]) -> st.SearchStrategy[Any]:
    """A strategy producing a value that satisfies ``prop_schema``."""
    enum_values = prop_schema.get("enum")
    if enum_values is not None:
        return st.sampled_from(enum_values)

    prop_type = prop_schema.get("type")
    if prop_type == "string":
        min_length = max(prop_schema.get("minLength", 1), 1)
        max_length = prop_schema.get("maxLength", min_length + 16)
        return st.text(
            alphabet=_SAFE_ALPHABET,
            min_size=min_length,
            max_size=min(max_length, min_length + 16),
        )
    if prop_type == "integer":
        minimum = prop_schema.get("minimum", 0)
        maximum = prop_schema.get("maximum", 100)
        return st.integers(min_value=minimum, max_value=maximum)
    if prop_type == "number":
        minimum = prop_schema.get("minimum", 0)
        maximum = prop_schema.get("maximum", 100)
        return st.floats(
            min_value=minimum,
            max_value=maximum,
            allow_nan=False,
            allow_infinity=False,
        )
    return st.just("x")


@st.composite
def _valid_parameters(
    draw: st.DrawFn, command: RegisteredCommand
) -> dict[str, Any]:
    """Build a parameter map that satisfies ``command``'s schema."""
    schema = command.parameters or {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    params: dict[str, Any] = {}
    for name, prop_schema in properties.items():
        include = name in required or draw(st.booleans())
        if include:
            params[name] = draw(_valid_value(prop_schema))
    # Guarantee all required fields are present.
    for name in required:
        if name not in params:
            params[name] = draw(_valid_value(properties[name]))
    return params


@st.composite
def _valid_case(draw: st.DrawFn) -> tuple[RegisteredCommand, dict[str, Any], bool]:
    """A (command, params, expected_valid=True) case satisfying the schema."""
    command = draw(st.sampled_from(_ALL_COMMANDS))
    params = draw(_valid_parameters(command))
    return command, params, True


@st.composite
def _invalid_case(
    draw: st.DrawFn,
) -> tuple[RegisteredCommand, dict[str, Any], bool]:
    """A (command, params, expected_valid=False) case violating the schema.

    Chooses one of the three named violation kinds: a missing required field,
    an out-of-bounds string length, or an invalid enum value.
    """
    kinds = []
    if _COMMANDS_WITH_REQUIRED:
        kinds.append("missing")
    if _STRING_MAXLEN_FIELDS:
        kinds.append("length")
    if _ENUM_FIELDS:
        kinds.append("enum")

    kind = draw(st.sampled_from(kinds))

    if kind == "missing":
        command = draw(st.sampled_from(_COMMANDS_WITH_REQUIRED))
        params = draw(_valid_parameters(command))
        required = (command.parameters or {}).get("required", [])
        drop = draw(st.sampled_from(required))
        params.pop(drop, None)
        return command, params, False

    if kind == "length":
        command, field_name = draw(st.sampled_from(_STRING_MAXLEN_FIELDS))
        params = draw(_valid_parameters(command))
        max_length = command.parameters["properties"][field_name]["maxLength"]
        # Build the overlong string directly: generating an 8k+ character
        # string via st.text exceeds Hypothesis's buffer size.
        excess = draw(st.integers(min_value=1, max_value=10))
        params[field_name] = "a" * (max_length + excess)
        return command, params, False

    # kind == "enum"
    command, field_name, enum_values = draw(st.sampled_from(_ENUM_FIELDS))
    params = draw(_valid_parameters(command))
    bad_value = draw(
        st.text(alphabet=_SAFE_ALPHABET, min_size=1, max_size=12).filter(
            lambda value: value not in enum_values
        )
    )
    params[field_name] = bad_value
    return command, params, False


# Feature: friday-desktop-agent, Property 8: Parameter schema validation
@settings(max_examples=200)
@given(case=st.one_of(_valid_case(), _invalid_case()))
def test_parameter_schema_validation(
    case: tuple[RegisteredCommand, dict[str, Any], bool],
) -> None:
    """Schema-violating parameters are declined; conforming ones pass.

    Validates: Requirements 3.6
    """
    command, parameters, expected_valid = case

    result = validate(command, parameters)

    assert result.valid is expected_valid
    if expected_valid:
        assert result.status is None
        assert result.error is None
    else:
        # A violation yields a validation-error status so the enforcement
        # gauntlet declines execution (Req 3.6).
        assert result.status == CommandStatus.VALIDATION_ERROR
        assert result.error
