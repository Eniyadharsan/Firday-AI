"""Unit tests for the SearchEngine orchestrator module."""

from unittest.mock import MagicMock, patch

import pytest

from jarvis.modules.music_models import (
    AggregatedResult,
    SearchContext,
    Suggestion,
    TrackResult,
)
from jarvis.modules.music_search_engine import SearchEngine


def _make_track(
    title: str = "Song",
    artist: str = "Artist",
    source: str = "youtube",
    match_score: float = 0.5,
) -> TrackResult:
    """Helper to create a TrackResult."""
    return TrackResult(
        id=f"{source}_{title.lower().replace(' ', '_')}",
        title=title,
        artist=artist,
        thumbnail_url="https://img.example.com/thumb.jpg",
        source=source,
        source_url=f"https://{source}.com/track/123",
        duration_seconds=240,
        match_score=match_score,
    )


def _make_suggestion(title: str = "Song", artist: str = "Artist") -> Suggestion:
    """Helper to create a Suggestion."""
    return Suggestion(
        title=title,
        artist=artist,
        thumbnail_url="https://img.example.com/thumb.jpg",
        video_id="abc123",
        source="youtube",
    )


@pytest.fixture
def mock_deps():
    """Create mocked dependencies for the SearchEngine."""
    language_processor = MagicMock()
    fuzzy_matcher = MagicMock()
    aggregator = MagicMock()
    autocomplete_service = MagicMock()

    # Default: build_search_context returns a non-devotional context
    language_processor.build_search_context.return_value = SearchContext(
        original_query="test",
        normalized_query="test",
        detected_scripts=["Latin"],
        is_devotional=False,
        devotional_tradition=None,
        devotional_keywords_found=[],
    )

    # Default: aggregator returns some results
    aggregator.search.return_value = AggregatedResult(
        results=[_make_track()],
        sources_queried=["youtube"],
        sources_failed=[],
    )

    # Default: no correction needed
    fuzzy_matcher.find_correction.return_value = None

    # Default: autocomplete returns some suggestions
    autocomplete_service.suggest.return_value = [_make_suggestion()]

    return {
        "language_processor": language_processor,
        "fuzzy_matcher": fuzzy_matcher,
        "aggregator": aggregator,
        "autocomplete_service": autocomplete_service,
    }


@pytest.fixture
def engine(mock_deps):
    """Create a SearchEngine with mocked dependencies."""
    return SearchEngine(**mock_deps)


class TestValidateQuery:
    def test_empty_string_returns_error(self, engine):
        error = engine.validate_query("")
        assert error == "Query parameter 'q' is required"

    def test_whitespace_only_returns_error(self, engine):
        error = engine.validate_query("   ")
        assert error == "Query parameter 'q' is required"

    def test_over_200_chars_returns_error(self, engine):
        query = "a" * 201
        error = engine.validate_query(query)
        assert error == "Query must be 200 characters or fewer"

    def test_exactly_200_chars_is_valid(self, engine):
        query = "a" * 200
        error = engine.validate_query(query)
        assert error is None

    def test_valid_query_returns_none(self, engine):
        error = engine.validate_query("hello world")
        assert error is None

    def test_unicode_query_is_valid(self, engine):
        error = engine.validate_query("भजन")
        assert error is None

    def test_single_char_is_valid(self, engine):
        error = engine.validate_query("a")
        assert error is None


class TestSearch:
    def test_raises_value_error_on_empty_query(self, engine):
        with pytest.raises(ValueError, match="Query parameter 'q' is required"):
            engine.search("")

    def test_raises_value_error_on_too_long_query(self, engine):
        with pytest.raises(ValueError, match="Query must be 200 characters or fewer"):
            engine.search("x" * 201)

    def test_calls_language_processor(self, engine, mock_deps):
        engine.search("test query")
        mock_deps["language_processor"].build_search_context.assert_called_once_with(
            "test query"
        )

    def test_calls_aggregator_with_context(self, engine, mock_deps):
        context = mock_deps["language_processor"].build_search_context.return_value
        engine.search("test query")
        mock_deps["aggregator"].search.assert_called_once_with(
            "test query", context=context
        )

    def test_returns_aggregated_result(self, engine):
        result = engine.search("test")
        assert isinstance(result, AggregatedResult)
        assert len(result.results) == 1

    def test_applies_fuzzy_correction_when_no_results(self, engine, mock_deps):
        # Aggregator returns empty results
        mock_deps["aggregator"].search.return_value = AggregatedResult(
            results=[],
            sources_queried=["youtube"],
            sources_failed=[],
        )
        mock_deps["fuzzy_matcher"].find_correction.return_value = "corrected query"

        result = engine.search("misspeled")

        mock_deps["fuzzy_matcher"].find_correction.assert_called_once_with("misspeled")
        assert result.correction == "corrected query"

    def test_no_fuzzy_correction_when_results_exist(self, engine, mock_deps):
        # Aggregator returns results
        mock_deps["aggregator"].search.return_value = AggregatedResult(
            results=[_make_track()],
            sources_queried=["youtube"],
            sources_failed=[],
        )

        result = engine.search("valid query")

        mock_deps["fuzzy_matcher"].find_correction.assert_not_called()
        assert result.correction is None

    def test_no_correction_when_fuzzy_returns_none(self, engine, mock_deps):
        mock_deps["aggregator"].search.return_value = AggregatedResult(
            results=[],
            sources_queried=["youtube"],
            sources_failed=[],
        )
        mock_deps["fuzzy_matcher"].find_correction.return_value = None

        result = engine.search("unknown")

        assert result.correction is None

    def test_attaches_devotional_context(self, engine, mock_deps):
        mock_deps["language_processor"].build_search_context.return_value = SearchContext(
            original_query="bhajan songs",
            normalized_query="bhajan songs",
            detected_scripts=["Latin"],
            is_devotional=True,
            devotional_tradition="Hindu Bhajan",
            devotional_keywords_found=["bhajan"],
        )

        result = engine.search("bhajan songs")

        assert result.devotional_context == "Hindu Bhajan"

    def test_no_devotional_context_for_non_devotional(self, engine, mock_deps):
        result = engine.search("pop songs")
        assert result.devotional_context is None


class TestAutocomplete:
    def test_delegates_to_autocomplete_service(self, engine, mock_deps):
        result = engine.autocomplete("tes")

        mock_deps["autocomplete_service"].suggest.assert_called_once_with("tes")
        assert len(result) == 1
        assert isinstance(result[0], Suggestion)

    def test_returns_empty_for_short_query(self, engine, mock_deps):
        mock_deps["autocomplete_service"].suggest.return_value = []

        result = engine.autocomplete("t")

        assert result == []
