# Feature: friday-desktop-agent, Property 12: Parser output invariants
"""Property-based tests for the Intent_Parser output invariants.

Property 12: Parser output invariants
For any Structured_Command produced by the Intent_Parser, the command SHALL
reference an existing Registered_Command with parameters that pass validation,
and SHALL include a confidence value in the inclusive range 0.0 to 1.0.

Validates: Requirements 5.1, 5.5

The Intent_Parser delegates candidate generation to a mockable
``CandidateEngine`` seam (the LLM/AI engine seam). These tests inject a fake
engine that returns arbitrary candidate mappings -- including candidates that
reference commands absent from the registry, candidates with schema-violating
parameters, and candidates whose confidence lies outside ``[0.0, 1.0]``. The
property then asserts that every ``StructuredCommand`` the parser actually
produces (whether the single recognized command or any candidate listed in an
ambiguous result) satisfies the output invariants.
"""

from __future__ import annotations

import string
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.intent_parser import (
    CandidateMapping,
    IntentParser,
    parse_intent,
)
from friday.desktop_agent.models import CommandStatus, RegisteredCommand, StructuredCommand
from friday.desktop_agent.registry import all_commands, lookup
from friday.desktop_agent.validator import validate

# The full allow-list under test.
_ALL_COMMANDS: list[RegisteredCommand] = list(all_commands())
_REGISTERED_IDS: frozenset[str] = frozenset(cmd.command_id for cmd in _ALL_COMMANDS)

# A safe alphabet of non-whitespace characters. Non-empty strings drawn from
# this alphabet always satisfy the validator's required-non-empty check.
_SAFE_ALPHABET = string.ascii_letters + string.digits


class _FakeCandidateEngine:
    """A fake CandidateEngine that returns a fixed candidate list.

    Stands in for the real LLM/AI engine seam so the parser's filtering,
    clamping, ranking, and ambiguity logic can be exercised deterministically
    without invoking a real model.
    """

    def __init__(self, candidates: list[CandidateMapping]) -> None:
        self._candidates = candidates

    def propose(self, text: str) -> list[CandidateMapping]:
        return list(self._candidates)


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
def _valid_parameters(draw: st.DrawFn, command: RegisteredCommand) -> dict[str, Any]:
    """Build a parameter map that satisfies ``command``'s schema."""
    schema = command.parameters or {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    params: dict[str, Any] = {}
    for name, prop_schema in properties.items():
        include = name in required or draw(st.booleans())
        if include:
            params[name] = draw(_valid_value(prop_schema))
    for name in required:
        if name not in params:
            params[name] = draw(_valid_value(properties[name]))
    return params


# Confidence values that may fall outside [0.0, 1.0] so we exercise the
# parser's clamping guarantee (Req 5.5).
_any_confidence = st.floats(
    min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False
)


@st.composite
def _valid_candidate(draw: st.DrawFn) -> CandidateMapping:
    """A candidate referencing a real command with schema-valid parameters.

    Confidence may lie outside [0.0, 1.0] to verify the parser clamps it.
    """
    command = draw(st.sampled_from(_ALL_COMMANDS))
    params = draw(_valid_parameters(command))
    return CandidateMapping(
        command_id=command.command_id,
        parameters=params,
        confidence=draw(_any_confidence),
    )


@st.composite
def _absent_candidate(draw: st.DrawFn) -> CandidateMapping:
    """A candidate referencing an identifier absent from the registry."""
    command_id = draw(
        st.text(alphabet=_SAFE_ALPHABET, min_size=0, max_size=20).filter(
            lambda s: s not in _REGISTERED_IDS
        )
    )
    params = draw(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=8),
            values=st.text(max_size=16),
            max_size=3,
        )
    )
    return CandidateMapping(
        command_id=command_id, parameters=params, confidence=draw(_any_confidence)
    )


@st.composite
def _invalid_params_candidate(draw: st.DrawFn) -> CandidateMapping:
    """A candidate referencing a real command but with invalid parameters.

    Drops a required field so the candidate fails schema validation and must
    be filtered out by the parser.
    """
    commands_with_required = [
        c for c in _ALL_COMMANDS if (c.parameters or {}).get("required")
    ]
    command = draw(st.sampled_from(commands_with_required))
    required = (command.parameters or {}).get("required", [])
    drop = draw(st.sampled_from(required))
    params = draw(_valid_parameters(command))
    params.pop(drop, None)
    return CandidateMapping(
        command_id=command.command_id,
        parameters=params,
        confidence=draw(_any_confidence),
    )


# A mixed pool of candidate kinds so a single proposed list can contain valid,
# absent, and schema-violating candidates simultaneously.
_any_candidate = st.one_of(
    _valid_candidate(), _absent_candidate(), _invalid_params_candidate()
)


def _assert_output_invariants(command: StructuredCommand) -> None:
    """Assert a produced Structured_Command satisfies Property 12.

    The command references an existing Registered_Command, its parameters pass
    validation, and its confidence lies in the inclusive range [0.0, 1.0].
    """
    registered = lookup(command.command_id)
    assert registered is not None, (
        f"produced command references absent id {command.command_id!r}"
    )
    assert validate(registered, command.parameters).valid, (
        f"produced command {command.command_id!r} has invalid parameters"
    )
    assert 0.0 <= command.confidence <= 1.0, (
        f"confidence {command.confidence} outside [0.0, 1.0]"
    )


@settings(max_examples=200)
@given(candidates=st.lists(_any_candidate, max_size=6), text=st.text(max_size=40))
def test_parser_output_invariants(
    candidates: list[CandidateMapping], text: str
) -> None:
    """Every Structured_Command the parser produces satisfies the invariants.

    For any set of candidate mappings (valid, absent, or schema-violating) and
    any input text, whatever Structured_Command the Intent_Parser emits -- the
    single recognized command or any candidate in an ambiguous result --
    references an existing Registered_Command with valid parameters and a
    confidence in [0.0, 1.0] (Req 5.1, 5.5).
    """
    result = parse_intent(text, _FakeCandidateEngine(candidates))

    if result.status == CommandStatus.SUCCESS:
        assert result.command is not None
        _assert_output_invariants(result.command)
    elif result.status == CommandStatus.AMBIGUOUS:
        assert result.candidates
        for candidate in result.candidates:
            _assert_output_invariants(candidate)
    else:
        # UNRECOGNIZED: the parser produced no Structured_Command, so there is
        # nothing to check against the output invariants.
        assert result.status == CommandStatus.UNRECOGNIZED
        assert result.command is None


@settings(max_examples=200)
@given(candidate=_valid_candidate())
def test_single_valid_candidate_is_recognized_and_clamped(
    candidate: CandidateMapping,
) -> None:
    """A lone valid candidate is recognized with a clamped confidence.

    When exactly one valid candidate is proposed, the parser recognizes it and
    the resulting Structured_Command satisfies the output invariants -- in
    particular the confidence is clamped into [0.0, 1.0] even when the engine
    reported a value outside that range (Req 5.1, 5.5).
    """
    result = parse_intent("do it", _FakeCandidateEngine([candidate]))

    assert result.status == CommandStatus.SUCCESS
    assert result.command is not None
    _assert_output_invariants(result.command)
    # Confidence is clamped to the valid range.
    assert result.command.confidence == max(0.0, min(1.0, candidate.confidence))


@settings(max_examples=200)
@given(candidates=st.lists(st.one_of(_absent_candidate(), _invalid_params_candidate()), max_size=6))
def test_only_invalid_candidates_yield_unrecognized(
    candidates: list[CandidateMapping],
) -> None:
    """When no candidate survives filtering, the parser returns UNRECOGNIZED.

    Candidates that reference absent commands or carry schema-violating
    parameters can never become a Structured_Command, so the parser emits no
    command and reports ``unrecognized-command`` (Req 5.1, 5.2).
    """
    result = parse_intent("nonsense", _FakeCandidateEngine(candidates))

    assert result.status == CommandStatus.UNRECOGNIZED
    assert result.command is None
    assert result.candidates == []
