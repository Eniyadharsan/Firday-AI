"""Property-based test for Intent_Parser ambiguity detection threshold.

Property 13: Ambiguity detection threshold
- For any set of candidate command mappings, the Intent_Parser SHALL return an
  ambiguous-command status listing the candidates if and only if the two
  highest confidence values differ by 0.10 or less.

The parser only ranks *valid* candidates (those referencing an existing
Registered_Command whose parameters pass schema validation). This test feeds
the parser exclusively valid candidate mappings through a deterministic fake
:class:`CandidateEngine`, then asserts the ambiguous-command status is returned
if and only if there are at least two candidates whose two highest confidence
values differ by <= 0.10. Confidence lists are generated to straddle the 0.10
boundary so both branches of the biconditional are exercised.

Validates: Requirements 5.3
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.intent_parser import (
    AMBIGUITY_THRESHOLD,
    CandidateMapping,
    IntentParser,
)
from friday.desktop_agent.models import CommandStatus

# Valid (command_id, parameters) pairs drawn from the real Command_Registry.
# Every pair references an existing Registered_Command and supplies parameters
# that satisfy that command's schema, so each candidate survives the parser's
# allow-list + validation filter and participates in ambiguity ranking.
_VALID_COMMANDS: list[tuple[str, dict[str, Any]]] = [
    ("launch_app", {"app_name": "chrome"}),
    ("open_path", {"path": "report.pdf"}),
    ("web_search", {"query": "weather"}),
    ("media_control", {"action": "play"}),
    ("dictation", {"text": "hello"}),
    ("window_management", {"action": "minimize"}),
    ("lock_pc", {}),
]


class _FakeEngine:
    """Deterministic CandidateEngine returning a preset candidate list."""

    def __init__(self, candidates: list[CandidateMapping]) -> None:
        self._candidates = candidates

    def propose(self, text: str) -> list[CandidateMapping]:
        return list(self._candidates)


@st.composite
def _confidences(draw: st.DrawFn) -> list[float]:
    """Generate confidence lists that straddle the 0.10 ambiguity boundary.

    Mixes three shapes so both sides of the threshold are well covered:
      * general lists of 0-6 confidences anywhere in [0.0, 1.0];
      * two-candidate lists whose gap is drawn tightly around 0.10;
      * boundary lists whose top gap is drawn around 0.10 with extra lower
        candidates trailing behind.
    """
    shape = draw(st.integers(min_value=0, max_value=2))

    if shape == 0:
        return draw(
            st.lists(
                st.floats(min_value=0.0, max_value=1.0),
                min_size=0,
                max_size=6,
            )
        )

    # Shapes 1 and 2 straddle the boundary: pick a top value and a gap around
    # the 0.10 threshold, then place the second candidate a gap below.
    top = draw(st.floats(min_value=0.10, max_value=1.0))
    gap = draw(st.floats(min_value=0.0, max_value=0.20))
    second = max(0.0, top - gap)
    values = [top, second]

    if shape == 2:
        # Add extra candidates strictly at or below the second value so the
        # "two highest" remain ``top`` and ``second``.
        extras = draw(
            st.lists(
                st.floats(min_value=0.0, max_value=1.0),
                min_size=1,
                max_size=3,
            )
        )
        values.extend(min(second, e) for e in extras)

    return values


@st.composite
def _candidate_lists(draw: st.DrawFn) -> list[CandidateMapping]:
    """Build a list of valid candidate mappings with generated confidences."""
    confidences = draw(_confidences())
    candidates: list[CandidateMapping] = []
    for confidence in confidences:
        command_id, parameters = draw(st.sampled_from(_VALID_COMMANDS))
        candidates.append(
            CandidateMapping(
                command_id=command_id,
                parameters=dict(parameters),
                confidence=confidence,
            )
        )
    return candidates


# Feature: friday-desktop-agent, Property 13: Ambiguity detection threshold
@settings(max_examples=200)
@given(candidates=_candidate_lists())
def test_ambiguity_detection_threshold(
    candidates: list[CandidateMapping],
) -> None:
    """Ambiguous iff the two highest confidences differ by <= 0.10.

    Validates: Requirements 5.3
    """
    parser = IntentParser(_FakeEngine(candidates))
    result = parser.parse_intent("do something")

    # Replicate the parser's ranking on the (already valid) candidate
    # confidences to compute the expected ambiguity decision.
    confidences = sorted(
        (c.confidence for c in candidates), reverse=True
    )
    expected_ambiguous = (
        len(confidences) >= 2
        and (confidences[0] - confidences[1]) <= AMBIGUITY_THRESHOLD
    )

    if expected_ambiguous:
        assert result.status == CommandStatus.AMBIGUOUS
        # The candidate list is returned, ranked highest-confidence first.
        assert len(result.candidates) == len(candidates)
        returned = [c.confidence for c in result.candidates]
        assert returned == sorted(returned, reverse=True)
    else:
        # Not ambiguous: either nothing mapped (0 candidates) or a single best
        # mapping was chosen -- never an ambiguous-command status.
        assert result.status != CommandStatus.AMBIGUOUS
        if confidences:
            assert result.status == CommandStatus.SUCCESS
        else:
            assert result.status == CommandStatus.UNRECOGNIZED
