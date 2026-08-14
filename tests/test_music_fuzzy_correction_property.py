# Feature: music-search-optimization, Property 7: Fuzzy Correction Within Edit Distance
"""
Property-based tests for the Fuzzy Matcher module.

Property 7: Fuzzy Correction Within Edit Distance
For any catalog entry string, applying at most 2 single-character edits
(insertions, deletions, or substitutions) always results in find_correction()
returning the original entry as the suggested correction.

**Validates: Requirements 4.1**
"""

import random
import string

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from friday.modules.music_catalog import CatalogCache
from friday.modules.music_fuzzy import FuzzyMatcher
from friday.modules.music_models import TrackResult


# --- Helper functions for applying edit operations ---


def _apply_insertion(s: str, pos: int, char: str) -> str:
    """Insert a single character at the given position."""
    return s[:pos] + char + s[pos:]


def _apply_deletion(s: str, pos: int) -> str:
    """Delete the character at the given position."""
    return s[:pos] + s[pos + 1:]


def _apply_substitution(s: str, pos: int, char: str) -> str:
    """Replace the character at the given position with a new character."""
    return s[:pos] + char + s[pos + 1:]


# --- Strategies ---

# Generate catalog entry strings: realistic track titles/artist names
# Must be at least 3 chars (the minimum for fuzzy matching to engage)
# Exclude leading/trailing spaces to avoid normalization affecting edit distance
_catalog_entry = st.text(
    alphabet=st.sampled_from(string.ascii_lowercase + string.digits + " "),
    min_size=3,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 3 and s == s.strip())

# Characters that can be used for insertions and substitutions
_edit_char = st.sampled_from(string.ascii_lowercase + string.digits)

# Number of edits to apply (1 or 2)
_num_edits = st.integers(min_value=1, max_value=2)


@st.composite
def _edited_entry(draw):
    """Generate a catalog entry and a version with 1-2 random edits applied.

    Returns a tuple of (original_entry, edited_version, num_edits_applied).
    The edited version is guaranteed to have the same normalized form as if
    it were stripped (no leading/trailing whitespace that would change
    edit distance after normalization).
    """
    entry = draw(_catalog_entry)
    num_edits = draw(_num_edits)

    modified = entry
    for _ in range(num_edits):
        # Choose a random edit operation
        operation = draw(st.sampled_from(["insert", "delete", "substitute"]))

        if operation == "insert":
            pos = draw(st.integers(min_value=0, max_value=len(modified)))
            char = draw(_edit_char)
            modified = _apply_insertion(modified, pos, char)

        elif operation == "delete":
            # Can only delete if the string has characters left
            if len(modified) > 0:
                pos = draw(st.integers(min_value=0, max_value=len(modified) - 1))
                modified = _apply_deletion(modified, pos)
            else:
                # If string is empty, insert instead
                char = draw(_edit_char)
                modified = _apply_insertion(modified, 0, char)

        elif operation == "substitute":
            if len(modified) > 0:
                pos = draw(st.integers(min_value=0, max_value=len(modified) - 1))
                char = draw(_edit_char)
                # Ensure substitution actually changes the character
                assume(char != modified[pos])
                modified = _apply_substitution(modified, pos, char)
            else:
                # If string is empty, insert instead
                char = draw(_edit_char)
                modified = _apply_insertion(modified, 0, char)

    # Ensure the edited version is not empty and different from original
    assume(len(modified.strip()) > 0)
    
    # IMPORTANT: Ensure the edited version, when stripped, has the same edit
    # distance as the non-stripped version. This means no leading/trailing
    # whitespace should have been added or removed by the edits.
    # This prevents normalization from changing the effective edit distance.
    assume(modified == modified.strip())

    return (entry, modified, num_edits)


def _make_track(title: str) -> TrackResult:
    """Create a minimal TrackResult for catalog indexing."""
    return TrackResult(
        id="test-id",
        title=title,
        artist="Test Artist",
        thumbnail_url="http://example.com/thumb.jpg",
        source="test",
        source_url="http://example.com/track",
    )


class TestFuzzyCorrectionWithinEditDistance:
    """
    Property 7: Fuzzy Correction Within Edit Distance

    For any catalog entry, applying ≤ 2 single-character edits to it always
    results in find_correction() returning the original entry.

    **Validates: Requirements 4.1**
    """

    @settings(max_examples=10, deadline=None)
    @given(data=_edited_entry())
    def test_find_correction_returns_original_within_edit_distance(self, data):
        """
        For any catalog entry, applying at most 2 single-character edits
        (insertions, deletions, or substitutions) SHALL always result in
        find_correction() returning the original entry as the correction.

        # Feature: music-search-optimization, Property 7: Fuzzy Correction Within Edit Distance
        **Validates: Requirements 4.1**
        """
        original_entry, edited_query, num_edits = data

        # Set up a fresh catalog cache with only our test entry
        catalog = CatalogCache(max_entries=10000, ttl=3600)
        catalog.add_entries([_make_track(original_entry)])

        # Create FuzzyMatcher with the populated catalog
        matcher = FuzzyMatcher(catalog_cache=catalog)

        # find_correction should return the original entry
        correction = matcher.find_correction(edited_query)

        assert correction is not None, (
            f"find_correction() returned None for a query within edit distance {num_edits}!\n"
            f"  Original entry: {original_entry!r}\n"
            f"  Edited query:   {edited_query!r}\n"
            f"  Edits applied:  {num_edits}"
        )

        # The correction should match the original entry (case-insensitive comparison
        # since the catalog stores originals but matching is case-insensitive)
        assert correction.lower() == original_entry.lower(), (
            f"find_correction() returned wrong correction!\n"
            f"  Original entry: {original_entry!r}\n"
            f"  Edited query:   {edited_query!r}\n"
            f"  Got correction: {correction!r}\n"
            f"  Expected:       {original_entry!r}"
        )
