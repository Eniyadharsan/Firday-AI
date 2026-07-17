"""Unit tests for the CatalogCache module."""

import time
import threading
import pytest

from friday.modules.music_catalog import CatalogCache
from friday.modules.music_models import TrackResult


def _make_track(title: str, artist: str) -> TrackResult:
    """Helper to create a minimal TrackResult for testing."""
    return TrackResult(
        id="test-id",
        title=title,
        artist=artist,
        thumbnail_url="http://example.com/thumb.jpg",
        source="youtube",
        source_url="http://example.com/play",
    )


class TestCatalogCacheInit:
    def test_default_params(self):
        cache = CatalogCache()
        assert cache.max_entries == 10000
        assert cache.ttl == 3600
        assert cache.size() == 0

    def test_custom_params(self):
        cache = CatalogCache(max_entries=500, ttl=60)
        assert cache.max_entries == 500
        assert cache.ttl == 60


class TestAddEntries:
    def test_adds_title_and_artist(self):
        cache = CatalogCache()
        cache.add_entries([_make_track("Shape of You", "Ed Sheeran")])
        # Both title and artist should be indexed
        assert cache.size() == 2

    def test_skips_empty_strings(self):
        cache = CatalogCache()
        cache.add_entries([_make_track("", "  ")])
        assert cache.size() == 0

    def test_deduplicates_case_insensitive(self):
        cache = CatalogCache()
        cache.add_entries([
            _make_track("Hello", "Adele"),
            _make_track("hello", "ADELE"),
        ])
        # "hello" and "adele" are duplicates (case-insensitive)
        assert cache.size() == 2

    def test_lru_eviction(self):
        cache = CatalogCache(max_entries=3)
        cache.add_entries([
            _make_track("Song A", "Artist A"),  # adds 2 entries
            _make_track("Song B", "Artist B"),  # adds 2 entries -> total 4 -> evicts 1
        ])
        # max_entries=3, so only 3 should remain
        assert cache.size() == 3

    def test_multiple_tracks(self):
        cache = CatalogCache()
        tracks = [
            _make_track("Song 1", "Artist 1"),
            _make_track("Song 2", "Artist 2"),
            _make_track("Song 3", "Artist 3"),
        ]
        cache.add_entries(tracks)
        assert cache.size() == 6  # 3 titles + 3 artists


class TestGetCandidates:
    def test_prefix_match(self):
        cache = CatalogCache()
        cache.add_entries([
            _make_track("Shape of You", "Ed Sheeran"),
            _make_track("Shallow", "Lady Gaga"),
        ])
        candidates = cache.get_candidates("sha")
        assert "Shape of You" in candidates
        assert "Shallow" in candidates

    def test_substring_match(self):
        cache = CatalogCache()
        cache.add_entries([_make_track("The Shape of You", "Ed Sheeran")])
        candidates = cache.get_candidates("shape")
        # "shape" is a substring of "the shape of you" but not a prefix
        assert "The Shape of You" in candidates

    def test_prefix_before_substring(self):
        cache = CatalogCache()
        cache.add_entries([
            _make_track("Shape of You", "Ed Sheeran"),
            _make_track("The Shape", "Some Artist"),
        ])
        candidates = cache.get_candidates("shape")
        # "Shape of You" is a prefix match, "The Shape" is a substring match
        shape_idx = candidates.index("Shape of You")
        the_shape_idx = candidates.index("The Shape")
        assert shape_idx < the_shape_idx

    def test_case_insensitive(self):
        cache = CatalogCache()
        cache.add_entries([_make_track("HELLO World", "Artist")])
        candidates = cache.get_candidates("hello")
        assert "HELLO World" in candidates

    def test_empty_prefix_returns_empty(self):
        cache = CatalogCache()
        cache.add_entries([_make_track("Song", "Artist")])
        assert cache.get_candidates("") == []
        assert cache.get_candidates("   ") == []

    def test_no_match_returns_empty(self):
        cache = CatalogCache()
        cache.add_entries([_make_track("Hello", "Adele")])
        assert cache.get_candidates("xyz") == []

    def test_ttl_expiration(self):
        cache = CatalogCache(ttl=1)
        cache.add_entries([_make_track("Expired Song", "Old Artist")])
        # Wait for TTL to expire
        time.sleep(1.1)
        candidates = cache.get_candidates("expired")
        assert candidates == []
        # Expired entries should be removed
        assert cache.size() == 0


class TestClear:
    def test_clear_empties_cache(self):
        cache = CatalogCache()
        cache.add_entries([_make_track("Song", "Artist")])
        assert cache.size() > 0
        cache.clear()
        assert cache.size() == 0


class TestThreadSafety:
    def test_concurrent_add_and_get(self):
        cache = CatalogCache(max_entries=100)
        errors = []

        def writer():
            try:
                for i in range(50):
                    cache.add_entries([_make_track(f"Song {i}", f"Artist {i}")])
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    cache.get_candidates("song")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
