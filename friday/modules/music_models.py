"""Data models and interfaces for the music search optimization system.

This module defines the core data structures used across the music search
components: autocomplete, fuzzy matching, aggregation, and language processing.
It also defines the MusicSourceAdapter protocol that all music source
integrations must implement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class TrackResult:
    """A single track result from a music source.

    Attributes:
        id: Source-specific track identifier (e.g., YouTube video ID).
        title: Track title in original language — never translated.
        artist: Artist name in original language.
        thumbnail_url: URL to album art or video thumbnail.
        source: Identifier of the music source ("youtube", "jiosaavn", "gaana").
        source_url: Playback or redirect URL for this track.
        duration_seconds: Track duration in seconds, or None if unavailable.
        is_devotional: Whether the track is categorized as devotional/spiritual.
        tradition: Devotional tradition label (e.g., "Hindu Bhajan", "Sikh Shabad"),
            or None if not devotional.
        match_score: Relevance score from 0.0 (no match) to 1.0 (exact match)
            used for ranking results.
    """

    id: str
    title: str
    artist: str
    thumbnail_url: str
    source: str
    source_url: str
    duration_seconds: int | None = None
    is_devotional: bool = False
    tradition: str | None = None
    match_score: float = 0.0


@dataclass
class Suggestion:
    """An autocomplete suggestion displayed in the suggestion panel.

    Attributes:
        title: Track title, truncated to 60 characters.
        artist: Artist name, truncated to 40 characters.
        thumbnail_url: URL to the track's thumbnail image.
        video_id: Source-specific track ID used for playback on selection.
        source: Identifier of the music source ("youtube", "jiosaavn", "gaana").
    """

    title: str
    artist: str
    thumbnail_url: str
    video_id: str
    source: str


@dataclass
class FuzzyMatch:
    """A fuzzy match result from the catalog cache.

    Represents a catalog entry that approximately matches the user's query,
    used for typo correction and partial matching.

    Attributes:
        original: The original catalog entry (title or artist name).
        query: The user's query that was matched against.
        score: Similarity score from 0.0 (no similarity) to 1.0 (exact match).
        distance: Levenshtein edit distance between query and original.
    """

    original: str
    query: str
    score: float
    distance: int


@dataclass
class AggregatedResult:
    """Merged results from multiple music sources.

    Contains the final ranked list of tracks after deduplication, along with
    metadata about the search operation including corrections and source status.

    Attributes:
        results: Merged, deduplicated, and ranked track results (max 20).
        correction: "Did you mean...?" suggestion if a typo was detected, or None.
        devotional_context: Devotional tradition label if the query was detected
            as devotional, or None.
        sources_queried: List of source names that were actually queried.
        sources_failed: List of source names that timed out or returned errors.
    """

    results: list[TrackResult] = field(default_factory=list)
    correction: str | None = None
    devotional_context: str | None = None
    sources_queried: list[str] = field(default_factory=list)
    sources_failed: list[str] = field(default_factory=list)


@dataclass
class SearchContext:
    """Contextual information about a search query after language processing.

    Produced by the LanguageProcessor to inform downstream components about
    the query's characteristics: script, devotional intent, and normalized form.

    Attributes:
        original_query: The raw query string as submitted by the user.
        normalized_query: Romanization-normalized form of the query. For non-Latin
            scripts, this is identical to the original (no transliteration).
        detected_scripts: List of Unicode script names detected in the query
            (e.g., ["Latin", "Devanagari"]).
        is_devotional: Whether the query contains a devotional keyword.
        devotional_tradition: The tradition label if devotional intent is detected
            (e.g., "Hindu Bhajan"), or None.
        devotional_keywords_found: List of devotional keywords found in the query.
    """

    original_query: str
    normalized_query: str
    detected_scripts: list[str] = field(default_factory=list)
    is_devotional: bool = False
    devotional_tradition: str | None = None
    devotional_keywords_found: list[str] = field(default_factory=list)


class MusicSourceAdapter(Protocol):
    """Protocol defining the interface for music source integrations.

    Each music source (YouTube, JioSaavn, Gaana, etc.) must implement this
    protocol so the MusicAggregator can query them uniformly.
    """

    @property
    def source_name(self) -> str:
        """Return the identifier for this music source (e.g., 'youtube')."""
        ...

    def search(self, query: str, max_results: int) -> list[TrackResult]:
        """Search this music source for tracks matching the query.

        Args:
            query: The search query string (may contain any Unicode script).
            max_results: Maximum number of results to return.

        Returns:
            A list of TrackResult objects from this source, ordered by relevance.
        """
        ...

    def is_available(self) -> bool:
        """Check whether this music source is currently reachable.

        Returns:
            True if the source can be queried, False otherwise.
        """
        ...
