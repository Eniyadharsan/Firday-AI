# Feature: friday-desktop-agent, Property 22: No screen capture without consent
"""Property-based test for the Screen_Observer opt-in capture gate.

Property 22: No screen capture without consent
For any capture attempt while screen awareness is disabled or explicit opt-in
consent has not been recorded, the Screen_Observer SHALL NOT capture any screen
content.

Validates: Requirements 10.1, 10.2, 10.3
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.models import AgentState, CommandStatus
from friday.desktop_agent.screen_observer import (
    CapturedFrame,
    ObservationResult,
    ScreenObserver,
)
from friday.desktop_agent.state import AgentStateMachine


# Epoch-second range kept finite/positive so timestamp arithmetic and ISO
# conversion stay well-behaved. Roughly year 2001..2035.
_times = st.floats(
    min_value=1_000_000_000.0,
    max_value=2_000_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)


class _FrameGrabberSpy:
    """A spy standing in for the screen FrameGrabber seam.

    Records whether ``capture()`` was ever invoked. The Screen_Observer must
    only reach the frame grabber after the enabled *and* consent gates pass, so
    ``captured`` must remain False whenever screen awareness is disabled or
    opt-in consent has not been recorded (Property 22).
    """

    def __init__(self) -> None:
        self.captured = False
        self.calls = 0

    def capture(self) -> CapturedFrame:
        self.captured = True
        self.calls += 1
        return CapturedFrame(image=b"pixels", mime_type="image/png")


class _VisionProviderSpy:
    """A fake Vision_Provider that records whether a frame was ever described.

    If the observer honors the consent gate, no frame is grabbed and therefore
    nothing is ever sent to the Vision_Provider while disabled/without consent.
    """

    def __init__(self) -> None:
        self.described = False

    def describe(self, frame: CapturedFrame, prompt: str = "") -> str:
        self.described = True
        return "a description"


# Ways the observer can end up disabled or without recorded consent. Each is a
# callable applied to a freshly constructed observer; none of them should ever
# permit a capture (Req 10.1, 10.2, 10.3).
def _leave_default(observer: ScreenObserver) -> None:
    """Untouched: disabled by default, no consent recorded (Req 10.1, 10.2)."""


def _decline_consent(observer: ScreenObserver) -> None:
    """User declines the opt-in consent -> remains disabled (Req 10.3)."""
    observer.decline_consent()


def _enable_without_consent(observer: ScreenObserver) -> None:
    """Enable attempt without prior consent must not permit capture (Req 10.2)."""
    observer.enable()


def _grant_then_disable(observer: ScreenObserver) -> None:
    """Consent granted then screen awareness disabled again (Req 10.1)."""
    observer.grant_consent()
    observer.disable()


def _grant_then_kill_switch(observer: ScreenObserver) -> None:
    """Consent granted then stopped by the Kill_Switch (Req 10.1)."""
    observer.grant_consent()
    observer.stop_for_kill_switch()


_no_consent_setups = st.sampled_from(
    [
        _leave_default,
        _decline_consent,
        _enable_without_consent,
        _grant_then_disable,
        _grant_then_kill_switch,
    ]
)


@settings(max_examples=200)
@given(setup=_no_consent_setups, now=_times)
def test_no_capture_while_disabled_or_without_consent(setup, now: float) -> None:
    """No screen content is captured while disabled or without consent.

    For every way the observer can be disabled or lack recorded opt-in consent,
    a capture attempt must return a ``disabled`` result and must never invoke
    the frame grabber or the Vision_Provider (Req 10.1, 10.2, 10.3).
    """
    grabber = _FrameGrabberSpy()
    vision = _VisionProviderSpy()
    observer = ScreenObserver(frame_grabber=grabber, vision_provider=vision)

    setup(observer)

    # Precondition: the observer reports it cannot capture.
    assert observer.can_capture is False

    result = observer.capture(now=now)

    # The capture attempt is refused with a disabled status ...
    assert isinstance(result, ObservationResult)
    assert result.status == CommandStatus.DISABLED
    # ... and, crucially, no screen content was ever grabbed or described.
    assert grabber.captured is False
    assert grabber.calls == 0
    assert vision.described is False
    # No captured frame is retained after a refused capture (Req 10.9).
    assert observer.current_frame is None


@settings(max_examples=200)
@given(now=_times)
def test_no_capture_while_kill_switched_even_with_consent(now: float) -> None:
    """A kill-switched agent never captures, even with consent recorded.

    When the agent state machine reports a disabled agent (Kill_Switch), the
    observer must refuse to capture regardless of consent, never touching the
    frame grabber (Req 8.3, 10.1).
    """
    grabber = _FrameGrabberSpy()
    vision = _VisionProviderSpy()
    machine = AgentStateMachine(initial_state=AgentState.ENABLED)
    observer = ScreenObserver(
        frame_grabber=grabber,
        vision_provider=vision,
        state_machine=machine,
    )

    # Explicit opt-in consent is recorded, so the consent gate alone would pass.
    observer.grant_consent()
    # But the Kill_Switch disables the whole agent.
    machine.activate_kill_switch(now=now)

    result = observer.capture(now=now)

    assert result.status == CommandStatus.DISABLED
    assert grabber.captured is False
    assert grabber.calls == 0
    assert vision.described is False
    assert observer.current_frame is None


@settings(max_examples=200)
@given(attempts=st.integers(min_value=1, max_value=10), now=_times)
def test_repeated_capture_attempts_without_consent_never_capture(
    attempts: int, now: float
) -> None:
    """Repeated capture attempts without consent never grab a single frame.

    The refusal is durable: no matter how many times capture is attempted while
    disabled/without consent, the frame grabber is never invoked (Req 10.1).
    """
    grabber = _FrameGrabberSpy()
    vision = _VisionProviderSpy()
    observer = ScreenObserver(frame_grabber=grabber, vision_provider=vision)

    for _ in range(attempts):
        result = observer.capture(now=now)
        assert result.status == CommandStatus.DISABLED

    assert grabber.captured is False
    assert grabber.calls == 0
    assert vision.described is False
