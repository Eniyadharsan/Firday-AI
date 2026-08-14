# Feature: music-search-optimization, Property 2: Suggestion Output Invariants
"""
Property-based tests for the Autocomplete Service suggestion output invariants.

Property 2: Suggestion Output Invariants
For any list of raw autocomplete results of arbitrary size, the formatted output
SHALL contain at most 8 suggestions, with each suggestion's title truncated to
at most 60 characters and each artist name truncated to at most 40 characters.

**Validates: Requirements 1.3**
"""

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.modules.music_aggregator import MusicAggregator
from friday.modules.music_autocomplete import AutocompleteService
from friday.modules.music_models import TrackResult


# --- Strategies ---

# Generate arbitrary-length strings for titles and artists (including very long ones)
_arbitrary_title = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),  # Exclude surrogates
    min_size=0,
    max_size=300,
)

_arbitrary_artist = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),  # Exclude surrogates
    min_size=0,
    max_size=200,
)


def _track_result_strategy():
    """Strategy to generate a TrackResult with arbitrary-length title and artist."""
    return st.builds(
        TrackResult,
        id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"))),
        title=_arbitrary_title,
        artist=_arbitrary_artist,
        thumbnail_url=st.just("https://example.com/thumb.jpg"),
        source=st.sampled_from(["youtube", "jiosaavn", "gaana"]),
        source_url=st.just("https://example.com/track"),
        match_score=st.floats(min_value=0.0, max_value=1.0),
    )


# Generate arbitrary-length lists of TrackResults (0 to 30 items)
_track_list_strategy = st.lists(
    _track_result_strategy(),
    min_size=0,
    max_size=30,
)

# A query that is long enough to trigger suggestion lookup (>= 2 chars)
_valid_query = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=2,
    max_size=50,
)


class TestSuggestionOutputInvariants:
    """
    Property 2: Suggestion Output Invariants

    Output never exceeds 8 suggestions, titles are <= 60 chars,
    and artist names are <= 40 chars.

    **Validates: Requirements 1.3**
    """

    @settings(max_examples=10, deadline=None)
    @given(tracks=_track_list_strategy, query=_valid_query)
    def test_output_respects_max_suggestions_and_truncation(
        self, tracks: list[TrackResult], query: str
    ):
        """
        For any arbitrary-length list of raw track results returned by the
        aggregator (with arbitrarily long title and artist strings), the
        AutocompleteService.suggest() output SHALL:
        - Contain at most 8 suggestions
        - Have each suggestion title at most 60 characters
        - Have each suggestion artist at most 40 characters

        # Feature: music-search-optimization, Property 2: Suggestion Output Invariants
        **Validates: Requirements 1.3**
        """
        # Mock the aggregator to return the generated tracks
        mock_aggregator = MagicMock(spec=MusicAggregator)
        mock_aggregator.quick_search.return_value = tracks
        service = AutocompleteService(aggregator=mock_aggregator, cache_ttl=300)

        suggestions = service.suggest(query)

        # Invariant 1: At most 8 suggestions
        assert len(suggestions) <= 8, (
            f"Expected at most 8 suggestions, got {len(suggestions)}.\n"
            f"  Query: {query!r}\n"
            f"  Input tracks count: {len(tracks)}"
        )

        # Invariant 2 & 3: Title and artist length constraints
        for i, suggestion in enumerate(suggestions):
            assert len(suggestion.title) <= 60, (
                f"Suggestion[{i}].title exceeds 60 chars "
                f"(len={len(suggestion.title)}).\n"
                f"  Title: {suggestion.title!r}"
            )
            assert len(suggestion.artist) <= 40, (
                f"Suggestion[{i}].artist exceeds 40 chars "
                f"(len={len(suggestion.artist)}).\n"
                f"  Artist: {suggestion.artist!r}"
            )
