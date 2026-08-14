# Feature: music-search-optimization, Property 4: Query Length Validation
"""
Property-based tests for query length validation in the SearchEngine.

Property 4: Query Length Validation
For any string of length ≤ 200 characters, the Search Engine SHALL accept
the query without error. For any string of length > 200 characters, the
Search Engine SHALL reject it with a validation error.

**Validates: Requirements 2.1**
"""

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from friday.modules.music_models import (
    AggregatedResult,
    SearchContext,
)
from friday.modules.music_search_engine import SearchEngine


def _make_engine() -> SearchEngine:
    """Create a SearchEngine with mocked dependencies for validation testing."""
    language_processor = MagicMock()
    fuzzy_matcher = MagicMock()
    aggregator = MagicMock()
    autocomplete_service = MagicMock()

    language_processor.build_search_context.return_value = SearchContext(
        original_query="test",
        normalized_query="test",
        detected_scripts=["Latin"],
        is_devotional=False,
        devotional_tradition=None,
        devotional_keywords_found=[],
    )

    aggregator.search.return_value = AggregatedResult(
        results=[],
        sources_queried=["youtube"],
        sources_failed=[],
    )

    fuzzy_matcher.find_correction.return_value = None
    autocomplete_service.suggest.return_value = []

    return SearchEngine(
        language_processor=language_processor,
        fuzzy_matcher=fuzzy_matcher,
        aggregator=aggregator,
        autocomplete_service=autocomplete_service,
    )


# --- Property 4: Query Length Validation ---


@settings(max_examples=10, deadline=None)
@given(
    query=st.text(min_size=1, max_size=200),
)
def test_queries_within_limit_are_accepted(query: str):
    """
    Property 4: Query Length Validation (accept case)

    For any non-empty string of length ≤ 200 characters, the SearchEngine
    SHALL accept the query without a validation error (validate_query returns None).

    # Feature: music-search-optimization, Property 4: Query Length Validation
    **Validates: Requirements 2.1**
    """
    # Skip whitespace-only strings since those are rejected for being empty,
    # not for length reasons
    assume(query.strip() != "")

    engine = _make_engine()
    error = engine.validate_query(query)

    assert error is None, (
        f"Query of length {len(query)} should be accepted, "
        f"but got error: {error!r}"
    )


@settings(max_examples=10, deadline=None)
@given(
    query=st.text(min_size=201, max_size=500),
)
def test_queries_exceeding_limit_are_rejected(query: str):
    """
    Property 4: Query Length Validation (reject case)

    For any string of length > 200 characters, the SearchEngine SHALL reject
    it with a validation error indicating the query is too long.

    # Feature: music-search-optimization, Property 4: Query Length Validation
    **Validates: Requirements 2.1**
    """
    engine = _make_engine()
    error = engine.validate_query(query)

    assert error is not None, (
        f"Query of length {len(query)} should be rejected, "
        f"but validate_query returned None"
    )
    assert "200" in error, (
        f"Error message should mention the 200-character limit, got: {error!r}"
    )


@settings(max_examples=10, deadline=None)
@given(
    query=st.text(min_size=201, max_size=500),
)
def test_search_raises_on_long_query(query: str):
    """
    Property 4: Query Length Validation (search raises ValueError)

    For any string of length > 200 characters, calling search() SHALL raise
    a ValueError with a message about the length limit.

    # Feature: music-search-optimization, Property 4: Query Length Validation
    **Validates: Requirements 2.1**
    """
    engine = _make_engine()

    with pytest.raises(ValueError, match="200 characters or fewer"):
        engine.search(query)


@settings(max_examples=10, deadline=None)
@given(
    query=st.text(min_size=1, max_size=200),
)
def test_search_does_not_raise_on_valid_query(query: str):
    """
    Property 4: Query Length Validation (search succeeds for valid queries)

    For any non-empty, non-whitespace string of length ≤ 200 characters,
    calling search() SHALL NOT raise a ValueError.

    # Feature: music-search-optimization, Property 4: Query Length Validation
    **Validates: Requirements 2.1**
    """
    assume(query.strip() != "")

    engine = _make_engine()

    # Should not raise — if it does, the test fails
    result = engine.search(query)
    assert result is not None
