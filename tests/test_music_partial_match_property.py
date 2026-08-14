# Feature: music-search-optimization, Property 9: Partial Match Constraints
"""
Property-based test for partial match constraints.

Property 9: Partial Match Constraints
For any query and catalog, when the query shares a contiguous substring of >= 3
characters with catalog entries, the fuzzy_search function SHALL return at most
10 partial matches, and those matches SHALL be sorted in descending order by
match length (score).

**Validates: Requirements 4.4**
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from friday.modules.music_catalog import CatalogCache
from friday.modules.music_fuzzy import FuzzyMatcher
from friday.modules.music_models import TrackResult


# Strategy for generating catalog entry strings (track titles/artists)
_catalog_entry = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        blacklist_characters=("\x00",),
    ),
    min_size=4,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 4)


# Strategy to generate a list of catalog entries (simulating a populated catalog)
_catalog_entries = st.lists(
    _catalog_entry,
    min_size=5,
    max_size=30,
)


# Strategy for query strings that share a substring with at least one catalog entry
# We generate a query by picking a substring from one of the catalog entries
@st.composite
def query_with_shared_substring(draw):
    """Generate a catalog list and a query that shares a >= 3 char substring with at least one entry."""
    entries = draw(_catalog_entries)
    # Pick one entry to derive the query from
    source_entry = draw(st.sampled_from(entries))
    # Extract a contiguous substring of length >= 3 from the source entry
    stripped = source_entry.strip()
    assume(len(stripped) >= 3)
    max_start = len(stripped) - 3
    start = draw(st.integers(min_value=0, max_value=max_start))
    # Substring length between 3 and remaining characters
    max_length = len(stripped) - start
    length = draw(st.integers(min_value=3, max_value=max_length))
    query = stripped[start:start + length]
    assume(len(query.strip()) >= 3)
    return entries, query


def _make_track(title: str, idx: int) -> TrackResult:
    """Create a minimal TrackResult for catalog population."""
    return TrackResult(
        id=f"track_{idx}",
        title=title,
        artist=f"Artist {idx}",
        thumbnail_url=f"https://example.com/thumb_{idx}.jpg",
        source="test",
        source_url=f"https://example.com/track_{idx}",
        match_score=0.5,
    )


@settings(max_examples=10, deadline=None)
@given(data=query_with_shared_substring())
def test_partial_match_constraints(data):
    """
    Property 9: Partial Match Constraints

    Test that fuzzy_search() returns at most 10 partial matches, sorted by
    descending match length (score).

    For any query and catalog, when the query shares a contiguous substring of
    >= 3 characters with catalog entries, the fuzzy_search function SHALL return
    at most 10 partial matches, and those matches SHALL be sorted in descending
    order by match length (score).

    # Feature: music-search-optimization, Property 9: Partial Match Constraints
    **Validates: Requirements 4.4**
    """
    entries, query = data

    # Set up catalog cache and populate it
    cache = CatalogCache(max_entries=10000, ttl=3600)
    tracks = [_make_track(entry, i) for i, entry in enumerate(entries)]
    cache.add_entries(tracks)

    # Create FuzzyMatcher and run fuzzy_search
    matcher = FuzzyMatcher(catalog_cache=cache)
    results = matcher.fuzzy_search(query, max_results=10)

    # Property 1: At most 10 partial matches
    assert len(results) <= 10, (
        f"fuzzy_search returned {len(results)} results, expected at most 10. "
        f"Query: {query!r}, Entries: {entries!r}"
    )

    # Property 2: Results are sorted by descending score (match length proxy)
    # The score represents how well the query matches the candidate — higher
    # score means longer/better match overlap.
    for i in range(len(results) - 1):
        assert results[i].score >= results[i + 1].score, (
            f"Results not sorted by descending score at indices {i} and {i+1}. "
            f"Score[{i}]={results[i].score}, Score[{i+1}]={results[i+1].score}. "
            f"Query: {query!r}"
        )
