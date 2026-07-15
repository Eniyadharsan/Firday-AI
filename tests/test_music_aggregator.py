"""Unit tests for the Music Aggregator module."""

import time
from unittest.mock import MagicMock, PropertyMock

import pytest

from jarvis.modules.music_aggregator import MusicAggregator, _SOURCE_PRIORITY
from jarvis.modules.music_models import (
    AggregatedResult,
    SearchContext,
    TrackResult,
)


def _make_track(
    title: str = "Song",
    artist: str = "Artist",
    source: str = "youtube",
    match_score: float = 0.5,
    is_devotional: bool = False,
    tradition: str | None = None,
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
        is_devotional=is_devotional,
        tradition=tradition,
        match_score=match_score,
    )


def _make_adapter(
    source_name: str,
    results: list[TrackResult] | None = None,
    delay: float = 0.0,
    should_raise: bool = False,
) -> MagicMock:
    """Create a mock adapter with configurable behavior."""
    adapter = MagicMock()
    type(adapter).source_name = PropertyMock(return_value=source_name)
    adapter.is_available.return_value = True

    if should_raise:
        adapter.search.side_effect = Exception(f"{source_name} failed")
    elif delay > 0:

        def slow_search(query, max_results=10):
            time.sleep(delay)
            return results or []

        adapter.search.side_effect = slow_search
    else:
        adapter.search.return_value = results or []

    return adapter


class TestMusicAggregatorInit:
    def test_creates_with_adapters_and_default_timeout(self):
        adapters = [_make_adapter("youtube")]
        agg = MusicAggregator(adapters)
        assert agg._timeout == 5.0

    def test_creates_with_custom_timeout(self):
        adapters = [_make_adapter("youtube")]
        agg = MusicAggregator(adapters, timeout=3.0)
        assert agg._timeout == 3.0


class TestSearch:
    def test_returns_aggregated_result(self):
        adapter = _make_adapter("youtube", [_make_track()])
        agg = MusicAggregator([adapter])

        result = agg.search("test query")

        assert isinstance(result, AggregatedResult)
        assert len(result.results) == 1
        assert result.sources_queried == ["youtube"]
        assert result.sources_failed == []

    def test_merges_results_from_multiple_adapters(self):
        yt = _make_adapter("youtube", [_make_track(title="Song A", source="youtube")])
        js = _make_adapter("jiosaavn", [_make_track(title="Song B", source="jiosaavn")])
        ga = _make_adapter("gaana", [_make_track(title="Song C", source="gaana")])

        agg = MusicAggregator([yt, js, ga])
        result = agg.search("test")

        assert len(result.results) == 3
        assert set(result.sources_queried) == {"youtube", "jiosaavn", "gaana"}
        assert result.sources_failed == []

    def test_respects_max_results(self):
        tracks = [_make_track(title=f"Song {i}", source="youtube") for i in range(25)]
        adapter = _make_adapter("youtube", tracks)
        agg = MusicAggregator([adapter])

        result = agg.search("test", max_results=20)
        assert len(result.results) <= 20

    def test_ranks_by_match_score_descending(self):
        tracks = [
            _make_track(title="Low", match_score=0.2, source="youtube"),
            _make_track(title="High", match_score=0.9, source="youtube"),
            _make_track(title="Mid", match_score=0.5, source="youtube"),
        ]
        adapter = _make_adapter("youtube", tracks)
        agg = MusicAggregator([adapter])

        result = agg.search("test")

        scores = [t.match_score for t in result.results]
        assert scores == sorted(scores, reverse=True)

    def test_handles_adapter_failure_gracefully(self):
        good = _make_adapter("youtube", [_make_track(source="youtube")])
        bad = _make_adapter("jiosaavn", should_raise=True)

        agg = MusicAggregator([good, bad])
        result = agg.search("test")

        assert len(result.results) == 1
        assert "youtube" in result.sources_queried
        assert "jiosaavn" in result.sources_queried
        assert "jiosaavn" in result.sources_failed

    def test_all_adapters_fail_returns_empty_results(self):
        bad1 = _make_adapter("youtube", should_raise=True)
        bad2 = _make_adapter("jiosaavn", should_raise=True)

        agg = MusicAggregator([bad1, bad2])
        result = agg.search("test")

        assert result.results == []
        assert set(result.sources_queried) == {"youtube", "jiosaavn"}
        assert set(result.sources_failed) == {"youtube", "jiosaavn"}

    def test_passes_query_to_adapters(self):
        adapter = _make_adapter("youtube", [])
        agg = MusicAggregator([adapter])

        agg.search("specific query", max_results=15)

        adapter.search.assert_called_once_with("specific query", 15)


class TestDeduplication:
    def test_removes_duplicate_tracks(self):
        track1 = _make_track(title="Hello", artist="Adele", source="youtube")
        track2 = _make_track(title="Hello", artist="Adele", source="jiosaavn")

        yt = _make_adapter("youtube", [track1])
        js = _make_adapter("jiosaavn", [track2])

        agg = MusicAggregator([yt, js])
        result = agg.search("hello")

        assert len(result.results) == 1

    def test_dedup_is_case_insensitive(self):
        track1 = _make_track(title="HELLO", artist="ADELE", source="youtube")
        track2 = _make_track(title="hello", artist="adele", source="jiosaavn")

        yt = _make_adapter("youtube", [track1])
        js = _make_adapter("jiosaavn", [track2])

        agg = MusicAggregator([yt, js])
        result = agg.search("hello")

        assert len(result.results) == 1

    def test_dedup_strips_whitespace(self):
        track1 = _make_track(title="  Hello  ", artist="  Adele  ", source="youtube")
        track2 = _make_track(title="Hello", artist="Adele", source="jiosaavn")

        yt = _make_adapter("youtube", [track1])
        js = _make_adapter("jiosaavn", [track2])

        agg = MusicAggregator([yt, js])
        result = agg.search("hello")

        assert len(result.results) == 1

    def test_keeps_higher_priority_source(self):
        """YouTube (priority 3) should be kept over JioSaavn (priority 2)."""
        track_yt = _make_track(title="Song", artist="Artist", source="youtube")
        track_js = _make_track(title="Song", artist="Artist", source="jiosaavn")

        yt = _make_adapter("youtube", [track_yt])
        js = _make_adapter("jiosaavn", [track_js])

        agg = MusicAggregator([yt, js])
        result = agg.search("song")

        assert len(result.results) == 1
        assert result.results[0].source == "youtube"

    def test_keeps_jiosaavn_over_gaana(self):
        """JioSaavn (priority 2) should be kept over Gaana (priority 1)."""
        track_js = _make_track(title="Song", artist="Artist", source="jiosaavn")
        track_ga = _make_track(title="Song", artist="Artist", source="gaana")

        js = _make_adapter("jiosaavn", [track_js])
        ga = _make_adapter("gaana", [track_ga])

        agg = MusicAggregator([js, ga])
        result = agg.search("song")

        assert len(result.results) == 1
        assert result.results[0].source == "jiosaavn"

    def test_different_titles_not_deduplicated(self):
        track1 = _make_track(title="Song A", artist="Artist", source="youtube")
        track2 = _make_track(title="Song B", artist="Artist", source="jiosaavn")

        yt = _make_adapter("youtube", [track1])
        js = _make_adapter("jiosaavn", [track2])

        agg = MusicAggregator([yt, js])
        result = agg.search("song")

        assert len(result.results) == 2

    def test_different_artists_not_deduplicated(self):
        track1 = _make_track(title="Song", artist="Artist A", source="youtube")
        track2 = _make_track(title="Song", artist="Artist B", source="jiosaavn")

        yt = _make_adapter("youtube", [track1])
        js = _make_adapter("jiosaavn", [track2])

        agg = MusicAggregator([yt, js])
        result = agg.search("song")

        assert len(result.results) == 2


class TestDevotionalBoost:
    def test_devotional_boost_promotes_devotional_tracks(self):
        """When is_devotional is True, ≥70% of top 10 should be devotional."""
        # Create 8 devotional and 8 non-devotional tracks
        devotional_tracks = [
            _make_track(
                title=f"Bhajan {i}",
                artist="Devotional Artist",
                source="youtube",
                match_score=0.3,
                is_devotional=True,
                tradition="Hindu Bhajan",
            )
            for i in range(8)
        ]
        non_devotional_tracks = [
            _make_track(
                title=f"Pop Song {i}",
                artist="Pop Artist",
                source="youtube",
                match_score=0.8,
            )
            for i in range(8)
        ]

        all_tracks = non_devotional_tracks + devotional_tracks
        adapter = _make_adapter("youtube", all_tracks)
        agg = MusicAggregator([adapter])

        context = SearchContext(
            original_query="bhajan songs",
            normalized_query="bhajan songs",
            is_devotional=True,
            devotional_tradition="Hindu Bhajan",
            devotional_keywords_found=["bhajan"],
        )

        result = agg.search("bhajan songs", context=context)

        top_10 = result.results[:10]
        devotional_count = sum(1 for t in top_10 if t.is_devotional)
        assert devotional_count >= 7  # 70% of 10

    def test_no_boost_without_devotional_context(self):
        """Without devotional context, ranking is purely by match_score."""
        devotional = _make_track(
            title="Bhajan", match_score=0.3, is_devotional=True, source="youtube"
        )
        pop = _make_track(title="Pop", match_score=0.9, source="youtube")

        adapter = _make_adapter("youtube", [devotional, pop])
        agg = MusicAggregator([adapter])

        result = agg.search("music")

        assert result.results[0].title == "Pop"
        assert result.results[1].title == "Bhajan"

    def test_devotional_boost_with_insufficient_devotional_tracks(self):
        """If fewer devotional tracks exist, use what's available."""
        devotional_tracks = [
            _make_track(
                title=f"Bhajan {i}",
                match_score=0.3,
                is_devotional=True,
                tradition="Hindu Bhajan",
                source="youtube",
            )
            for i in range(3)
        ]
        non_devotional_tracks = [
            _make_track(
                title=f"Pop {i}", match_score=0.8, source="youtube"
            )
            for i in range(10)
        ]

        adapter = _make_adapter("youtube", non_devotional_tracks + devotional_tracks)
        agg = MusicAggregator([adapter])

        context = SearchContext(
            original_query="bhajan",
            normalized_query="bhajan",
            is_devotional=True,
        )

        result = agg.search("bhajan", context=context)

        # Should still have all tracks — no tracks dropped
        assert len(result.results) == 13

    def test_devotional_boost_with_empty_results(self):
        """Devotional boost on empty results doesn't crash."""
        adapter = _make_adapter("youtube", [])
        agg = MusicAggregator([adapter])

        context = SearchContext(
            original_query="bhajan",
            normalized_query="bhajan",
            is_devotional=True,
        )

        result = agg.search("bhajan", context=context)
        assert result.results == []


class TestQuickSearch:
    def test_returns_list_of_tracks(self):
        tracks = [_make_track(title=f"Song {i}", source="youtube") for i in range(5)]
        adapter = _make_adapter("youtube", tracks)
        agg = MusicAggregator([adapter])

        result = agg.quick_search("test")

        assert isinstance(result, list)
        assert len(result) == 5
        assert all(isinstance(t, TrackResult) for t in result)

    def test_limits_to_max_results(self):
        tracks = [_make_track(title=f"Song {i}", source="youtube") for i in range(15)]
        adapter = _make_adapter("youtube", tracks)
        agg = MusicAggregator([adapter])

        result = agg.quick_search("test", max_results=8)
        assert len(result) <= 8

    def test_deduplicates_results(self):
        track1 = _make_track(title="Song", artist="Artist", source="youtube")
        track2 = _make_track(title="Song", artist="Artist", source="jiosaavn")

        yt = _make_adapter("youtube", [track1])
        js = _make_adapter("jiosaavn", [track2])

        agg = MusicAggregator([yt, js])
        result = agg.quick_search("song")

        assert len(result) == 1

    def test_handles_adapter_failure(self):
        good = _make_adapter("youtube", [_make_track(source="youtube")])
        bad = _make_adapter("jiosaavn", should_raise=True)

        agg = MusicAggregator([good, bad])
        result = agg.quick_search("test")

        assert len(result) == 1

    def test_ranks_by_match_score(self):
        tracks = [
            _make_track(title="Low", match_score=0.1, source="youtube"),
            _make_track(title="High", match_score=0.9, source="youtube"),
        ]
        adapter = _make_adapter("youtube", tracks)
        agg = MusicAggregator([adapter])

        result = agg.quick_search("test")

        assert result[0].match_score >= result[1].match_score


class TestSourcePriority:
    def test_youtube_has_highest_priority(self):
        assert _SOURCE_PRIORITY["youtube"] > _SOURCE_PRIORITY["jiosaavn"]
        assert _SOURCE_PRIORITY["youtube"] > _SOURCE_PRIORITY["gaana"]

    def test_jiosaavn_higher_than_gaana(self):
        assert _SOURCE_PRIORITY["jiosaavn"] > _SOURCE_PRIORITY["gaana"]
