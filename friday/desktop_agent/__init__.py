"""FRIDAY Desktop Agent package.

A local native process that runs on the user's Windows PC and executes
explicitly allow-listed operating-system actions on behalf of the FRIDAY
assistant. The agent binds only to the loopback interface, requires a
high-entropy per-session token on every request, and records every outcome
in a local append-only audit log.

This package exposes the core immutable data models shared across the
Desktop_Agent components (see design.md, "Data Models").
"""

from __future__ import annotations

from friday.desktop_agent.authorization import AuthorizationManager
from friday.desktop_agent.client_bridge import (
    COMMAND_PATH,
    DEFAULT_TIMEOUT_SECONDS as CLIENT_BRIDGE_DEFAULT_TIMEOUT_SECONDS,
    RELAYABLE_STATUSES,
    SESSION_TOKEN_HEADER,
    AgentUnreachableError,
    DesktopAgentClient,
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
)
from friday.desktop_agent.confirmation import (
    DEFAULT_TIMEOUT_SECONDS,
    ConfirmationManager,
)
from friday.desktop_agent.executor import (
    CommandExecutor,
    OSHandlers,
    WindowsOSHandlers,
    build_search_url,
)
from friday.desktop_agent.intent_parser import (
    AMBIGUITY_THRESHOLD,
    CandidateEngine,
    CandidateMapping,
    IntentParser,
    LLMCandidateEngine,
    desktop_tool_definitions,
    parse_intent,
    register_desktop_tools,
)
from friday.desktop_agent.models import (
    AgentState,
    AuditEntry,
    AuthResult,
    CommandStatus,
    ConfirmationPrompt,
    ExecutionResult,
    IntentResult,
    RegisteredCommand,
    RiskClass,
    SessionToken,
    StructuredCommand,
)
from friday.desktop_agent.pipeline import (
    DesktopCommandPipeline,
    InProcessAgentTransport,
    build_in_process_pipeline,
)
from friday.desktop_agent.registry import all_commands, lookup
from friday.desktop_agent.runtime import (
    DesktopAgentRuntime,
    build_desktop_agent,
)
from friday.desktop_agent.screen_observer import (
    DEFAULT_VISION_PROMPT,
    AuditRecorder,
    CapturedFrame,
    FrameGrabber,
    GeminiVisionProvider,
    ObservationResult,
    ScreenObserver,
    VisionProvider,
    VisionProviderError,
)
from friday.desktop_agent.server import (
    LOOPBACK_HOST,
    ConfirmationManager as ConfirmationManagerProtocol,
    LoopbackCommandServer,
    PendingConfirmationManager,
    is_loopback,
)
from friday.desktop_agent.state import (
    AgentStateMachine,
    StateTransition,
)
from friday.desktop_agent.validator import (
    ValidationResult,
    clamp_volume,
    validate,
    validate_parameters,
)

__all__ = [
    "AMBIGUITY_THRESHOLD",
    "AgentState",
    "AgentStateMachine",
    "AgentUnreachableError",
    "AuditEntry",
    "AuditRecorder",
    "AuthResult",
    "AuthorizationManager",
    "CLIENT_BRIDGE_DEFAULT_TIMEOUT_SECONDS",
    "COMMAND_PATH",
    "CandidateEngine",
    "CandidateMapping",
    "CapturedFrame",
    "CommandExecutor",
    "CommandStatus",
    "DesktopAgentClient",
    "DesktopAgentRuntime",
    "DesktopCommandPipeline",
    "ConfirmationPrompt",
    "ConfirmationManager",
    "ConfirmationManagerProtocol",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_VISION_PROMPT",
    "ExecutionResult",
    "FrameGrabber",
    "GeminiVisionProvider",
    "HttpResponse",
    "HttpTransport",
    "InProcessAgentTransport",
    "IntentParser",
    "IntentResult",
    "LLMCandidateEngine",
    "LOOPBACK_HOST",
    "LoopbackCommandServer",
    "ObservationResult",
    "OSHandlers",
    "PendingConfirmationManager",
    "RELAYABLE_STATUSES",
    "RegisteredCommand",
    "RiskClass",
    "SESSION_TOKEN_HEADER",
    "ScreenObserver",
    "SessionToken",
    "StateTransition",
    "StructuredCommand",
    "UrllibHttpTransport",
    "ValidationResult",
    "VisionProvider",
    "VisionProviderError",
    "WindowsOSHandlers",
    "all_commands",
    "build_desktop_agent",
    "build_in_process_pipeline",
    "build_search_url",
    "clamp_volume",
    "desktop_tool_definitions",
    "is_loopback",
    "lookup",
    "parse_intent",
    "register_desktop_tools",
    "validate",
    "validate_parameters",
]
