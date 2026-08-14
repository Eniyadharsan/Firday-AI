# Feature: music-search-optimization, Property 8: Exact Matches Rank Above Fuzzy Matches
"""
Property-based test for exact matches ranking above fuzzy matches.

Property 8: Exact Matches Rank Above Fuzzy Matches

For any mixed result set containing both exact-match results (match_score == 1.0)
and fuzzy-match results (match_score < 1.0), after sorting, all exact matches SHALL
appear before all fuzzy matches in the output list.

**Validates: Requirements 4.3**
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from friday.modules.music_models import TrackResult
from friday.modules.music_aggregator import MusicAggregator


# --- Strategies ---

# Strategy to generate a valid source name
_source_strategy = st.sampled_from(["youtube", "jiosaavn", "gaana"])


def _track_result_strategy(match_score_strategy: st.SearchStrategy[float]) -> st.SearchStrategy[TrackResult]:
    """Generate a TrackResult with a given match_score strategy."""
    return st.builds(
        TrackResult,
        id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
        title=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Zs"))).filter(lambda s: s.strip() != ""),
        artist=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Zs"))).filter(lambda s: s.strip() != ""),
        thumbnail_url=st.just("https://img.example.com/thumb.jpg"),
        source=_source_strategy,
        source_url=st.just("https://example.com/track"),
        duration_seconds=st.one_of(st.none(), st.integers(min_value=1, max_value=600)),
        is_devotional=st.booleans(),
        tradition=st.one_of(st.none(), st.sampled_from(["Hindu Bhajan", "Sikh Shabad", "Christian Hymn"])),
        match_score=match_score_strategy,
    )


# Strategy for exact match tracks (match_score == 1.0)
_exact_match_track = _track_result_strategy(st.just(1.0))

# Strategy for fuzzy match tracks (match_score < 1.0, but > 0.0 for meaningful results)
_fuzzy_match_track = _track_result_strategy(st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False))


# Combined strategy: at least one exact and at least one fuzzy track
_mixed_track_list = st.tuples(
    st.lists(_exact_match_track, min_size=1, max_size=10),
    st.lists(_fuzzy_match_track, min_size=1, max_size=10),
).map(lambda pair: pair[0] + pair[1])


# --- Helpers ---

class _FakeAdapter:
    """A fake adapter that returns pre-set results for testing."""

    def __init__(self, tracks: list[TrackResult]):
        self._tracks = tracks

    @property
    def source_name(self) -> str:
        return "test_source"

    def search(self, query: str, max_results: int) -> list[TrackResult]:
        return self._tracks[:max_results]

    def is_available(self) -> bool:
        return True


def _make_tracks_unique(tracks: list[TrackResult]) -> list[TrackResult]:
    """Ensure all tracks have unique title+artist combinations to avoid dedup."""
    unique_tracks = []
    seen = set()
    for i, track in enumerate(tracks):
        # Make each track unique by appending index to title
        unique_title = f"{track.title} {i}"
        key = (unique_title.lower().strip(), track.artist.lower().strip())
        if key not in seen:
            seen.add(key)
            unique_tracks.append(
                TrackResult(
                    id=f"track_{i}",
                    title=unique_title,
                    artist=track.artist,
                    thumbnail_url=track.thumbnail_url,
                    source=track.source,
                    source_url=track.source_url,
                    duration_seconds=track.duration_seconds,
                    is_devotional=track.is_devotional,
                    tradition=track.tradition,
                    match_score=track.match_score,
                )
            )
    return unique_tracks


# --- Property Test ---

@settings(max_examples=10, deadline=None)
@given(tracks=_mixed_track_list)
def test_exact_matches_rank_above_fuzzy_matches(tracks: list[TrackResult]):
    """
    Property 8: Exact Matches Rank Above Fuzzy Matches

    For any mixed result set containing both exact-match results (match_score == 1.0)
    and fuzzy-match results (match_score < 1.0), after sorting by the Music Aggregator's
    ranking logic, all exact matches SHALL appear before all fuzzy matches in the output.

    # Feature: music-search-optimization, Property 8: Exact Matches Rank Above Fuzzy Matches
    **Validates: Requirements 4.3**
    """
    # Ensure uniqueness so deduplication doesn't remove our test tracks
    unique_tracks = _make_tracks_unique(tracks)

    # We need at least one exact and one fuzzy after dedup
    has_exact = any(t.match_score == 1.0 for t in unique_tracks)
    has_fuzzy = any(t.match_score < 1.0 for t in unique_tracks)
    assume(has_exact and has_fuzzy)

    # Use the MusicAggregator's ranking logic
    adapter = _FakeAdapter(unique_tracks)
    aggregator = MusicAggregator([adapter], timeout=5.0)
    result = aggregator.search("test query", max_results=20)

    # Verify the property: all exact matches appear before all fuzzy matches
    found_fuzzy = False
    for track in result.results:
        if track.match_score < 1.0:
            found_fuzzy = True
        elif track.match_score == 1.0:
            # If we already found a fuzzy match, an exact match after it violates the property
            assert not found_fuzzy, (
                f"Exact match (score=1.0, title={track.title!r}) appeared after "
                f"a fuzzy match (score<1.0) in the ranked results. "
                f"Scores in order: {[t.match_score for t in result.results]}"
            )
