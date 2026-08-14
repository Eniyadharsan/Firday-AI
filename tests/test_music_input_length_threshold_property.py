# Feature: music-search-optimization, Property 1: Input Length Threshold Controls Suggestion Visibility
"""
Property-based tests for the Autocomplete Service input length threshold.

Property 1: Input Length Threshold Controls Suggestion Visibility
For any input string, the autocomplete service SHALL return suggestions only
when the string length is >= 2 characters, and SHALL return an empty list
(signaling "hide") for any string with length < 2.

**Validates: Requirements 1.1, 1.5**
"""

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.modules.music_aggregator import MusicAggregator
from friday.modules.music_autocomplete import AutocompleteService
from friday.modules.music_models import TrackResult


def _make_track(index: int) -> TrackResult:
    """Create a minimal TrackResult for testing."""
    return TrackResult(
        id=f"track-{index}",
        title=f"Test Song {index}",
        artist=f"Artist {index}",
        thumbnail_url=f"https://example.com/thumb{index}.jpg",
        source="youtube",
        source_url=f"https://example.com/track{index}",
        match_score=0.9,
    )


def _create_service_with_mock(tracks: list[TrackResult] | None = None) -> AutocompleteService:
    """Create an AutocompleteService with a mocked MusicAggregator.

    The mock's quick_search returns the provided tracks (default: 3 tracks).
    """
    mock_aggregator = MagicMock(spec=MusicAggregator)
    if tracks is None:
        tracks = [_make_track(i) for i in range(3)]
    mock_aggregator.quick_search.return_value = tracks
    return AutocompleteService(aggregator=mock_aggregator, cache_ttl=300)


# --- Strategies ---

# Short queries: length 0 or 1 (should always return empty)
_short_query = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),  # Exclude surrogates
    min_size=0,
    max_size=1,
)

# Queries with length >= 2 (should proceed to return suggestions)
_long_enough_query = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),  # Exclude surrogates
    min_size=2,
    max_size=100,
)


class TestInputLengthThreshold:
    """
    Property 1: Input Length Threshold Controls Suggestion Visibility

    Queries with length < 2 always return an empty list.
    Queries with length >= 2 proceed to return suggestions from the aggregator.

    **Validates: Requirements 1.1, 1.5**
    """

    @settings(max_examples=10, deadline=None)
    @given(query=_short_query)
    def test_short_queries_return_empty_list(self, query: str):
        """
        For any query with length < 2, the autocomplete service SHALL return
        an empty list (no suggestions), regardless of query content.

        # Feature: music-search-optimization, Property 1: Input Length Threshold Controls Suggestion Visibility
        **Validates: Requirements 1.1, 1.5**
        """
        service = _create_service_with_mock()
        result = service.suggest(query)

        assert result == [], (
            f"Expected empty list for short query (len={len(query)}), "
            f"got {len(result)} suggestions.\n"
            f"  Query: {query!r}"
        )

    @settings(max_examples=10, deadline=None)
    @given(query=_long_enough_query)
    def test_long_enough_queries_proceed_to_return_suggestions(self, query: str):
        """
        For any query with length >= 2, the autocomplete service SHALL proceed
        to fetch and return suggestions (non-empty when aggregator has results).

        # Feature: music-search-optimization, Property 1: Input Length Threshold Controls Suggestion Visibility
        **Validates: Requirements 1.1, 1.5**
        """
        service = _create_service_with_mock()
        result = service.suggest(query)

        # With a mock aggregator returning 3 tracks, we expect suggestions
        assert len(result) > 0, (
            f"Expected suggestions for query with length >= 2 (len={len(query)}), "
            f"but got empty list.\n"
            f"  Query: {query!r}"
        )

