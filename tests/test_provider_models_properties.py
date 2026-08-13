"""Property-based tests for provider data models.

Property 8: Status Color Mapping
- For any ProviderStatus value, get_status_color SHALL return exactly one of:
  "green" for OPERATIONAL, "yellow" for DEGRADED, "red" for UNAVAILABLE,
  "gray" for NOT_CONFIGURED.

Validates: Requirements 8.3
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from friday.modules.providers.models import ProviderStatus, get_status_color

# The exact, expected status-to-color mapping per the acceptance criteria.
EXPECTED_COLORS = {
    ProviderStatus.OPERATIONAL: "green",
    ProviderStatus.DEGRADED: "yellow",
    ProviderStatus.UNAVAILABLE: "red",
    ProviderStatus.NOT_CONFIGURED: "gray",
}

VALID_COLORS = {"green", "yellow", "red", "gray"}


@given(status=st.sampled_from(list(ProviderStatus)))
def test_status_color_mapping_is_exact(status: ProviderStatus) -> None:
    """Each status maps to exactly the expected color.

    Validates: Requirements 8.3
    """
    assert get_status_color(status) == EXPECTED_COLORS[status]


@given(status=st.sampled_from(list(ProviderStatus)))
def test_status_color_is_always_valid(status: ProviderStatus) -> None:
    """The output is always one of the four valid colors.

    Validates: Requirements 8.3
    """
    assert get_status_color(status) in VALID_COLORS


@given(status=st.sampled_from(list(ProviderStatus)))
def test_status_color_mapping_is_total(status: ProviderStatus) -> None:
    """Every enum member maps to a non-empty color string (mapping is total).

    Validates: Requirements 8.3
    """
    color = get_status_color(status)
    assert isinstance(color, str)
    assert color != ""


def test_status_color_covers_all_members() -> None:
    """Sanity check that the test's expected map covers every enum member.

    Guards against new ProviderStatus members being added without an
    accompanying color mapping.

    Validates: Requirements 8.3
    """
    assert set(ProviderStatus) == set(EXPECTED_COLORS)
