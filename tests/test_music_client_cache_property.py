# Feature: music-search-optimization, Property 11: Client Cache Invariants
"""Property-based test for client-side autocomplete cache invariants.

Validates: Requirements 6.4

Tests that:
  - The client-side autocomplete cache never exceeds 50 entries.
  - Any entry older than 5 minutes returns a cache miss (None).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st


# --- Python mirror of the frontend AcCache (LRU, 50 entries, 5-min TTL) ---


class ClientAutocompleteCache:
    """Python mirror of the frontend AcCache class.

    Implements an LRU cache with a maximum size and TTL-based expiry.
    Mirrors the JavaScript implementation in public/index.html.
    """

    def __init__(self, max_size: int = 50, ttl_seconds: float = 300.0):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        """Retrieve an entry from the cache.

        Returns None (cache miss) if the key is not found or if the entry
        has exceeded its TTL. On a hit, the entry is moved to the most-recently-used
        position.
        """
        if key not in self._cache:
            return None

        entry = self._cache[key]
        # Check TTL expiry
        if time.time() - entry["ts"] > self.ttl_seconds:
            del self._cache[key]
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return entry["data"]

    def set(self, key: str, data: Any) -> None:
        """Insert or update a cache entry.

        If the key already exists, it is moved to the most-recently-used position.
        If inserting causes the cache to exceed max_size, the least-recently-used
        entry is evicted.
        """
        if key in self._cache:
            del self._cache[key]

        self._cache[key] = {"data": data, "ts": time.time()}

        # Evict LRU entries if over capacity
        while len(self._cache) > self.max_size:
            self._cache.popitem(last=False)


# --- Strategies ---

# Generate realistic query strings as cache keys
_cache_key_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    min_size=1,
    max_size=30,
)

# Generate suggestion data (list of suggestion dicts)
_suggestion_data_strategy = st.lists(
    st.fixed_dictionaries({
        "title": st.text(min_size=1, max_size=60),
        "artist": st.text(min_size=1, max_size=40),
    }),
    min_size=0,
    max_size=8,
)


@st.composite
def cache_operations(draw: st.DrawFn) -> list[tuple[str, Any]]:
    """Generate a sequence of cache put operations (key, data) pairs.

    Generates between 1 and 120 operations to ensure we test well above the
    50-entry capacity limit.
    """
    num_ops = draw(st.integers(min_value=1, max_value=120))
    ops = []
    for _ in range(num_ops):
        key = draw(_cache_key_strategy)
        data = draw(_suggestion_data_strategy)
        ops.append((key, data))
    return ops


# --- Property Tests ---


@given(ops=cache_operations())
@settings(max_examples=100, deadline=None)
def test_cache_never_exceeds_max_size(ops: list[tuple[str, Any]]) -> None:
    """**Validates: Requirements 6.4**

    For any sequence of cache put operations, the client-side autocomplete
    cache SHALL never exceed 50 entries.
    """
    cache = ClientAutocompleteCache(max_size=50, ttl_seconds=300.0)

    for key, data in ops:
        cache.set(key, data)
        # Invariant: cache size must never exceed max_size after any put operation
        assert len(cache._cache) <= 50, (
            f"Cache exceeded 50 entries: size={len(cache._cache)} "
            f"after inserting key={key!r}"
        )


@given(
    keys=st.lists(_cache_key_strategy, min_size=1, max_size=20, unique=True),
    data=_suggestion_data_strategy,
)
@settings(max_examples=100, deadline=None)
def test_expired_entries_return_cache_miss(
    keys: list[str], data: Any
) -> None:
    """**Validates: Requirements 6.4**

    For any entry older than 5 minutes, a cache lookup SHALL return a
    cache miss (None), forcing a fresh API call.
    """
    # Use a very short TTL to simulate expiry without actually waiting
    ttl_seconds = 0.01  # 10 milliseconds
    cache = ClientAutocompleteCache(max_size=50, ttl_seconds=ttl_seconds)

    # Insert entries
    for key in keys:
        cache.set(key, data)

    # Wait for entries to expire
    time.sleep(0.02)  # 20 ms > 10 ms TTL

    # All entries should now be expired (cache miss)
    for key in keys:
        result = cache.get(key)
        assert result is None, (
            f"Expected cache miss for expired key={key!r}, got {result!r}"
        )


@given(ops=cache_operations())
@settings(max_examples=100, deadline=None)
def test_cache_lru_eviction_preserves_recent_entries(
    ops: list[tuple[str, Any]],
) -> None:
    """**Validates: Requirements 6.4**

    When the cache is at capacity and a new entry is inserted, the
    least-recently-used entry is evicted. The most recent entries (up to
    max_size) should remain accessible.
    """
    cache = ClientAutocompleteCache(max_size=50, ttl_seconds=300.0)

    for key, data in ops:
        cache.set(key, data)

    # After all operations, the cache contains at most 50 entries
    assert len(cache._cache) <= 50

    # All entries currently in the cache should be retrievable (not expired)
    for key in list(cache._cache.keys()):
        result = cache.get(key)
        assert result is not None, (
            f"Entry for key={key!r} is in cache but returned None"
        )
