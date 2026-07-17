# Feature: music-search-optimization, Property 6: Devotional Ranking Guarantee
"""
Property-based test for devotional ranking guarantee.

Property 6: Devotional Ranking Guarantee

For any query containing a devotional keyword and a mixed result set containing
both devotional and non-devotional tracks (with sufficient devotional tracks
available), the ranking function SHALL place devotional results such that at
least 70% of the first 10 results have `is_devotional == True`, and every
devotional result SHALL have a non-null `tradition` field.

**Validates: Requirements 3.1, 3.3, 3.4**
"""

from unittest.mock import MagicMock, PropertyMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from friday.modules.music_aggregator import MusicAggregator
from friday.modules.music_models import SearchContext, TrackResult


# --- Strategies ---

TRADITIONS = [
    "Hindu Bhajan",
    "Sikh Shabad",
    "Islamic Naat",
    "Christian Hymn",
    "Christian Gospel",
    "Hindu Kirtan",
    "Hindu Stotram",
    "Tamil Paadal",
    "Tamil Keerthanai",
]

SOURCES = ["youtube", "jiosaavn", "gaana"]


def _track_id_strategy():
    """Generate a unique track ID."""
    return st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
        min_size=8,
        max_size=16,
    )


def _devotional_track_strategy():
    """Generate a devotional track with non-null tradition."""
    return st.builds(
        TrackResult,
        id=_track_id_strategy(),
        title=st.text(min_size=3, max_size=50).filter(lambda s: s.strip()),
        artist=st.text(min_size=2, max_size=30).filter(lambda s: s.strip()),
        thumbnail_url=st.just("https://img.example.com/thumb.jpg"),
        source=st.sampled_from(SOURCES),
        source_url=st.just("https://example.com/track"),
        duration_seconds=st.one_of(st.none(), st.integers(min_value=30, max_value=600)),
        is_devotional=st.just(True),
        tradition=st.sampled_from(TRADITIONS),
        match_score=st.floats(min_value=0.1, max_value=1.0),
    )


def _non_devotional_track_strategy():
    """Generate a non-devotional track."""
    return st.builds(
        TrackResult,
        id=_track_id_strategy(),
        title=st.text(min_size=3, max_size=50).filter(lambda s: s.strip()),
        artist=st.text(min_size=2, max_size=30).filter(lambda s: s.strip()),
        thumbnail_url=st.just("https://img.example.com/thumb.jpg"),
        source=st.sampled_from(SOURCES),
        source_url=st.just("https://example.com/track"),
        duration_seconds=st.one_of(st.none(), st.integers(min_value=30, max_value=600)),
        is_devotional=st.just(False),
        tradition=st.just(None),
        match_score=st.floats(min_value=0.1, max_value=1.0),
    )


def _mixed_track_list_strategy():
    """Generate a mixed list with sufficient devotional tracks (>=7) and some non-devotional.

    We need at least 7 devotional tracks to meet the 70% threshold for top 10,
    and enough total tracks to fill at least 10 results.
    """
    return st.tuples(
        st.lists(_devotional_track_strategy(), min_size=7, max_size=15),
        st.lists(_non_devotional_track_strategy(), min_size=3, max_size=10),
    )


def _make_mock_adapter(source_name: str, results: list[TrackResult]) -> MagicMock:
    """Create a mock adapter returning the given results."""
    adapter = MagicMock()
    type(adapter).source_name = PropertyMock(return_value=source_name)
    adapter.is_available.return_value = True
    adapter.search.return_value = results
    return adapter


# --- Property Test ---


@settings(max_examples=100, deadline=None)
@given(track_lists=_mixed_track_list_strategy())
def test_devotional_ranking_guarantee(track_lists):
    """
    Property 6: Devotional Ranking Guarantee

    When a devotional query has sufficient devotional tracks (>=7),
    at least 70% of the first 10 results have `is_devotional == True`
    and all devotional results have non-null `tradition`.

    # Feature: music-search-optimization, Property 6: Devotional Ranking Guarantee
    **Validates: Requirements 3.1, 3.3, 3.4**
    """
    devotional_tracks, non_devotional_tracks = track_lists
    all_tracks = devotional_tracks + non_devotional_tracks

    # Ensure we have enough tracks for a meaningful test
    assume(len(all_tracks) >= 10)
    assume(len(devotional_tracks) >= 7)

    # Ensure all tracks have unique title+artist combos to avoid deduplication
    # removing tracks we need for the test
    seen_keys = set()
    unique_tracks = []
    for track in all_tracks:
        key = (track.title.lower().strip(), track.artist.lower().strip())
        if key not in seen_keys:
            seen_keys.add(key)
            unique_tracks.append(track)
    all_tracks = unique_tracks

    # After dedup, re-check we still have sufficient tracks
    devotional_count_in_input = sum(1 for t in all_tracks if t.is_devotional)
    non_devotional_count_in_input = sum(1 for t in all_tracks if not t.is_devotional)
    assume(devotional_count_in_input >= 7)
    assume(len(all_tracks) >= 10)

    # Set up aggregator with a single mock adapter returning all tracks
    adapter = _make_mock_adapter("youtube", all_tracks)
    aggregator = MusicAggregator([adapter])

    # Create a devotional search context
    context = SearchContext(
        original_query="bhajan devotional songs",
        normalized_query="bhajan devotional songs",
        is_devotional=True,
        devotional_tradition="Hindu Bhajan",
        devotional_keywords_found=["bhajan"],
    )

    # Execute search with devotional context
    result = aggregator.search("bhajan devotional songs", context=context)

    # Property assertion 1: >=70% of first 10 results are devotional
    top_10 = result.results[:10]
    devotional_in_top_10 = sum(1 for t in top_10 if t.is_devotional)

    assert devotional_in_top_10 >= 7, (
        f"Expected >=70% devotional in top 10, got {devotional_in_top_10}/10. "
        f"Input had {devotional_count_in_input} devotional tracks."
    )

    # Property assertion 2: All devotional results have non-null tradition
    for i, track in enumerate(result.results):
        if track.is_devotional:
            assert track.tradition is not None, (
                f"Devotional track at index {i} has tradition=None. "
                f"Title: {track.title!r}, Source: {track.source}"
            )
