"""Language processing module for the music search optimization system.

This module provides script detection, devotional intent recognition,
and search context building for multi-language music queries. It handles
Unicode script identification and keyword-based devotional classification
without performing any transliteration — queries are passed through unchanged.
"""

from __future__ import annotations

import re
import unicodedata

from jarvis.modules.music_models import SearchContext


# Unicode code point ranges for supported scripts
_SCRIPT_RANGES: list[tuple[int, int, str]] = [
    (0x0900, 0x097F, "Devanagari"),
    (0x0980, 0x09FF, "Bengali"),
    (0x0A00, 0x0A7F, "Gurmukhi"),
    (0x0A80, 0x0AFF, "Gujarati"),
    (0x0B80, 0x0BFF, "Tamil"),
    (0x0C00, 0x0C7F, "Telugu"),
    (0x0C80, 0x0CFF, "Kannada"),
    (0x0D00, 0x0D7F, "Malayalam"),
]


# Devotional keywords — all lowercase for case-insensitive matching
DEVOTIONAL_KEYWORDS: set[str] = {
    "bhajan",
    "kirtan",
    "hymn",
    "naat",
    "shabad",
    "stotram",
    "paadal",
    "keerthanai",
    "azan",
    "psalm",
    "gospel",
}


# Mapping from devotional keyword to tradition label
DEVOTIONAL_TRADITIONS: dict[str, str] = {
    "bhajan": "Hindu Bhajan",
    "kirtan": "Hindu Kirtan",
    "hymn": "Christian Hymn",
    "psalm": "Christian Psalm",
    "gospel": "Christian Gospel",
    "naat": "Islamic Naat",
    "azan": "Islamic Azan",
    "shabad": "Sikh Shabad",
    "stotram": "Hindu Stotram",
    "paadal": "Tamil Devotional",
    "keerthanai": "Tamil Devotional",
}


class LanguageProcessor:
    """Processes search queries for script detection and devotional intent.

    The LanguageProcessor analyses incoming search queries to determine:
    - Which Unicode scripts are present (Latin, Devanagari, Tamil, etc.)
    - Whether the query contains devotional music keywords
    - The appropriate tradition label for devotional queries

    It produces a SearchContext that downstream components use for ranking
    and source selection. Critically, the normalized_query is always
    byte-for-byte identical to the original input — no transliteration
    is performed.
    """

    DEVOTIONAL_KEYWORDS = DEVOTIONAL_KEYWORDS
    DEVOTIONAL_TRADITIONS = DEVOTIONAL_TRADITIONS

    def detect_script(self, text: str) -> list[str]:
        """Detect Unicode script blocks present in the text.

        Examines each character in the text and identifies which writing
        systems are used. Supports Latin, Devanagari, Tamil, Telugu,
        Kannada, Malayalam, Bengali, Gujarati, and Gurmukhi.

        Args:
            text: The input string to analyze.

        Returns:
            A list of unique script names detected, in the order they
            were first encountered. Returns an empty list if no
            supported script characters are found.
        """
        detected: list[str] = []
        seen: set[str] = set()

        for char in text:
            cp = ord(char)

            # Check Latin: Basic Latin + Latin Extended
            if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or \
               (0x00C0 <= cp <= 0x024F):
                script = "Latin"
            else:
                script = self._match_indic_script(cp)

            if script and script not in seen:
                seen.add(script)
                detected.append(script)

        return detected

    def has_devotional_intent(self, query: str) -> tuple[bool, str | None]:
        """Check whether the query contains a devotional keyword.

        Performs case-insensitive, whole-word matching against the known
        set of devotional keywords. Uses word boundary detection to avoid
        false positives (e.g., "gospel" in "gospelize" would not match
        without boundaries, but "gospel" as a standalone word does).

        Args:
            query: The search query string.

        Returns:
            A tuple of (is_devotional, tradition_label). If a devotional
            keyword is found, returns (True, tradition_label). If no
            keyword is found, returns (False, None). When multiple keywords
            are present, returns the tradition of the first one found.
        """
        query_lower = query.lower()

        for keyword in DEVOTIONAL_KEYWORDS:
            # Use regex word boundaries for whole-word matching
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, query_lower):
                tradition = DEVOTIONAL_TRADITIONS.get(keyword)
                return (True, tradition)

        return (False, None)

    def build_search_context(self, query: str) -> SearchContext:
        """Build a SearchContext from the raw query string.

        Analyses the query for script composition and devotional intent,
        then produces a SearchContext. The normalized_query field is set
        to be byte-for-byte identical to the original query — no
        transliteration or transformation is applied.

        Args:
            query: The raw search query as submitted by the user.

        Returns:
            A SearchContext populated with script info, devotional flags,
            and the original query preserved unchanged.
        """
        detected_scripts = self.detect_script(query)
        is_devotional, tradition = self.has_devotional_intent(query)

        # Find all devotional keywords present in the query
        keywords_found = self._find_all_devotional_keywords(query)

        return SearchContext(
            original_query=query,
            normalized_query=query,  # Pass-through, no transliteration
            detected_scripts=detected_scripts,
            is_devotional=is_devotional,
            devotional_tradition=tradition,
            devotional_keywords_found=keywords_found,
        )

    def _match_indic_script(self, code_point: int) -> str | None:
        """Match a Unicode code point to an Indic script range.

        Args:
            code_point: The Unicode code point to check.

        Returns:
            The script name if matched, or None.
        """
        for start, end, name in _SCRIPT_RANGES:
            if start <= code_point <= end:
                return name
        return None

    def _find_all_devotional_keywords(self, query: str) -> list[str]:
        """Find all devotional keywords present in the query.

        Args:
            query: The search query string.

        Returns:
            A list of devotional keywords found (lowercase), in the order
            they appear in the DEVOTIONAL_KEYWORDS set iteration.
        """
        query_lower = query.lower()
        found: list[str] = []

        for keyword in DEVOTIONAL_KEYWORDS:
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, query_lower):
                found.append(keyword)

        return found
