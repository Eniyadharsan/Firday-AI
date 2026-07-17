"""Search Engine orchestrator for the music search optimization system.

This module provides the top-level SearchEngine class that wires together the
LanguageProcessor, FuzzyMatcher, MusicAggregator, and AutocompleteService into
a unified search flow with query validation, context building, aggregation,
and fuzzy correction.
"""

from __future__ import annotations

from friday.modules.music_aggregator import MusicAggregator
from friday.modules.music_autocomplete import AutocompleteService
from friday.modules.music_fuzzy import FuzzyMatcher
from friday.modules.music_language import LanguageProcessor
from friday.modules.music_models import AggregatedResult, SearchContext, Suggestion


# Maximum allowed query length
_MAX_QUERY_LENGTH = 200


class SearchEngine:
    """Orchestrate the full music search pipeline.

    Coordinates validation, language processing, multi-source aggregation,
    and fuzzy correction into a single search flow. Also delegates
    autocomplete requests to the AutocompleteService.

    Args:
        language_processor: LanguageProcessor for script detection and
            devotional intent analysis.
        fuzzy_matcher: FuzzyMatcher for typo correction against the catalog.
        aggregator: MusicAggregator for concurrent multi-source search.
        autocomplete_service: AutocompleteService for real-time suggestions.
    """

    def __init__(
        self,
        language_processor: LanguageProcessor,
        fuzzy_matcher: FuzzyMatcher,
        aggregator: MusicAggregator,
        autocomplete_service: AutocompleteService,
    ):
        self._language_processor = language_processor
        self._fuzzy_matcher = fuzzy_matcher
        self._aggregator = aggregator
        self._autocomplete_service = autocomplete_service

    def validate_query(self, query: str) -> str | None:
        """Validate the search query and return an error message if invalid.

        Checks:
            - Empty or whitespace-only queries are rejected.
            - Queries longer than 200 characters are rejected.

        Args:
            query: The raw search query string.

        Returns:
            An error message string if the query is invalid, or None if valid.
        """
        if not query or not query.strip():
            return "Query parameter 'q' is required"

        if len(query) > _MAX_QUERY_LENGTH:
            return "Query must be 200 characters or fewer"

        return None

    def search(self, query: str) -> AggregatedResult:
        """Execute the full search flow.

        Flow:
            1. Validate the query — raise ValueError if invalid.
            2. Build search context via LanguageProcessor.
            3. Aggregate results from all music sources.
            4. If no results, attempt fuzzy correction.
            5. Attach devotional context if applicable.
            6. Return the AggregatedResult.

        Args:
            query: The user's search query string.

        Returns:
            An AggregatedResult with merged tracks, optional correction,
            and devotional context metadata.

        Raises:
            ValueError: If the query fails validation (empty or too long).
        """
        # Step 1: Validate
        error = self.validate_query(query)
        if error is not None:
            raise ValueError(error)

        # Step 2: Build search context
        context: SearchContext = self._language_processor.build_search_context(query)

        # Step 3: Aggregate results from all sources
        result: AggregatedResult = self._aggregator.search(query, context=context)

        # Step 4: If no results, try fuzzy correction
        if len(result.results) == 0:
            correction = self._fuzzy_matcher.find_correction(query)
            if correction is not None:
                result.correction = correction

        # Step 5: Attach devotional context if detected
        if context.is_devotional:
            result.devotional_context = context.devotional_tradition

        return result

    def autocomplete(self, query: str) -> list[Suggestion]:
        """Return autocomplete suggestions for a partial query.

        Delegates directly to the AutocompleteService.

        Args:
            query: The partial search query string.

        Returns:
            A list of Suggestion objects (may be empty).
        """
        return self._autocomplete_service.suggest(query)
