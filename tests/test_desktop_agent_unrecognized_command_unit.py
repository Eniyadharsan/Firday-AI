"""Unit tests for Intent_Parser unrecognized-command handling.

These example tests verify that the Intent_Parser
(``friday/desktop_agent/intent_parser.py``) returns an ``unrecognized-command``
status whenever it cannot map the natural-language input to any
Registered_Command in the Command_Registry allow-list (Req 5.2).

There are three distinct ways "no candidate" arises, all of which must yield
``UNRECOGNIZED``:
    1. The candidate engine proposes nothing at all (empty list).
    2. Every proposed candidate references a command_id that is absent from the
       Command_Registry allow-list.
    3. Every proposed candidate references a real command but supplies
       parameters that fail schema validation (so none survive as a valid
       Structured_Command).

The AI/LLM engine seam (:class:`CandidateEngine`) is replaced by a small
deterministic fake so the test exercises only the parser's own mapping logic
without invoking a real model, mirroring the recording-fake approach used in
``tests/_adapter_fakes.py``.

Validates: Requirements 5.2
"""

from __future__ import annotations

from friday.desktop_agent.intent_parser import (
    CandidateMapping,
    IntentParser,
    parse_intent,
)
from friday.desktop_agent.models import CommandStatus, IntentResult


class FakeCandidateEngine:
    """Deterministic stand-in for the ``CandidateEngine`` LLM seam.

    Returns a pre-seeded list of candidate mappings regardless of the input
    text, so tests can drive the parser's ranking/validation logic without a
    real AI engine.
    """

    def __init__(self, candidates: list[CandidateMapping]) -> None:
        self._candidates = candidates
        self.calls: list[str] = []

    def propose(self, text: str) -> list[CandidateMapping]:
        self.calls.append(text)
        return list(self._candidates)


def test_unrecognized_when_engine_proposes_no_candidates() -> None:
    """No candidates at all yields an unrecognized-command status.

    Validates: Requirements 5.2
    """
    engine = FakeCandidateEngine([])

    result = parse_intent("do something inscrutable", engine)

    assert isinstance(result, IntentResult)
    assert result.status is CommandStatus.UNRECOGNIZED
    assert result.status.value == "unrecognized-command"
    assert result.command is None
    assert result.candidates == []
    # The parser consulted the engine for the input text.
    assert engine.calls == ["do something inscrutable"]


def test_unrecognized_when_candidate_not_in_registry() -> None:
    """Candidates that reference no Registered_Command yield unrecognized.

    Validates: Requirements 5.2
    """
    engine = FakeCandidateEngine(
        [
            CandidateMapping(
                command_id="format_hard_drive",
                parameters={"target": "C:"},
                confidence=0.99,
            ),
            CandidateMapping(
                command_id="unlock_pc",
                parameters={},
                confidence=0.80,
            ),
        ]
    )

    result = IntentParser(engine).parse_intent("erase everything")

    assert result.status is CommandStatus.UNRECOGNIZED
    assert result.command is None
    assert result.candidates == []


def test_unrecognized_when_all_candidates_fail_validation() -> None:
    """Real commands with invalid parameters leave no valid candidate.

    ``launch_app`` requires a non-empty ``app_name`` string; omitting it means
    the only proposed candidate fails schema validation and is dropped, so the
    parser finds no candidate and returns unrecognized-command.

    Validates: Requirements 5.2
    """
    engine = FakeCandidateEngine(
        [
            CandidateMapping(
                command_id="launch_app",
                parameters={},  # missing required "app_name"
                confidence=0.95,
            ),
        ]
    )

    result = IntentParser(engine).parse_intent("open the thing")

    assert result.status is CommandStatus.UNRECOGNIZED
    assert result.command is None
    assert result.candidates == []
