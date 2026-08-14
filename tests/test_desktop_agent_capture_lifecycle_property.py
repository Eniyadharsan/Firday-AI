# Feature: friday-desktop-agent, Property 23: Capture lifecycle and retention
"""Property-based tests for the Screen_Observer capture lifecycle and retention.

Property 23: Capture lifecycle and retention
For any screen capture that is sent to the Vision_Provider, the Screen_Observer
SHALL record the capture event with a timestamp, SHALL retain the captured
content only until the Vision_Provider response resolves, and SHALL discard the
content afterward; if the Vision_Provider request fails, the Screen_Observer
SHALL additionally return a vision-unavailable status and record the failure.

Validates: Requirements 10.5, 10.8, 10.9

The real screen-capture and vision seams are replaced by fakes following the
``tests/_adapter_fakes.py`` convention: a fake ``FrameGrabber`` produces an
in-memory frame, and a fake ``VisionProvider`` either returns a canned
description (success) or raises (failure). A collecting audit fake records the
capture and vision-failure events. The vision fake inspects the observer's
retained frame *during* the call so the test can prove the frame is held only
for the duration of the response and discarded afterward.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.audit import ISO_TIMESTAMP_FORMAT
from friday.desktop_agent.models import CommandStatus
from friday.desktop_agent.screen_observer import (
    CapturedFrame,
    ScreenObserver,
)


def _expected_iso(now: float) -> str:
    """Mirror the observer's epoch->ISO timestamp conversion for assertions."""
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime(ISO_TIMESTAMP_FORMAT)


class _FakeFrameGrabber:
    """Fake FrameGrabber seam that returns a canned in-memory frame.

    Records how many times ``capture`` was invoked so the test can confirm the
    grabber is only touched after the consent/enabled gates pass.
    """

    def __init__(self, frame: CapturedFrame) -> None:
        self._frame = frame
        self.capture_calls = 0

    def capture(self) -> CapturedFrame:
        self.capture_calls += 1
        return self._frame


class _FakeVisionProvider:
    """Fake VisionProvider seam returning a description or raising on failure.

    When invoked it inspects the observer's ``current_frame`` so the test can
    verify the captured content is retained *for the duration of the call*
    (Req 10.9). On ``should_fail`` it raises to simulate a Vision_Provider
    failure (Req 10.5).
    """

    def __init__(
        self,
        observer_ref: list["ScreenObserver"],
        description: str,
        should_fail: bool,
        error_message: str,
    ) -> None:
        self._observer_ref = observer_ref
        self._description = description
        self._should_fail = should_fail
        self._error_message = error_message
        # Set during the call to record whether the frame was retained.
        self.frame_retained_during_call: Optional[bool] = None
        self.received_frame: Optional[CapturedFrame] = None

    def describe(self, frame: CapturedFrame, prompt: Optional[str] = None) -> str:
        observer = self._observer_ref[0]
        # The observer must be holding exactly the in-flight frame right now.
        self.frame_retained_during_call = observer.current_frame is frame
        self.received_frame = frame
        if self._should_fail:
            raise RuntimeError(self._error_message)
        return self._description


class _AuditSpy:
    """Collecting fake for the audit seam used by the Screen_Observer.

    Captures the capture-event timestamps and vision-failure records so the
    test can assert the capture event is recorded with a timestamp (Req 10.8)
    and the failure is recorded on a Vision_Provider error (Req 10.5).
    """

    def __init__(self) -> None:
        self.capture_timestamps: list[Optional[str]] = []
        self.vision_failures: list[tuple[str, Optional[str]]] = []

    def record_capture(self, timestamp: Optional[str] = None):
        self.capture_timestamps.append(timestamp)

    def record_vision_failure(self, reason: str, timestamp: Optional[str] = None):
        self.vision_failures.append((reason, timestamp))


# -- Generators ---------------------------------------------------------------

# Raw frame bytes; at least one byte so the frame is non-empty.
_frame_bytes = st.binary(min_size=1, max_size=64)
_mime_types = st.sampled_from(["image/png", "image/jpeg", "image/webp"])

# Vision descriptions returned on success and error messages produced on
# failure. Both non-empty so the observer sees a meaningful response/error.
_descriptions = st.text(min_size=1, max_size=64)
_error_messages = st.text(min_size=1, max_size=64)

# Whether the Vision_Provider request succeeds or fails this iteration.
_should_fail = st.booleans()

# Epoch-second range kept finite/positive so ISO conversion is well-behaved
# (roughly year 2001..2035).
_times = st.floats(
    min_value=1_000_000_000.0,
    max_value=2_000_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)


@settings(max_examples=200)
@given(
    image=_frame_bytes,
    mime_type=_mime_types,
    description=_descriptions,
    error_message=_error_messages,
    should_fail=_should_fail,
    now=_times,
)
def test_capture_lifecycle_records_retains_and_discards(
    image: bytes,
    mime_type: str,
    description: str,
    error_message: str,
    should_fail: bool,
    now: float,
) -> None:
    """A capture sent to the Vision_Provider is recorded, retained, discarded.

    For any capture that reaches the Vision_Provider:
      * the capture event is recorded with a timestamp (Req 10.8),
      * the captured content is retained only for the duration of the
        Vision_Provider call and discarded afterward (Req 10.9),
      * on a Vision_Provider failure the observer returns ``vision-unavailable``
        and records the failure (Req 10.5).

    Both success and failure vision responses are generated.
    """
    frame = CapturedFrame(image=image, mime_type=mime_type)
    grabber = _FakeFrameGrabber(frame)
    observer_ref: list[ScreenObserver] = []
    vision = _FakeVisionProvider(
        observer_ref=observer_ref,
        description=description,
        should_fail=should_fail,
        error_message=error_message,
    )
    audit = _AuditSpy()

    observer = ScreenObserver(
        frame_grabber=grabber,
        vision_provider=vision,
        audit=audit,
    )
    observer_ref.append(observer)

    # The capture must reach the Vision_Provider, so screen awareness must be
    # enabled with recorded opt-in consent.
    observer.grant_consent()

    result = observer.capture(now=now)

    # The frame reached the Vision_Provider (the capture was actually sent).
    assert grabber.capture_calls == 1
    assert vision.received_frame is frame

    # Req 10.8: the capture event is recorded with the expected timestamp.
    assert audit.capture_timestamps == [_expected_iso(now)]

    # Req 10.9: the content was retained *during* the call and discarded after.
    assert vision.frame_retained_during_call is True
    assert observer.current_frame is None

    if should_fail:
        # Req 10.5: failure yields vision-unavailable and a recorded failure.
        assert result.status == CommandStatus.VISION_UNAVAILABLE
        assert result.description is None
        assert len(audit.vision_failures) == 1
        failure_reason, failure_ts = audit.vision_failures[0]
        assert error_message in failure_reason
        assert failure_ts == _expected_iso(now)
    else:
        # Success returns the description and records no failure.
        assert result.status == CommandStatus.SUCCESS
        assert result.description == description
        assert audit.vision_failures == []


@settings(max_examples=100)
@given(
    image=_frame_bytes,
    error_message=_error_messages,
    now=_times,
)
def test_frame_discarded_even_when_vision_fails(
    image: bytes,
    error_message: str,
    now: float,
) -> None:
    """A Vision_Provider failure still discards the retained frame (Req 10.9).

    The retention guarantee holds on the error path too: after a failed vision
    call the observer must not be holding any captured content.
    """
    frame = CapturedFrame(image=image)
    grabber = _FakeFrameGrabber(frame)
    observer_ref: list[ScreenObserver] = []
    vision = _FakeVisionProvider(
        observer_ref=observer_ref,
        description="",
        should_fail=True,
        error_message=error_message,
    )
    audit = _AuditSpy()

    observer = ScreenObserver(
        frame_grabber=grabber,
        vision_provider=vision,
        audit=audit,
    )
    observer_ref.append(observer)
    observer.grant_consent()

    result = observer.capture(now=now)

    assert result.status == CommandStatus.VISION_UNAVAILABLE
    # Retained during the call, discarded afterward regardless of the failure.
    assert vision.frame_retained_during_call is True
    assert observer.current_frame is None
    # Capture recorded before the failure; failure recorded after (Req 10.5, 10.8).
    assert audit.capture_timestamps == [_expected_iso(now)]
    assert len(audit.vision_failures) == 1
