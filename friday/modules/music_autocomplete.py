"""Autocomplete Service module.

Provides fast, lightweight song suggestions from cached data and live
API results via the Music Aggregator's quick_search method.
Implements server-side caching with TTL and enforces output constraints
(max suggestions, title/artist truncation).
"""

from __future__ import annotations

import threading
import time

from loguru import logger

from friday.modules.music_aggregator import MusicAggregator
from friday.modules.music_models import Suggestion, TrackResult


class AutocompleteService:
    """Provide real-time autocomplete suggestions for music search.

    Wraps the MusicAggregator's quick_search with server-side caching,
    minimum query length enforcement, and output truncation rules.

    Args:
        aggregator: MusicAggregator instance for live search queries.
        cache_ttl: Cache time-to-live in seconds (default 300s / 5 minutes).
    """

    def __init__(self, aggregator: MusicAggregator, cache_ttl: int = 300):
        self._aggregator = aggregator
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, list[Suggestion]]] = {}
        self._lock = threading.Lock()

    def suggest(self, query: str, max_results: int = 8) -> list[Suggestion]:
        """Return up to max_results suggestions for the partial query.

        Flow:
            1. If query length < 2, return empty list immediately.
            2. Normalize cache key (lowercase, stripped).
            3. Check server-side cache; return cached if not expired.
            4. Call aggregator.quick_search() for live results.
            5. Convert TrackResult objects to Suggestion objects with truncation.
            6. Cache and return the suggestions (max 8).

        Args:
            query: The partial search query string.
            max_results: Maximum number of suggestions to return (default 8).

        Returns:
            A list of Suggestion objects, possibly empty.
        """
        if len(query) < 2:
            return []

        cache_key = query.lower().strip()
        max_results = min(max_results, 8)

        # Check cache
        with self._lock:
            if cache_key in self._cache:
                timestamp, cached_suggestions = self._cache[cache_key]
                if time.time() - timestamp < self._cache_ttl:
                    logger.debug(
                        "Autocomplete cache hit for query: '{}'", cache_key
                    )
                    return cached_suggestions[:max_results]
                else:
                    # Expired entry — remove it
                    del self._cache[cache_key]

        # Cache miss — fetch live results
        try:
            tracks = self._aggregator.quick_search(query, max_results=max_results)
        except Exception as e:
            logger.warning(
                "Autocomplete quick_search failed for '{}': {}", query, e
            )
            return []

        # Convert TrackResult to Suggestion with truncation
        suggestions = [
            self._track_to_suggestion(track) for track in tracks
        ][:max_results]

        # Store in cache
        with self._lock:
            self._cache[cache_key] = (time.time(), suggestions)

        return suggestions

    def _track_to_suggestion(self, track: TrackResult) -> Suggestion:
        """Convert a TrackResult to a Suggestion with field truncation.

        Title is truncated to 60 characters, artist to 40 characters.

        Args:
            track: The TrackResult to convert.

        Returns:
            A Suggestion dataclass instance.
        """
        return Suggestion(
            title=self._truncate(track.title, 60),
            artist=self._truncate(track.artist, 40),
            thumbnail_url=track.thumbnail_url,
            video_id=track.id,
            source=track.source,
        )

    @staticmethod
    def _truncate(value: str, max_length: int) -> str:
        """Truncate a string to max_length, appending '...' if truncated.

        Args:
            value: The string to potentially truncate.
            max_length: Maximum allowed length.

        Returns:
            The original string if within limits, or truncated with '...' suffix.
        """
        if len(value) <= max_length:
            return value
        return value[: max_length - 3] + "..."

    def clear_cache(self) -> None:
        """Clear all cached suggestions."""
        with self._lock:
            self._cache.clear()
