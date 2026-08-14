"""Intent_Parser for the FRIDAY Desktop Agent.

The Intent_Parser runs inside the FRIDAY_Backend, layered on the existing
``IntentRouter`` / ``ToolRegistry`` tool-calling flow. It converts
natural-language voice input into a machine-readable ``StructuredCommand`` that
references a ``RegisteredCommand`` in the Command_Registry allow-list, together
with a mapping confidence in the inclusive range ``[0.0, 1.0]``.

Design reference: design.md, "FRIDAY_Backend additions" -> "Intent_Parser
(desktop command mapping)".

Responsibilities (Req 5.1, 5.2, 5.3, 5.5):
    * Register the desktop tool definitions (launch app, open path, web search,
      media control, dictation, window management, lock PC) with the existing
      ``ToolRegistry`` so the LLM tool-selection flow can map free text to a
      Registered_Command identifier and validated parameters.
    * Produce a ``StructuredCommand`` with a confidence value in ``[0.0, 1.0]``
      when the input maps to a single best Registered_Command (Req 5.1, 5.5).
    * Return an ``unrecognized-command`` status when nothing maps (Req 5.2).
    * Return an ``ambiguous-command`` status listing the candidates when the two
      highest-confidence candidates differ by ``<= 0.10`` (Req 5.3).

Non-execution guarantee
-----------------------
The parser NEVER executes anything. It only produces an :class:`IntentResult`
carrying a ``StructuredCommand`` (or a candidate list). Forwarding the command
to the Desktop_Agent and executing it is the responsibility of the client
bridge and the agent's enforcement gauntlet.

Mockable AI seam
----------------
Candidate generation is isolated behind the :class:`CandidateEngine` seam so
tests can inject deterministic candidate mappings without invoking a real LLM.
The default :class:`LLMCandidateEngine` wraps the existing tool-calling
selection client (the same ``select_tools`` seam used by ``IntentRouter``).

**Validates: Requirements 5.1, 5.2, 5.3, 5.5**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from friday.desktop_agent.models import (
    CommandStatus,
    IntentResult,
    StructuredCommand,
)
from friday.desktop_agent.registry import all_commands, lookup
from friday.desktop_agent.validator import validate
from friday.modules.tool_calling.models import ToolDefinition, ToolRegistrationError
from friday.modules.tool_calling.registry import ToolRegistry

# The Intent_Parser flags a set of candidate mappings as ambiguous when the two
# highest confidence values differ by this amount or less (Req 5.3).
AMBIGUITY_THRESHOLD = 0.10

# Confidence assigned to a tool the LLM selected when the selection seam does
# not itself provide a numeric confidence. A selected tool is treated as a
# high-confidence mapping; injected engines may supply their own values.
_DEFAULT_LLM_CONFIDENCE = 1.0


def _clamp_confidence(value: float) -> float:
    """Clamp a raw confidence value into the inclusive range ``[0.0, 1.0]``.

    Guarantees the ``StructuredCommand.confidence`` invariant (Req 5.5)
    regardless of what an upstream engine reports.

    Args:
        value: The raw confidence value proposed by a CandidateEngine.

    Returns:
        ``value`` clamped to ``[0.0, 1.0]``.
    """
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class CandidateMapping:
    """A single proposed mapping from free text to a Registered_Command.

    Produced by a :class:`CandidateEngine`. The Intent_Parser validates each
    candidate against the Command_Registry allow-list and its parameter schema
    before ranking, so a proposed mapping is not guaranteed to be valid.

    Attributes:
        command_id: The proposed Registered_Command identifier.
        parameters: The proposed parameters for the command.
        confidence: The engine's confidence for this mapping. It is clamped to
            ``[0.0, 1.0]`` by the parser (Req 5.5).
    """

    command_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@runtime_checkable
class CandidateEngine(Protocol):
    """Mockable seam that proposes candidate command mappings for input text.

    The default implementation (:class:`LLMCandidateEngine`) delegates to the
    existing tool-calling LLM selection client. Tests inject a fake that returns
    deterministic candidate mappings so the parser's ranking, ambiguity, and
    validation logic can be exercised without a real AI engine.
    """

    def propose(self, text: str) -> list[CandidateMapping]:
        """Return candidate command mappings for ``text`` (possibly empty)."""
        ...


def desktop_tool_definitions() -> list[ToolDefinition]:
    """Return the desktop tool definitions derived from the Command_Registry.

    Each ``RegisteredCommand`` in the allow-list is projected onto a
    tool-calling ``ToolDefinition`` so the existing ``IntentRouter`` /
    ``ToolRegistry`` LLM tool-selection flow can map free text to a
    Registered_Command identifier and its parameters. The tool ``name`` matches
    the ``command_id`` so a selected tool maps directly back to a registry
    entry.

    Returns:
        A list of ``ToolDefinition`` objects, one per Registered_Command.

    **Validates: Requirements 5.1**
    """
    return [
        ToolDefinition(
            name=command.command_id,
            description=command.description,
            parameters=command.parameters,
            handler_name=command.handler_name,
        )
        for command in all_commands()
    ]


def register_desktop_tools(registry: ToolRegistry) -> list[ToolRegistrationError]:
    """Register the desktop tool definitions with a ``ToolRegistry``.

    Adds the desktop command tools (launch app, open path, web search, media
    control, dictation, window management, lock PC) to the shared tool-calling
    registry used by the existing ``IntentRouter`` (Req 5.1).

    Args:
        registry: The ``ToolRegistry`` to register the desktop tools with.

    Returns:
        A list of ``ToolRegistrationError`` for any tool that failed validation;
        empty when every desktop tool registered successfully.

    **Validates: Requirements 5.1**
    """
    errors: list[ToolRegistrationError] = []
    for tool in desktop_tool_definitions():
        error = registry.register(tool)
        if error is not None:
            errors.append(error)
    return errors


class LLMCandidateEngine:
    """Default :class:`CandidateEngine` backed by the tool-calling LLM seam.

    Wraps the same ``select_tools`` selection client used by ``IntentRouter``.
    The desktop tool definitions are offered to the model, and each selected
    tool call is projected onto a :class:`CandidateMapping`. Because the raw
    selection API does not report a numeric confidence, selected tools are
    assigned ``_DEFAULT_LLM_CONFIDENCE``; deterministic confidences are supplied
    by injected engines in tests.
    """

    def __init__(
        self,
        select_tools: Callable[..., Any],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        timeout: float = 3.0,
        default_confidence: float = _DEFAULT_LLM_CONFIDENCE,
    ) -> None:
        """Initialize the engine.

        Args:
            select_tools: The tool-selection callable (e.g. the ``llm`` module's
                ``select_tools``) matching ``IntentRouter``'s selection seam.
                Must accept ``message``, ``tools``, ``tool_choice`` and
                ``timeout`` keyword arguments and return an object exposing
                ``is_error``, ``has_tool_calls`` and ``tool_calls``.
            tools: Optional pre-built OpenAI-format tool list. Defaults to the
                desktop tool definitions.
            timeout: Selection timeout in seconds.
            default_confidence: Confidence assigned to a selected tool.
        """
        self._select_tools = select_tools
        self._tools = tools if tools is not None else [
            tool.to_openai_format() for tool in desktop_tool_definitions()
        ]
        self._timeout = timeout
        self._default_confidence = default_confidence

    def propose(self, text: str) -> list[CandidateMapping]:
        """Propose candidate mappings by asking the LLM to select desktop tools.

        Args:
            text: The natural-language voice input.

        Returns:
            A list of candidate mappings, one per selected tool call. Returns an
            empty list when selection errors or no tool is selected.
        """
        result = self._select_tools(
            message=text,
            tools=self._tools,
            tool_choice="auto",
            timeout=self._timeout,
        )

        if getattr(result, "is_error", False) or not getattr(
            result, "has_tool_calls", False
        ):
            return []

        candidates: list[CandidateMapping] = []
        for call in result.tool_calls:
            candidates.append(
                CandidateMapping(
                    command_id=call.function_name,
                    parameters=dict(call.arguments or {}),
                    confidence=self._default_confidence,
                )
            )
        return candidates


class IntentParser:
    """Maps natural-language input to a validated ``StructuredCommand``.

    The parser delegates candidate generation to a :class:`CandidateEngine`
    seam, then applies allow-list + schema validation, ranking, and ambiguity
    detection to produce an :class:`IntentResult`. It performs no execution.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.5**
    """

    def __init__(self, engine: CandidateEngine) -> None:
        """Initialize the parser with a candidate engine seam.

        Args:
            engine: The :class:`CandidateEngine` used to propose candidate
                mappings for input text.
        """
        self._engine = engine

    def parse_intent(self, text: str) -> IntentResult:
        """Parse ``text`` into an :class:`IntentResult`.

        Flow:
            1. Ask the engine for candidate mappings.
            2. Keep only candidates that reference an existing
               Registered_Command and whose parameters pass validation, with
               confidence clamped to ``[0.0, 1.0]`` (Req 5.1, 5.5).
            3. If no candidate survives, return ``UNRECOGNIZED`` (Req 5.2).
            4. Rank surviving candidates by confidence (highest first). If the
               top two differ by ``<= 0.10``, return ``AMBIGUOUS`` listing the
               candidates (Req 5.3). Otherwise return the top candidate as the
               recognized ``StructuredCommand``.

        Args:
            text: The natural-language voice input.

        Returns:
            An :class:`IntentResult` whose status is one of ``SUCCESS``
            (recognized, with ``command`` set), ``UNRECOGNIZED``, or
            ``AMBIGUOUS`` (with ``candidates`` set).

        **Validates: Requirements 5.1, 5.2, 5.3, 5.5**
        """
        raw_candidates = self._engine.propose(text) or []

        valid: list[StructuredCommand] = []
        for candidate in raw_candidates:
            registered = lookup(candidate.command_id)
            if registered is None:
                # References an action absent from the Command_Registry; it
                # cannot become a Structured_Command (Req 5.1).
                continue

            parameters = dict(candidate.parameters or {})
            if not validate(registered, parameters).valid:
                # Parameters do not satisfy the command's schema, so this is not
                # a valid mapping (Req 5.1).
                continue

            valid.append(
                StructuredCommand(
                    command_id=candidate.command_id,
                    parameters=parameters,
                    confidence=_clamp_confidence(candidate.confidence),
                )
            )

        # Req 5.2: nothing mapped to a Registered_Command.
        if not valid:
            return IntentResult(status=CommandStatus.UNRECOGNIZED)

        # Rank by confidence, highest first (stable for equal confidences).
        ranked = sorted(valid, key=lambda command: command.confidence, reverse=True)

        # Req 5.3: ambiguous when the top two candidates are within the
        # threshold of each other.
        if len(ranked) >= 2:
            top_delta = ranked[0].confidence - ranked[1].confidence
            if top_delta <= AMBIGUITY_THRESHOLD:
                return IntentResult(
                    status=CommandStatus.AMBIGUOUS,
                    candidates=ranked,
                )

        # Recognized: a single best mapping (Req 5.1, 5.5).
        return IntentResult(status=CommandStatus.SUCCESS, command=ranked[0])


def parse_intent(text: str, engine: CandidateEngine) -> IntentResult:
    """Parse ``text`` into an :class:`IntentResult` using ``engine``.

    Module-level convenience wrapper around :class:`IntentParser` for callers
    that do not need to hold a parser instance.

    Args:
        text: The natural-language voice input.
        engine: The :class:`CandidateEngine` seam supplying candidate mappings.

    Returns:
        The :class:`IntentResult` produced by the parser.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.5**
    """
    return IntentParser(engine).parse_intent(text)
