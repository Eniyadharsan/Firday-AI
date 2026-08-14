# Feature: music-search-optimization, Property 10: Aggregation Deduplication and Bounds
"""Property-based test for aggregation deduplication and bounds.

Validates: Requirements 5.2, 5.4

Tests that the Music Aggregator's merged output:
  (a) contains no duplicate entries (case-insensitive title+artist),
  (b) contains at most 20 results, and
  (c) includes a non-empty source field on every result.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.modules.music_aggregator import MusicAggregator
from friday.modules.music_models import TrackResult


# --- Strategies ---

# Generate non-empty source names from known sources (with occasional custom ones)
_source_strategy = st.sampled_from(["youtube", "jiosaavn", "gaana"])

# Generate track titles that may create duplicates via case/whitespace variation
_title_base = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    min_size=1,
    max_size=50,
)


def _case_variant(s: str) -> st.SearchStrategy[str]:
    """Produce case/whitespace variations of a string."""
    return st.sampled_from([
        s,
        s.upper(),
        s.lower(),
        f"  {s}  ",
        s.title(),
    ])


@st.composite
def track_result_strategy(draw: st.DrawFn) -> TrackResult:
    """Generate a random TrackResult with valid fields."""
    title = draw(_title_base)
    artist = draw(_title_base)
    source = draw(_source_strategy)
    match_score = draw(st.floats(min_value=0.0, max_value=1.0))
    track_id = draw(st.text(min_size=1, max_size=20))

    return TrackResult(
        id=track_id,
        title=title,
        artist=artist,
        thumbnail_url="https://img.example.com/thumb.jpg",
        source=source,
        source_url=f"https://{source}.com/track/{track_id}",
        duration_seconds=draw(st.one_of(st.none(), st.integers(min_value=1, max_value=600))),
        is_devotional=draw(st.booleans()),
        tradition=draw(st.one_of(st.none(), st.text(min_size=1, max_size=30))),
        match_score=match_score,
    )


@st.composite
def track_list_with_duplicates(draw: st.DrawFn) -> list[TrackResult]:
    """Generate a list of TrackResult with intentional duplicates.

    Some tracks share the same title+artist but with case/whitespace variations,
    simulating duplicates coming from different sources.
    """
    # Generate base tracks
    base_tracks = draw(st.lists(track_result_strategy(), min_size=0, max_size=40))

    # Optionally duplicate some tracks with case/whitespace variations
    duplicated_tracks: list[TrackResult] = []
    for track in base_tracks:
        duplicated_tracks.append(track)
        # 40% chance to create a duplicate with case variation
        if draw(st.booleans()) and draw(st.integers(min_value=1, max_value=10)) <= 4:
            variant_title = draw(st.sampled_from([
                track.title.upper(),
                track.title.lower(),
                f"  {track.title}  ",
            ]))
            variant_artist = draw(st.sampled_from([
                track.artist.upper(),
                track.artist.lower(),
                f"  {track.artist}  ",
            ]))
            # Different source to test cross-source dedup
            other_source = draw(st.sampled_from(
                [s for s in ["youtube", "jiosaavn", "gaana"] if s != track.source]
            ))
            dup = TrackResult(
                id=f"dup_{track.id}",
                title=variant_title,
                artist=variant_artist,
                thumbnail_url=track.thumbnail_url,
                source=other_source,
                source_url=f"https://{other_source}.com/track/dup",
                duration_seconds=track.duration_seconds,
                is_devotional=track.is_devotional,
                tradition=track.tradition,
                match_score=draw(st.floats(min_value=0.0, max_value=1.0)),
            )
            duplicated_tracks.append(dup)

    return duplicated_tracks


def _make_adapter_from_tracks(
    source_name: str, tracks: list[TrackResult]
) -> MagicMock:
    """Create a mock adapter that returns the given tracks."""
    adapter = MagicMock()
    type(adapter).source_name = PropertyMock(return_value=source_name)
    adapter.is_available.return_value = True
    adapter.search.return_value = tracks
    return adapter


# --- Property Test ---


@given(tracks=track_list_with_duplicates())
@settings(max_examples=10, deadline=None)
def test_aggregation_deduplication_and_bounds(tracks: list[TrackResult]) -> None:
    """**Validates: Requirements 5.2, 5.4**

    For any collection of result lists from multiple music sources (with
    potential duplicates defined by case-insensitive title + artist equality),
    the aggregator's merged output SHALL:
      (a) contain no duplicate entries,
      (b) contain at most 20 results, and
      (c) include a non-empty source field on every result.
    """
    # Split tracks by source to simulate multiple adapters
    source_groups: dict[str, list[TrackResult]] = {}
    for track in tracks:
        source_groups.setdefault(track.source, []).append(track)

    # Create adapters for each source group
    adapters = [
        _make_adapter_from_tracks(source, group)
        for source, group in source_groups.items()
    ]

    # If no tracks generated, use a single empty adapter
    if not adapters:
        adapters = [_make_adapter_from_tracks("youtube", [])]

    aggregator = MusicAggregator(adapters, timeout=5.0)
    result = aggregator.search("test query", max_results=20)

    # (a) No duplicates: case-insensitive title+artist uniqueness
    seen_keys: set[tuple[str, str]] = set()
    for track in result.results:
        key = (track.title.lower().strip(), track.artist.lower().strip())
        assert key not in seen_keys, (
            f"Duplicate found: title={track.title!r}, artist={track.artist!r}"
        )
        seen_keys.add(key)

    # (b) At most 20 results
    assert len(result.results) <= 20, (
        f"Expected at most 20 results, got {len(result.results)}"
    )

    # (c) Every result has a non-empty source field
    for track in result.results:
        assert track.source, (
            f"Track has empty source: title={track.title!r}, artist={track.artist!r}"
        )
