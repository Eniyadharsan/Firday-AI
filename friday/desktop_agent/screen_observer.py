"""Screen_Observer (opt-in) for the FRIDAY Desktop Agent.

The Screen_Observer is the opt-in screen-awareness component. It captures
screen content and sends it to a vision-capable provider (the existing Gemini
adapter) for description or context extraction. Screen awareness is **disabled
by default** and never captures anything until the user both enables it and
records explicit opt-in consent.

Design reference: design.md, "Desktop_Agent components" -> "Screen_Observer
(opt-in)".

Privacy-by-construction
------------------------
* Disabled by default; the observer never captures while disabled (Req 10.1).
* Enabling screen awareness requires explicit opt-in consent before the first
  capture; declining consent leaves the observer disabled (Req 10.2, 10.3).
* On capture, the frame is sent to the Vision_Provider (Req 10.4), the capture
  event and its timestamp are recorded (Req 10.8), and the captured content is
  retained *only* for the duration of the Vision_Provider call, then discarded
  in a ``finally`` block (Req 10.9).
* On a Vision_Provider failure the frame is discarded, a ``vision-unavailable``
  status is returned, and the failure is recorded (Req 10.5).
* Disabling screen awareness or a Kill_Switch activation stops capturing
  synchronously, well within the 1-second bound, and drives the agent's
  observing state (Req 8.3, 10.6, 10.7).

Testability by construction
---------------------------
All real side effects are isolated behind injectable seams:
    * :class:`FrameGrabber` grabs a screen frame (never touched directly).
    * :class:`VisionProvider` sends a frame to the vision-capable model. The
      production wrapper :class:`GeminiVisionProvider` adapts the existing
      ``Gemini_Adapter``; tests inject a fake that returns a canned
      description or raises to simulate failure.
    * An injected ``clock`` supplies timing so timestamps are deterministic.
    * An optional audit recorder (the ``AuditLog``) records capture and
      vision-failure events, and an optional state machine drives the
      observing state.

**Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 8.3**
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, runtime_checkable

from friday.desktop_agent.audit import ISO_TIMESTAMP_FORMAT
from friday.desktop_agent.models import CommandStatus
from friday.desktop_agent.state import AgentStateMachine

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids importing SDK deps
    from friday.modules.providers.base import Provider_Adapter

# Default prompt sent alongside a captured frame asking the Vision_Provider to
# describe the on-screen context (Req 10.4).
DEFAULT_VISION_PROMPT = (
    "Describe what is currently shown on the user's screen and summarize any "
    "actionable context."
)

# Seam for a clock returning epoch seconds, matching the injected-clock
# convention used across the Desktop_Agent (SessionToken, ConfirmationPrompt).
Clock = Callable[[], float]


def _to_iso8601(epoch_seconds: float) -> str:
    """Convert epoch seconds to the audit-log ISO 8601 timestamp string.

    Uses the same format string as :data:`friday.desktop_agent.audit` so the
    capture and failure records the observer writes are consistent with every
    other audited event.
    """

    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime(
        ISO_TIMESTAMP_FORMAT
    )


@dataclass(frozen=True)
class CapturedFrame:
    """An opaque, in-memory screen capture handed to the Vision_Provider.

    The frame is held only for the duration of the Vision_Provider call and is
    discarded immediately afterward (Req 10.9). It is intentionally minimal so
    no captured pixel data is ever persisted or logged.

    Attributes:
        image: Raw encoded image bytes of the captured screen content.
        mime_type: The image encoding, e.g. ``"image/png"``.
    """

    image: bytes
    mime_type: str = "image/png"


@dataclass(frozen=True)
class ObservationResult:
    """Outcome of a screen-capture-and-describe cycle.

    Attributes:
        status: ``SUCCESS`` with a description, ``VISION_UNAVAILABLE`` on a
            Vision_Provider failure (Req 10.5), or ``DISABLED`` when capture is
            refused because screen awareness is off or consent is absent
            (Req 10.1-10.3).
        description: The Vision_Provider description on success, else ``None``.
        detail: Human-readable detail about the outcome.
    """

    status: CommandStatus
    description: Optional[str] = None
    detail: str = ""


@runtime_checkable
class FrameGrabber(Protocol):
    """Injectable seam that grabs the current screen content as a frame.

    The observer depends only on this protocol, never on a concrete
    screen-capture API, so no capture ever happens in tests unless a fake is
    invoked. Crucially, the observer only calls :meth:`capture` after the
    consent/enabled gates pass, guaranteeing no capture while disabled or
    without consent (Req 10.1-10.3).
    """

    def capture(self) -> CapturedFrame:
        """Grab the current screen content and return it as a frame."""
        ...


@runtime_checkable
class VisionProvider(Protocol):
    """Injectable seam that sends a captured frame to a vision-capable model.

    The production implementation (:class:`GeminiVisionProvider`) wraps the
    existing Gemini adapter; tests substitute a fake that returns a canned
    description or raises to simulate a provider failure (Req 10.5).
    """

    def describe(self, frame: CapturedFrame, prompt: str) -> str:
        """Return a description of ``frame``.

        Raises:
            Exception: Any error signals a Vision_Provider failure, which the
                observer converts into a ``vision-unavailable`` outcome
                (Req 10.5).
        """
        ...


@runtime_checkable
class AuditRecorder(Protocol):
    """Seam for recording capture/vision-failure events.

    Satisfied by :class:`friday.desktop_agent.audit.AuditLog` (which provides
    ``record_capture`` and ``record_vision_failure``) or by a collecting fake
    in tests.
    """

    def record_capture(self, timestamp: Optional[str] = None) -> Any:
        """Record a Screen_Observer capture event and its timestamp (Req 10.8)."""
        ...

    def record_vision_failure(
        self, reason: str, timestamp: Optional[str] = None
    ) -> Any:
        """Record a Vision_Provider failure (Req 10.5)."""
        ...


class VisionProviderError(RuntimeError):
    """Raised by :class:`GeminiVisionProvider` when a vision request fails."""


class GeminiVisionProvider:
    """Adapts the existing Gemini adapter to the :class:`VisionProvider` seam.

    Wraps a ``Provider_Adapter`` (the Gemini adapter, whose
    ``capabilities.supports_vision`` is ``True``) so the Screen_Observer can
    send a captured frame to the vision-capable model without depending on the
    adapter's concrete API. Any adapter error or empty response is surfaced as
    a :class:`VisionProviderError`, which the observer treats as a
    Vision_Provider failure (Req 10.5).

    Args:
        adapter: The vision-capable provider adapter (the Gemini adapter).
        model: Optional model override; defaults to the adapter's default.
        prompt: The instruction sent alongside the captured frame.
    """

    def __init__(
        self,
        adapter: "Provider_Adapter",
        model: Optional[str] = None,
        prompt: str = DEFAULT_VISION_PROMPT,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._prompt = prompt

    def describe(self, frame: CapturedFrame, prompt: Optional[str] = None) -> str:
        """Send ``frame`` to the Gemini vision model and return its description.

        The captured image is passed as an inline image part alongside a text
        instruction. The frame reference is not retained by this wrapper beyond
        the call, consistent with the observer's retention guarantee (Req 10.9).

        Raises:
            VisionProviderError: If the adapter raises or returns no content.
        """
        import base64

        encoded = base64.b64encode(frame.image).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": prompt or self._prompt,
                # Inline image for the vision-capable Gemini model. The adapter
                # forwards the content to the model; a non-vision provider would
                # simply ignore the image, but the Gemini adapter advertises
                # ``supports_vision=True``.
                "image": {"mime_type": frame.mime_type, "data": encoded},
            }
        ]
        try:
            response = self._adapter.generate(messages, model=self._model)
        except Exception as exc:  # noqa: BLE001 - normalize to a vision failure
            raise VisionProviderError(str(exc)) from exc

        content = getattr(response, "content", None)
        if not content:
            raise VisionProviderError("Vision provider returned an empty response")
        return content


class ScreenObserver:
    """Opt-in screen-awareness component.

    Coordinates the consent gate, the frame grabber, the Vision_Provider, the
    audit recorder, and the agent state machine to implement the full capture
    lifecycle while enforcing the privacy guarantees in Requirement 10.

    Screen awareness is disabled by default. A capture only proceeds when the
    user has enabled screen awareness *and* recorded explicit opt-in consent;
    otherwise :meth:`capture` returns a ``DISABLED`` result without ever
    touching the frame grabber (Req 10.1-10.3).

    Args:
        frame_grabber: Seam that grabs a screen frame (Req 10.4).
        vision_provider: Seam that describes a frame (the Gemini adapter
            wrapper in production) (Req 10.4).
        audit: Optional recorder for capture and vision-failure events
            (Req 10.5, 10.8). Pass the ``AuditLog`` instance to persist them.
        state_machine: Optional :class:`AgentStateMachine` used to drive the
            observing state around each capture (Req 9.2, 10.6) and to honor a
            Kill_Switch disable (Req 8.3).
        clock: Injected clock returning epoch seconds; defaults to
            :func:`time.time`. Enables deterministic timestamps in tests.
        prompt: The instruction sent to the Vision_Provider with each frame.
    """

    def __init__(
        self,
        frame_grabber: FrameGrabber,
        vision_provider: VisionProvider,
        audit: Optional[AuditRecorder] = None,
        state_machine: Optional[AgentStateMachine] = None,
        clock: Clock = time.time,
        prompt: str = DEFAULT_VISION_PROMPT,
    ) -> None:
        self._frame_grabber = frame_grabber
        self._vision_provider = vision_provider
        self._audit = audit
        self._state_machine = state_machine
        self._clock = clock
        self._prompt = prompt

        # Disabled by default and no consent recorded (Req 10.1, 10.2).
        self._enabled: bool = False
        self._consent_granted: bool = False
        # The frame currently being processed. Held only for the duration of
        # the Vision_Provider call; discarded (set to None) in ``finally``
        # (Req 10.9). Never persisted or logged.
        self._current_frame: Optional[CapturedFrame] = None

    # -- State inspection -----------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        """Whether screen awareness is currently enabled."""
        return self._enabled

    @property
    def has_consent(self) -> bool:
        """Whether explicit opt-in consent has been recorded (Req 10.2)."""
        return self._consent_granted

    @property
    def can_capture(self) -> bool:
        """Whether a capture may proceed: enabled *and* consented (Req 10.1-10.3)."""
        return self._enabled and self._consent_granted

    @property
    def current_frame(self) -> Optional[CapturedFrame]:
        """The frame currently being processed, or ``None`` when idle.

        Exposed for observability/testing the retention guarantee: it is
        non-``None`` only for the duration of an in-flight Vision_Provider call
        and ``None`` at every other time (Req 10.9).
        """
        return self._current_frame

    # -- Consent and enable/disable lifecycle ---------------------------------

    def grant_consent(self) -> None:
        """Record explicit opt-in consent and enable screen awareness.

        This is the affirmative opt-in required before the first capture
        (Req 10.2). After it, :meth:`can_capture` becomes ``True``.
        """
        self._consent_granted = True
        self._enabled = True

    def decline_consent(self) -> None:
        """Decline the opt-in consent, leaving the observer disabled.

        The observer remains disabled and will not capture screen content
        (Req 10.3).
        """
        self._consent_granted = False
        self._enabled = False

    def enable(self) -> None:
        """Re-enable screen awareness (only meaningful once consent exists).

        Enabling never bypasses the consent gate: capture still requires
        recorded opt-in consent (Req 10.2). If consent has not been granted,
        this has no effect on :meth:`can_capture`.
        """
        if self._consent_granted:
            self._enabled = True

    def disable(self, now: Optional[float] = None) -> None:
        """Disable screen awareness and stop capturing.

        Flips the enabled flag synchronously so any subsequent capture is
        refused, well within the 1-second bound (Req 10.7). If the state
        machine is currently observing, it is returned to the enabled state.
        Consent is preserved so re-enabling does not require a fresh opt-in.

        Args:
            now: Optional epoch-seconds timestamp; defaults to the injected
                clock.
        """
        self._enabled = False
        self._current_frame = None
        self._leave_observing(self._resolve_now(now))

    def stop_for_kill_switch(self, now: Optional[float] = None) -> None:
        """Stop the observer in response to a Kill_Switch activation (Req 8.3).

        Equivalent to :meth:`disable`: capturing stops synchronously within the
        1-second bound. Kept as a distinct method so callers can express intent
        at the call site.
        """
        self.disable(now)

    # -- Capture lifecycle ----------------------------------------------------

    def capture(self, now: Optional[float] = None) -> ObservationResult:
        """Capture the screen and send it to the Vision_Provider.

        Enforces the full opt-in capture lifecycle:

        1. Refuse to capture while disabled, without consent, or while the
           agent is kill-switched; the frame grabber is never called in that
           case (Req 10.1-10.3, 8.3).
        2. Drive the observing state for the duration of the capture (Req 10.6).
        3. Grab the frame, record the capture event and timestamp (Req 10.8),
           and send the frame to the Vision_Provider (Req 10.4).
        4. On success, return the description; on failure, discard the frame,
           record the failure, and return ``vision-unavailable`` (Req 10.5).
        5. Always discard the retained frame afterward (Req 10.9) and leave the
           observing state.

        Args:
            now: Optional epoch-seconds timestamp; defaults to the injected
                clock.

        Returns:
            An :class:`ObservationResult` describing the outcome.

        **Validates: Requirements 10.1-10.9, 8.3**
        """
        resolved_now = self._resolve_now(now)

        # Gate 1: never capture while disabled or without consent (Req 10.1-10.3),
        # and never capture while the agent is kill-switched (Req 8.3).
        if not self.can_capture or self._agent_disabled():
            return ObservationResult(
                status=CommandStatus.DISABLED,
                detail="Screen awareness is disabled or opt-in consent is absent.",
            )

        # Drive the observing state so the Active_Indicator reflects capturing
        # for the duration of this cycle (Req 9.2, 10.6).
        self._enter_observing(resolved_now)

        try:
            # Grab the frame and retain it only until the response resolves.
            self._current_frame = self._frame_grabber.capture()

            # Record the capture event + timestamp as the frame is sent to the
            # Vision_Provider (Req 10.8).
            self._record_capture(resolved_now)

            # Send the captured content to the Vision_Provider (Req 10.4).
            description = self._describe(self._current_frame)
            return ObservationResult(
                status=CommandStatus.SUCCESS,
                description=description,
            )
        except Exception as exc:  # noqa: BLE001 - any failure => vision-unavailable
            # Discard the frame (handled by finally), return vision-unavailable,
            # and record the failure (Req 10.5).
            self._record_vision_failure(str(exc), resolved_now)
            return ObservationResult(
                status=CommandStatus.VISION_UNAVAILABLE,
                detail="The Vision_Provider request failed.",
            )
        finally:
            # Retain the captured content only until the response resolves,
            # then discard it (Req 10.9).
            self._current_frame = None
            self._leave_observing(resolved_now)

    # -- Internals ------------------------------------------------------------

    def _describe(self, frame: CapturedFrame) -> str:
        """Invoke the Vision_Provider seam for ``frame``."""
        try:
            # The production wrapper accepts an optional prompt; fakes may not.
            return self._vision_provider.describe(frame, self._prompt)  # type: ignore[call-arg]
        except TypeError:
            # Fallback for seams whose ``describe`` takes only the frame.
            return self._vision_provider.describe(frame)  # type: ignore[call-arg]

    def _agent_disabled(self) -> bool:
        """True when a state machine is present and reports a disabled agent."""
        return self._state_machine is not None and self._state_machine.is_disabled

    def _enter_observing(self, now: float) -> None:
        """Drive the state machine into the observing state, if present."""
        if self._state_machine is not None and not self._state_machine.is_observing:
            self._state_machine.start_observing(now)

    def _leave_observing(self, now: float) -> None:
        """Return the state machine to enabled if it is observing, if present."""
        if self._state_machine is not None and self._state_machine.is_observing:
            self._state_machine.stop_observing(now)

    def _record_capture(self, now: float) -> None:
        """Record the capture event through the audit seam (Req 10.8)."""
        if self._audit is not None:
            self._audit.record_capture(timestamp=_to_iso8601(now))

    def _record_vision_failure(self, reason: str, now: float) -> None:
        """Record a Vision_Provider failure through the audit seam (Req 10.5)."""
        if self._audit is not None:
            self._audit.record_vision_failure(
                reason=reason, timestamp=_to_iso8601(now)
            )

    def _resolve_now(self, now: Optional[float]) -> float:
        """Return the provided timestamp or the injected clock's current time."""
        return self._clock() if now is None else now
