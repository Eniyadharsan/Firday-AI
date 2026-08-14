"""Unit test for the Kill_Switch / disable stopping the Screen_Observer.

Asserts two closely-related timing behaviors of the opt-in Screen_Observer:

    * WHEN the user disables screen awareness, THE Screen_Observer SHALL stop
      capturing within 1 second (Req 10.7). ``ScreenObserver.disable`` flips
      the enabled flag synchronously so any subsequent capture is refused with
      a ``DISABLED`` status and the frame grabber is never touched.
    * WHEN the user activates the Kill_Switch, THE Desktop_Agent SHALL stop the
      Screen_Observer within 1 second (Req 8.3). Activating the Kill_Switch on
      the shared :class:`AgentStateMachine` flips it to ``disabled``
      synchronously; the observer honors that disabled state and refuses to
      capture, and the activation (with its timestamp) is recorded in the
      Audit_Log (Req 8.4).

These are example (unit) tests. The real screen-capture and vision seams are
replaced by counting fakes so no real capture ever occurs, and elapsed time is
measured with ``time.monotonic()`` - a steady, non-decreasing clock unaffected
by wall-clock adjustments - between the stop request and the observer refusing
to capture. The measurement is asserted to be comfortably within the 1-second
bound.

Validates: Requirements 8.3, 10.7
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from friday.desktop_agent.models import (
    AgentState,
    AuditEntry,
    CommandStatus,
)
from friday.desktop_agent.screen_observer import CapturedFrame, ScreenObserver
from friday.desktop_agent.state import AgentStateMachine


# The 1-second stop bound shared by Req 8.3 and Req 10.7.
STOP_BOUND_SECONDS = 1.0


class _CountingFrameGrabber:
    """Fake FrameGrabber seam recording how many times it is invoked.

    The count lets the test prove the grabber is *never* touched once the
    observer is stopped: a stopped observer must not capture screen content.
    """

    def __init__(self, frame: CapturedFrame) -> None:
        self._frame = frame
        self.capture_calls = 0

    def capture(self) -> CapturedFrame:
        self.capture_calls += 1
        return self._frame


class _StubVisionProvider:
    """Fake VisionProvider seam returning a canned description.

    Never invoked while the observer is stopped; present only so a capture on
    an enabled observer has a working vision seam.
    """

    def __init__(self, description: str = "a description") -> None:
        self._description = description
        self.describe_calls = 0

    def describe(self, frame: CapturedFrame, prompt: str | None = None) -> str:
        self.describe_calls += 1
        return self._description


class _AuditSpy:
    """Collecting fake for the state machine's audit sink.

    Captures every :class:`AuditEntry` so the test can assert the Kill_Switch
    activation and its timestamp were recorded (Req 8.4).
    """

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def _make_observer(
    state_machine: AgentStateMachine | None = None,
) -> tuple[ScreenObserver, _CountingFrameGrabber, _StubVisionProvider]:
    """Build a consented, enabled observer wired to counting fakes."""
    grabber = _CountingFrameGrabber(CapturedFrame(image=b"\x89PNG-frame"))
    vision = _StubVisionProvider()
    observer = ScreenObserver(
        frame_grabber=grabber,
        vision_provider=vision,
        state_machine=state_machine,
    )
    # Screen awareness enabled with recorded opt-in consent so a capture would
    # otherwise proceed (Req 10.2).
    observer.grant_consent()
    return observer, grabber, vision


def test_disable_stops_screen_observer_capture_within_one_second() -> None:
    """Disabling screen awareness stops capture within 1s (Req 10.7).

    Validates: Requirements 10.7
    """
    observer, grabber, vision = _make_observer()

    # While enabled + consented the observer would capture.
    assert observer.can_capture is True

    # Disable screen awareness and measure how long until a capture is refused,
    # using a monotonic clock immune to wall-clock adjustments.
    start = time.monotonic()
    observer.disable(now=time.time())
    result = observer.capture(now=time.time())
    elapsed = time.monotonic() - start

    # The observer is stopped: it refuses to capture and never touches the
    # frame grabber or vision provider.
    assert observer.can_capture is False
    assert result.status is CommandStatus.DISABLED
    assert grabber.capture_calls == 0
    assert vision.describe_calls == 0

    # The stop takes effect well within the 1-second bound (Req 10.7).
    assert elapsed <= STOP_BOUND_SECONDS, (
        f"disable took {elapsed:.6f}s to stop the observer; "
        f"expected within {STOP_BOUND_SECONDS}s"
    )


def test_kill_switch_stops_screen_observer_within_one_second_and_records_activation() -> None:
    """Activating the Kill_Switch stops the observer within 1s and records it.

    The observer shares an :class:`AgentStateMachine`. Activating the
    Kill_Switch flips the machine to ``disabled`` synchronously; the observer
    honors that state and refuses to capture, and the activation + timestamp
    are recorded in the Audit_Log.

    Validates: Requirements 8.3, 8.4
    """
    audit = _AuditSpy()
    machine = AgentStateMachine(
        audit_sink=audit.append, initial_state=AgentState.ENABLED
    )
    observer, grabber, vision = _make_observer(state_machine=machine)

    # The observer would capture before the Kill_Switch fires.
    assert observer.can_capture is True

    # Activate the Kill_Switch and measure the time until the observer refuses
    # to capture, using a monotonic clock.
    now = 1_700_000_000.0
    start = time.monotonic()
    machine.activate_kill_switch(now=now)
    # The observer also stops in direct response to the Kill_Switch.
    observer.stop_for_kill_switch(now=now)
    result = observer.capture(now=time.time())
    elapsed = time.monotonic() - start

    # The observer is stopped: no capture occurs and the result is DISABLED
    # (Req 8.3). The state machine reports the disabled agent.
    assert machine.is_disabled is True
    assert result.status is CommandStatus.DISABLED
    assert grabber.capture_calls == 0
    assert vision.describe_calls == 0
    assert elapsed <= STOP_BOUND_SECONDS, (
        f"kill-switch took {elapsed:.6f}s to stop the observer; "
        f"expected within {STOP_BOUND_SECONDS}s"
    )

    # The Kill_Switch activation and its timestamp are recorded (Req 8.4).
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.event_type == "kill_switch"
    assert entry.outcome == "disabled"
    expected_timestamp = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    assert entry.timestamp == expected_timestamp


def test_kill_switch_disabled_state_alone_refuses_capture() -> None:
    """A disabled state machine alone is enough to refuse capture (Req 8.3).

    Even without calling ``stop_for_kill_switch`` on the observer, a disabled
    shared state machine causes the observer to decline capture, so the
    Kill_Switch reliably stops screen observation.

    Validates: Requirements 8.3
    """
    audit = _AuditSpy()
    machine = AgentStateMachine(
        audit_sink=audit.append, initial_state=AgentState.ENABLED
    )
    observer, grabber, vision = _make_observer(state_machine=machine)

    machine.activate_kill_switch(now=1_700_000_100.0)

    # The observer's own enabled/consent flags are untouched here, yet the
    # disabled agent state gates the capture (Req 8.3).
    start = time.monotonic()
    result = observer.capture(now=time.time())
    elapsed = time.monotonic() - start

    assert result.status is CommandStatus.DISABLED
    assert grabber.capture_calls == 0
    assert vision.describe_calls == 0
    assert elapsed <= STOP_BOUND_SECONDS
