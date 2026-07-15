"""Fuzzy Matcher for the music search optimization system.

This module provides typo correction, fuzzy search, and romanization
normalization for music queries. It uses the RapidFuzz library for
efficient edit distance and similarity computations against the
CatalogCache of recently seen track titles and artists.
"""

from __future__ import annotations

import re

try:
    from rapidfuzz import fuzz
    from rapidfuzz.distance import Levenshtein

    def _levenshtein_distance(s1: str, s2: str) -> int:
        return Levenshtein.distance(s1, s2)

    def _partial_ratio(s1: str, s2: str) -> float:
        return fuzz.partial_ratio(s1, s2) / 100.0

except ImportError:
    # Pure-Python fallback when rapidfuzz is unavailable (e.g., Vercel serverless)
    def _levenshtein_distance(s1: str, s2: str) -> int:
        if len(s1) < len(s2):
            return _levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]

    def _partial_ratio(s1: str, s2: str) -> float:
        if not s1 or not s2:
            return 0.0
        shorter, longer = (s1, s2) if len(s1) <= len(s2) else (s2, s1)
        best = 0.0
        l_short = len(shorter)
        for i in range(len(longer) - l_short + 1):
            sub = longer[i:i + l_short]
            matches = sum(a == b for a, b in zip(shorter, sub))
            ratio = matches / l_short
            if ratio > best:
                best = ratio
        return best


from jarvis.modules.music_catalog import CatalogCache
from jarvis.modules.music_models import FuzzyMatch


# Configurable romanization equivalence rules.
# Each tuple maps a longer romanized form to its canonical short form.
ROMANIZATION_RULES: list[tuple[str, str]] = [
    ("ee", "i"),
    ("oo", "u"),
    ("th", "t"),
    ("dh", "d"),
]


class FuzzyMatcher:
    """Detect typos, suggest corrections, and provide fuzzy-matched results.

    Uses the CatalogCache to obtain candidate strings and RapidFuzz for
    edit distance and similarity scoring.

    Attributes:
        catalog_cache: The CatalogCache instance used to retrieve candidates.
    """

    def __init__(self, catalog_cache: CatalogCache):
        """Initialize the FuzzyMatcher.

        Args:
            catalog_cache: A CatalogCache instance providing candidate strings
                for matching.
        """
        self.catalog_cache = catalog_cache

    def find_correction(self, query: str) -> str | None:
        """Return a corrected query if a catalog entry is within edit distance ≤ 2.

        Searches the catalog cache for candidates matching the query prefix/substring,
        then finds the best match (lowest edit distance) that is within 2 edits.

        Args:
            query: The user's search query string.

        Returns:
            The closest catalog entry if within edit distance 2, or None if no
            close match is found.
        """
        if not query or not query.strip():
            return None

        query_normalized = query.strip().lower()
        candidates = self.catalog_cache.get_candidates(query_normalized)

        # If prefix/substring candidates are empty, try getting all entries
        # by checking with single characters from the query
        if not candidates:
            seen = set()
            for char in query_normalized:
                if char.strip():
                    for candidate in self.catalog_cache.get_candidates(char):
                        if candidate not in seen:
                            seen.add(candidate)
                            candidates.append(candidate)

        best_match: str | None = None
        best_distance = float("inf")

        for candidate in candidates:
            candidate_lower = candidate.lower()
            distance = _levenshtein_distance(query_normalized, candidate_lower)
            if distance <= 2 and distance < best_distance:
                best_distance = distance
                best_match = candidate

        return best_match

    def fuzzy_search(self, query: str, max_results: int = 10) -> list[FuzzyMatch]:
        """Return partial/fuzzy matches ranked by similarity score.

        Computes similarity scores between the query and all catalog candidates,
        returning up to max_results matches sorted by descending score.

        Args:
            query: The user's search query string.
            max_results: Maximum number of results to return (default 10).

        Returns:
            A list of FuzzyMatch objects sorted by descending similarity score,
            containing at most max_results entries.
        """
        if not query or not query.strip():
            return []

        query_normalized = query.strip().lower()
        candidates = self.catalog_cache.get_candidates(query_normalized)

        # Also try to get broader candidates if initial set is small
        if len(candidates) < max_results:
            seen = set(c.lower() for c in candidates)
            for char in query_normalized:
                if char.strip():
                    for candidate in self.catalog_cache.get_candidates(char):
                        if candidate.lower() not in seen:
                            seen.add(candidate.lower())
                            candidates.append(candidate)

        matches: list[FuzzyMatch] = []

        for candidate in candidates:
            candidate_lower = candidate.lower()
            # Compute similarity score using partial_ratio for substring matching
            score = _partial_ratio(query_normalized, candidate_lower)
            distance = _levenshtein_distance(query_normalized, candidate_lower)

            # Only include if there's meaningful similarity (score > 0)
            if score > 0:
                matches.append(
                    FuzzyMatch(
                        original=candidate,
                        query=query,
                        score=score,
                        distance=distance,
                    )
                )

        # Sort by descending score, then by ascending distance for ties
        matches.sort(key=lambda m: (-m.score, m.distance))

        return matches[:max_results]

    def normalize_romanized(self, query: str) -> str:
        """Normalize common vowel-length and word-boundary variations.

        Applies romanization equivalence rules to convert the query to a
        canonical form for consistent comparison. Rules applied:
        - "ee" → "i", "oo" → "u", "th" → "t", "dh" → "d"
        - All spaces are collapsed (word boundary collapsing)

        The input is lowercased first for consistent comparison.

        Args:
            query: The romanized query string to normalize.

        Returns:
            The normalized canonical form of the query.
        """
        if not query:
            return query

        # Lowercase for consistent comparison
        result = query.lower()

        # Apply romanization equivalence rules (longer forms → canonical short forms)
        for long_form, short_form in ROMANIZATION_RULES:
            result = result.replace(long_form, short_form)

        # Collapse all spaces (word boundary collapsing)
        result = re.sub(r"\s+", "", result)

        return result
