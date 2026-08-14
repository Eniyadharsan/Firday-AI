"""Property-based tests for the media-control volume bounds invariant.

Property 10: Media volume is bounded
- For any requested media volume value, the applied volume level SHALL lie
  within the inclusive range 0 to 100.

The Parameter Validator exposes ``clamp_volume`` (friday/desktop_agent/
validator.py), which the Command Executor uses to constrain any requested
media-control volume before applying it (Req 4.4). This property exercises
``clamp_volume`` across arbitrary requested values -- in-range, out-of-range
(negative and above 100), and boundary values -- and asserts the applied
level is always within ``[VOLUME_MIN, VOLUME_MAX]``.

Validates: Requirements 4.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.validator import VOLUME_MAX, VOLUME_MIN, clamp_volume


# A generator covering the full space of requested volume values: integers and
# finite floats spanning far below 0 and far above 100, plus the exact
# boundaries, so the property stresses clamping in both directions.
_requested_volume = st.one_of(
    st.integers(min_value=-10_000, max_value=10_000),
    st.floats(
        min_value=-10_000.0,
        max_value=10_000.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    st.sampled_from([VOLUME_MIN, VOLUME_MAX, VOLUME_MIN - 1, VOLUME_MAX + 1]),
)


# Feature: friday-desktop-agent, Property 10: Media volume is bounded
@settings(max_examples=200)
@given(requested=_requested_volume)
def test_applied_media_volume_is_bounded(requested: float) -> None:
    """For any requested volume, the applied level lies within [0, 100].

    Validates: Requirements 4.4
    """
    applied = clamp_volume(requested)

    assert VOLUME_MIN <= applied <= VOLUME_MAX
    # The applied level is an integer volume step within the allowed range.
    assert isinstance(applied, int)


# Feature: friday-desktop-agent, Property 10: Media volume is bounded
@settings(max_examples=100)
@given(requested=st.integers(min_value=VOLUME_MIN, max_value=VOLUME_MAX))
def test_in_range_volume_is_preserved(requested: int) -> None:
    """A requested level already within [0, 100] is applied unchanged.

    This confirms clamping only constrains out-of-range values and does not
    distort valid requests.

    Validates: Requirements 4.4
    """
    assert clamp_volume(requested) == requested
