# Feature: music-search-optimization, Property 3: Query Pass-Through Preservation
"""
Property-based tests for the Language Processor module.

Property 3: Query Pass-Through Preservation
For any query string composed of characters from any Unicode script (Latin,
Devanagari, Tamil, Telugu, Kannada, Malayalam, Bengali, Gujarati, Gurmukhi,
or any other script), the Language Processor SHALL output the query unchanged —
the normalized_query field in SearchContext must be byte-for-byte identical to
the original input.

**Validates: Requirements 2.2, 2.3, 2.6**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.modules.music_language import LanguageProcessor


# --- Strategies for various Unicode alphabets ---

# Latin characters (basic + extended)
_latin_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll"),
        whitelist_characters=" ",
        min_codepoint=0x0041,
        max_codepoint=0x024F,
    ),
    min_size=0,
    max_size=200,
)

# Devanagari script (Hindi, Marathi, Sanskrit)
_devanagari_text = st.text(
    alphabet=st.characters(min_codepoint=0x0900, max_codepoint=0x097F),
    min_size=0,
    max_size=200,
)

# Tamil script
_tamil_text = st.text(
    alphabet=st.characters(min_codepoint=0x0B80, max_codepoint=0x0BFF),
    min_size=0,
    max_size=200,
)

# Telugu script
_telugu_text = st.text(
    alphabet=st.characters(min_codepoint=0x0C00, max_codepoint=0x0C7F),
    min_size=0,
    max_size=200,
)

# Kannada script
_kannada_text = st.text(
    alphabet=st.characters(min_codepoint=0x0C80, max_codepoint=0x0CFF),
    min_size=0,
    max_size=200,
)

# Malayalam script
_malayalam_text = st.text(
    alphabet=st.characters(min_codepoint=0x0D00, max_codepoint=0x0D7F),
    min_size=0,
    max_size=200,
)

# Bengali script
_bengali_text = st.text(
    alphabet=st.characters(min_codepoint=0x0980, max_codepoint=0x09FF),
    min_size=0,
    max_size=200,
)

# Gujarati script
_gujarati_text = st.text(
    alphabet=st.characters(min_codepoint=0x0A80, max_codepoint=0x0AFF),
    min_size=0,
    max_size=200,
)

# Gurmukhi script (Punjabi)
_gurmukhi_text = st.text(
    alphabet=st.characters(min_codepoint=0x0A00, max_codepoint=0x0A7F),
    min_size=0,
    max_size=200,
)

# Mixed Unicode: any valid text including all scripts above plus CJK, Arabic, etc.
_any_unicode_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # Exclude surrogates
    ),
    min_size=0,
    max_size=200,
)

# Combined strategy using one_of to cover all script families
_multi_script_text = st.one_of(
    _latin_text,
    _devanagari_text,
    _tamil_text,
    _telugu_text,
    _kannada_text,
    _malayalam_text,
    _bengali_text,
    _gujarati_text,
    _gurmukhi_text,
    _any_unicode_text,
)


class TestQueryPassThroughPreservation:
    """
    Property 3: Query Pass-Through Preservation

    For any Unicode string input, build_search_context().normalized_query
    is byte-for-byte identical to the original input (no transliteration).

    **Validates: Requirements 2.2, 2.3, 2.6**
    """

    @settings(max_examples=100, deadline=None)
    @given(query=_multi_script_text)
    def test_normalized_query_equals_original(self, query: str):
        """
        For any Unicode string input, the Language Processor's
        build_search_context() SHALL produce a normalized_query that is
        byte-for-byte identical to the original input — no transliteration
        or transformation is applied.

        # Feature: music-search-optimization, Property 3: Query Pass-Through Preservation
        **Validates: Requirements 2.2, 2.3, 2.6**
        """
        processor = LanguageProcessor()
        context = processor.build_search_context(query)

        # The normalized_query must be byte-for-byte identical to the input
        assert context.normalized_query == query, (
            f"normalized_query was modified!\n"
            f"  Input:      {query!r}\n"
            f"  normalized: {context.normalized_query!r}"
        )

        # Double-check with encoded bytes for true byte-level equality
        assert context.normalized_query.encode("utf-8") == query.encode("utf-8"), (
            f"UTF-8 byte mismatch!\n"
            f"  Input bytes:      {query.encode('utf-8')!r}\n"
            f"  normalized bytes: {context.normalized_query.encode('utf-8')!r}"
        )

    @settings(max_examples=100, deadline=None)
    @given(query=_any_unicode_text)
    def test_original_query_also_preserved(self, query: str):
        """
        The original_query field should also be preserved unchanged,
        ensuring both fields retain the exact input.

        # Feature: music-search-optimization, Property 3: Query Pass-Through Preservation
        **Validates: Requirements 2.2, 2.3, 2.6**
        """
        processor = LanguageProcessor()
        context = processor.build_search_context(query)

        assert context.original_query == query, (
            f"original_query was modified!\n"
            f"  Input:    {query!r}\n"
            f"  original: {context.original_query!r}"
        )
