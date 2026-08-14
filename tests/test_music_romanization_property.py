# Feature: music-search-optimization, Property 5: Romanization Normalization Equivalence
"""
Property-based tests for the Fuzzy Matcher's normalize_romanized function.

Property 5: Romanization Normalization Equivalence
For any pair of romanized Indian-language strings that differ only by common
vowel-length variations ("ee"↔"i", "oo"↔"u") or word-boundary variations
("Tum hi"↔"Tumhi"), the normalize_romanized function SHALL produce identical
canonical output strings.

**Validates: Requirements 2.5, 4.5**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.modules.music_fuzzy import FuzzyMatcher
from friday.modules.music_catalog import CatalogCache


# --- Strategies ---

# Characters that do NOT participate in any equivalence rule.
# Avoiding: 'e' (part of "ee"), 'o' (part of "oo"), 'i' (target of "ee"→"i"),
# 'u' (target of "oo"→"u"), 't' (part of "th"→"t"), 'h' (part of "th"/"dh"),
# 'd' (part of "dh"→"d")
# Safe consonants/vowels that won't interact with normalization rules.
_SAFE_CHARS = "abcfgjklmnpqrsvwxyz"

_safe_segment = st.text(alphabet=st.sampled_from(_SAFE_CHARS), min_size=1, max_size=6)

# Equivalence pairs: (short_form, long_form)
# The normalizer maps long_form → short_form
EQUIVALENCE_PAIRS = [
    ("i", "ee"),
    ("u", "oo"),
]


@st.composite
def romanized_equivalence_pair(draw):
    """Generate a pair of strings that differ only by romanization equivalences.

    Strategy:
    1. Build a string from safe segments interleaved with equivalence tokens
    2. For the base version, use the short form (canonical)
    3. For the variant, randomly use the long form
    4. Since safe segments don't contain rule characters, substitutions are unambiguous
    """
    # Generate 1-4 segments with 0-3 equivalence tokens between them
    num_segments = draw(st.integers(min_value=1, max_value=4))
    segments = [draw(_safe_segment) for _ in range(num_segments)]

    # Insert equivalence tokens between/around segments
    num_tokens = draw(st.integers(min_value=1, max_value=3))
    tokens_short = []
    tokens_long = []
    for _ in range(num_tokens):
        short_form, long_form = draw(st.sampled_from(EQUIVALENCE_PAIRS))
        tokens_short.append(short_form)
        tokens_long.append(long_form)

    # Build strings: interleave segments with tokens
    base_parts = []
    variant_parts = []
    for idx in range(num_segments):
        base_parts.append(segments[idx])
        variant_parts.append(segments[idx])
        if idx < num_tokens:
            base_parts.append(tokens_short[idx])
            variant_parts.append(tokens_long[idx])

    base = "".join(base_parts)
    variant = "".join(variant_parts)

    return base, variant


@st.composite
def word_boundary_variation_pair(draw):
    """Generate a pair of strings that differ only by word boundaries (spaces).

    Strategy:
    1. Generate multiple safe words
    2. Create one version with spaces, one without
    3. Both should normalize to the same output (spaces are collapsed)
    """
    words = draw(st.lists(_safe_segment, min_size=2, max_size=4))

    # Version with spaces
    with_spaces = " ".join(words)

    # Version without spaces (concatenated)
    without_spaces = "".join(words)

    return with_spaces, without_spaces


@st.composite
def combined_variation_pair(draw):
    """Generate pairs that combine both romanization equivalences AND word-boundary variations.

    Strategy:
    1. Build multiple words from safe segments + equivalence tokens
    2. For the base: use short forms + spaces between words
    3. For the variant: use long forms + optionally no spaces
    4. Both should normalize identically
    """
    num_words = draw(st.integers(min_value=1, max_value=3))

    base_words = []
    variant_words = []

    for _ in range(num_words):
        # Each word: safe_prefix + optional equivalence token + safe_suffix
        prefix = draw(_safe_segment)
        suffix = draw(_safe_segment)

        has_token = draw(st.booleans())
        if has_token:
            short_form, long_form = draw(st.sampled_from(EQUIVALENCE_PAIRS))
            base_words.append(prefix + short_form + suffix)
            variant_words.append(prefix + long_form + suffix)
        else:
            base_words.append(prefix + suffix)
            variant_words.append(prefix + suffix)

    # Base uses spaces between words
    base = " ".join(base_words)

    # Variant may or may not use spaces
    use_spaces = draw(st.booleans())
    if use_spaces:
        variant = " ".join(variant_words)
    else:
        variant = "".join(variant_words)

    return base, variant


# --- Helper ---

def _create_matcher() -> FuzzyMatcher:
    """Create a FuzzyMatcher instance with an empty CatalogCache."""
    cache = CatalogCache(max_entries=100, ttl=3600)
    return FuzzyMatcher(catalog_cache=cache)


# --- Property Tests ---

class TestRomanizationNormalizationEquivalence:
    """
    Property 5: Romanization Normalization Equivalence

    For any pair of romanized strings that differ only by "ee"↔"i", "oo"↔"u",
    or word-boundary variations, normalize_romanized() SHALL produce identical
    canonical output strings.

    **Validates: Requirements 2.5, 4.5**
    """

    @settings(max_examples=10, deadline=None)
    @given(pair=romanized_equivalence_pair())
    def test_vowel_length_equivalence(self, pair: tuple[str, str]):
        """
        Strings differing only by vowel-length variations ("ee"↔"i", "oo"↔"u")
        produce identical normalize_romanized() output.

        # Feature: music-search-optimization, Property 5: Romanization Normalization Equivalence
        **Validates: Requirements 2.5, 4.5**
        """
        base, variant = pair
        matcher = _create_matcher()

        normalized_base = matcher.normalize_romanized(base)
        normalized_variant = matcher.normalize_romanized(variant)

        assert normalized_base == normalized_variant, (
            f"Romanization equivalence violated!\n"
            f"  Base:             {base!r}\n"
            f"  Variant:          {variant!r}\n"
            f"  Normalized base:  {normalized_base!r}\n"
            f"  Normalized var:   {normalized_variant!r}"
        )

    @settings(max_examples=10, deadline=None)
    @given(pair=word_boundary_variation_pair())
    def test_word_boundary_equivalence(self, pair: tuple[str, str]):
        """
        Strings differing only by word boundaries (spaces vs. no spaces)
        produce identical normalize_romanized() output.

        # Feature: music-search-optimization, Property 5: Romanization Normalization Equivalence
        **Validates: Requirements 2.5, 4.5**
        """
        with_spaces, without_spaces = pair
        matcher = _create_matcher()

        normalized_with = matcher.normalize_romanized(with_spaces)
        normalized_without = matcher.normalize_romanized(without_spaces)

        assert normalized_with == normalized_without, (
            f"Word boundary equivalence violated!\n"
            f"  With spaces:    {with_spaces!r}\n"
            f"  Without spaces: {without_spaces!r}\n"
            f"  Normalized (w): {normalized_with!r}\n"
            f"  Normalized (wo):{normalized_without!r}"
        )

    @settings(max_examples=10, deadline=None)
    @given(pair=combined_variation_pair())
    def test_combined_romanization_and_boundary_equivalence(self, pair: tuple[str, str]):
        """
        Strings differing by both vowel-length and word-boundary variations
        produce identical normalize_romanized() output.

        # Feature: music-search-optimization, Property 5: Romanization Normalization Equivalence
        **Validates: Requirements 2.5, 4.5**
        """
        base, variant = pair
        matcher = _create_matcher()

        normalized_base = matcher.normalize_romanized(base)
        normalized_variant = matcher.normalize_romanized(variant)

        assert normalized_base == normalized_variant, (
            f"Combined equivalence violated!\n"
            f"  Base:             {base!r}\n"
            f"  Variant:          {variant!r}\n"
            f"  Normalized base:  {normalized_base!r}\n"
            f"  Normalized var:   {normalized_variant!r}"
        )
