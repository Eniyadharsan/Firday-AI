"""Music Aggregator module.

Queries multiple music sources concurrently and merges, deduplicates,
and ranks results into a single unified list. Supports devotional ranking
boost and graceful partial failure handling.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from jarvis.modules.music_models import (
    AggregatedResult,
    MusicSourceAdapter,
    SearchContext,
    TrackResult,
)

# Source priority for deduplication — higher index = higher priority
_SOURCE_PRIORITY: dict[str, int] = {
    "gaana": 1,
    "jiosaavn": 2,
    "youtube": 3,
}


class MusicAggregator:
    """Query multiple music sources concurrently and merge results.

    Fans out search queries to all registered adapters in parallel using a
    thread pool, then deduplicates, ranks, and optionally applies devotional
    boosting to produce a single merged result list.

    Args:
        adapters: List of music source adapters implementing MusicSourceAdapter.
        timeout: Maximum seconds to wait for each adapter response (default 5s).
    """

    def __init__(self, adapters: list[MusicSourceAdapter], timeout: float = 5.0):
        self._adapters = adapters
        self._timeout = timeout

    def search(
        self,
        query: str,
        max_results: int = 20,
        context: SearchContext | None = None,
    ) -> AggregatedResult:
        """Fan out to all adapters, merge, deduplicate, and rank results.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return (default 20).
            context: Optional SearchContext with devotional flags and metadata.

        Returns:
            An AggregatedResult containing merged results and source status.
        """
        sources_queried: list[str] = []
        sources_failed: list[str] = []
        all_tracks: list[TrackResult] = []

        with ThreadPoolExecutor(max_workers=len(self._adapters) or 1) as executor:
            future_to_adapter = {}
            for adapter in self._adapters:
                sources_queried.append(adapter.source_name)
                future = executor.submit(adapter.search, query, max_results)
                future_to_adapter[future] = adapter

            for future in as_completed(future_to_adapter, timeout=self._timeout + 1):
                adapter = future_to_adapter[future]
                try:
                    results = future.result(timeout=self._timeout)
                    all_tracks.extend(results)
                except TimeoutError:
                    logger.warning(
                        "Adapter '{}' timed out for query: {}",
                        adapter.source_name,
                        query,
                    )
                    sources_failed.append(adapter.source_name)
                except Exception as e:
                    logger.warning(
                        "Adapter '{}' failed for query: {} — {}",
                        adapter.source_name,
                        query,
                        e,
                    )
                    sources_failed.append(adapter.source_name)

        # Deduplicate
        deduplicated = self._deduplicate(all_tracks)

        # Rank by match_score descending (exact matches first)
        ranked = sorted(deduplicated, key=lambda t: t.match_score, reverse=True)

        # Apply devotional boost if context indicates devotional intent
        if context and context.is_devotional:
            ranked = self._apply_devotional_boost(ranked)

        # Trim to max_results
        final_results = ranked[:max_results]

        return AggregatedResult(
            results=final_results,
            sources_queried=sources_queried,
            sources_failed=sources_failed,
        )

    def quick_search(self, query: str, max_results: int = 8) -> list[TrackResult]:
        """Lightweight search for autocomplete with shorter timeout.

        Uses a 2-second timeout and returns at most max_results tracks.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return (default 8).

        Returns:
            A list of deduplicated, ranked TrackResult objects.
        """
        quick_timeout = 2.0
        all_tracks: list[TrackResult] = []

        with ThreadPoolExecutor(max_workers=len(self._adapters) or 1) as executor:
            future_to_adapter = {}
            for adapter in self._adapters:
                future = executor.submit(adapter.search, query, max_results)
                future_to_adapter[future] = adapter

            for future in as_completed(future_to_adapter, timeout=quick_timeout + 1):
                adapter = future_to_adapter[future]
                try:
                    results = future.result(timeout=quick_timeout)
                    all_tracks.extend(results)
                except TimeoutError:
                    logger.debug(
                        "Adapter '{}' timed out during quick_search for: {}",
                        adapter.source_name,
                        query,
                    )
                except Exception as e:
                    logger.debug(
                        "Adapter '{}' failed during quick_search for: {} — {}",
                        adapter.source_name,
                        query,
                        e,
                    )

        deduplicated = self._deduplicate(all_tracks)
        ranked = sorted(deduplicated, key=lambda t: t.match_score, reverse=True)
        return ranked[:max_results]

    def _deduplicate(self, tracks: list[TrackResult]) -> list[TrackResult]:
        """Remove duplicate tracks, keeping the one from the higher-priority source.

        Two tracks are duplicates when their title and artist match
        case-insensitively after stripping whitespace.

        Priority order: YouTube > JioSaavn > Gaana.

        Args:
            tracks: Raw list of tracks from all sources.

        Returns:
            Deduplicated list preserving highest-priority source entries.
        """
        seen: dict[tuple[str, str], TrackResult] = {}

        for track in tracks:
            key = (track.title.lower().strip(), track.artist.lower().strip())
            if key in seen:
                existing = seen[key]
                existing_priority = _SOURCE_PRIORITY.get(existing.source, 0)
                new_priority = _SOURCE_PRIORITY.get(track.source, 0)
                if new_priority > existing_priority:
                    seen[key] = track
            else:
                seen[key] = track

        return list(seen.values())

    def _apply_devotional_boost(self, tracks: list[TrackResult]) -> list[TrackResult]:
        """Re-rank results so ≥70% of top 10 are devotional when possible.

        If fewer devotional tracks exist than needed for the 70% threshold,
        uses whatever devotional tracks are available without dropping
        non-devotional results.

        Args:
            tracks: Already-ranked list of tracks.

        Returns:
            Re-ranked list with devotional tracks promoted in top positions.
        """
        if not tracks:
            return tracks

        devotional = [t for t in tracks if t.is_devotional]
        non_devotional = [t for t in tracks if not t.is_devotional]

        # We want at least 7 devotional tracks in the top 10 (70%)
        target_devotional_in_top_10 = 7
        top_size = min(10, len(tracks))

        # Take as many devotional tracks as we can for the top slots
        devotional_for_top = devotional[:target_devotional_in_top_10]
        # Fill remaining top slots with non-devotional
        remaining_top_slots = top_size - len(devotional_for_top)
        non_devotional_for_top = non_devotional[:remaining_top_slots]

        # Build top section
        top_section = devotional_for_top + non_devotional_for_top

        # Remaining tracks (those not in top section)
        used_devotional = set(id(t) for t in devotional_for_top)
        used_non_devotional = set(id(t) for t in non_devotional_for_top)

        remaining = [
            t for t in tracks
            if id(t) not in used_devotional and id(t) not in used_non_devotional
        ]

        return top_section + remaining
