"""Catalog Cache for the music search optimization system.

This module provides a local index of recently seen track titles and artists,
enabling fuzzy matching and prefix/substring candidate lookups. The cache uses
LRU eviction and TTL-based expiration to keep memory bounded and data fresh.

Thread-safe: all operations are protected by a threading lock for safe
concurrent access from multiple adapter calls.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

from jarvis.modules.music_models import TrackResult


class CatalogCache:
    """LRU cache of track titles and artists for fuzzy lookup.

    Stores lowercase-normalized strings (titles and artists) with timestamps
    for TTL-based expiration. Uses OrderedDict for LRU eviction when the
    cache exceeds max_entries.

    Attributes:
        max_entries: Maximum number of entries before LRU eviction.
        ttl: Time-to-live in seconds for each entry.
    """

    def __init__(self, max_entries: int = 10000, ttl: int = 3600):
        """Initialize the catalog cache.

        Args:
            max_entries: Maximum number of cached entries (default 10000).
            ttl: Time-to-live in seconds for each entry (default 3600 = 1 hour).
        """
        self.max_entries = max_entries
        self.ttl = ttl
        # OrderedDict maps: normalized_string -> (original_string, timestamp)
        self._cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._lock = threading.Lock()

    def add_entries(self, tracks: list[TrackResult]) -> None:
        """Index track titles and artists for fuzzy lookup.

        Extracts the title and artist from each TrackResult and adds them
        to the cache. Duplicate entries (case-insensitive) are refreshed
        with updated timestamps and moved to the end (most recently used).

        Args:
            tracks: List of TrackResult objects to index.
        """
        with self._lock:
            now = time.time()
            for track in tracks:
                for value in (track.title, track.artist):
                    if not value or not value.strip():
                        continue
                    key = value.strip().lower()
                    original = value.strip()
                    # If already present, update timestamp and move to end (MRU)
                    if key in self._cache:
                        self._cache.move_to_end(key)
                    self._cache[key] = (original, now)

            # Evict oldest entries if over capacity
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    def get_candidates(self, prefix: str) -> list[str]:
        """Return candidate strings matching prefix or substring.

        Performs case-insensitive matching. Prefix matches are returned first,
        followed by substring matches. Expired entries (older than TTL) are
        skipped and lazily removed.

        Args:
            prefix: The search prefix/substring to match against cached entries.

        Returns:
            A list of original (non-normalized) strings that match the prefix
            or contain it as a substring. Prefix matches come first.
        """
        if not prefix or not prefix.strip():
            return []

        query = prefix.strip().lower()
        prefix_matches: list[str] = []
        substring_matches: list[str] = []
        expired_keys: list[str] = []

        with self._lock:
            now = time.time()
            for key, (original, timestamp) in self._cache.items():
                # Check TTL expiration
                if now - timestamp > self.ttl:
                    expired_keys.append(key)
                    continue

                # Prefix match takes priority
                if key.startswith(query):
                    prefix_matches.append(original)
                elif query in key:
                    substring_matches.append(original)

            # Lazily remove expired entries
            for key in expired_keys:
                del self._cache[key]

        return prefix_matches + substring_matches

    def size(self) -> int:
        """Return the current number of entries in the cache.

        Returns:
            The number of non-expired entries currently stored.
        """
        with self._lock:
            return len(self._cache)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._cache.clear()
