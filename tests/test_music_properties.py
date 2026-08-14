# Feature: music-player, Property 1: Artist/Title Parsing Round-Trip
# Feature: music-player, Property 2: Music Request Detection Consistency
# Feature: music-player, Property 3: Search Response Structure Invariant
"""
Property-based tests for the music player backend.

Property 1: Artist/Title Parsing Round-Trip
For any YouTube video title string containing an artist and song name in a recognized
format (e.g., "Artist - Title", "Title by Artist"), calling extract_artist_title SHALL
produce an (artist, title) tuple where neither field is empty, and the concatenation of
artist and title contains all meaningful words from the original.

Property 3: Search Response Structure Invariant
For any non-empty query string passed to search_tracks, the returned list SHALL have
length between 0 and 10 inclusive, and every element in the list SHALL contain the keys
video_id, title, artist, and thumbnail_url with non-empty string values.

Validates: Requirements 1.1, 4.2, 6.2, 6.3
"""

import os
import re as _re_module
import string
from unittest.mock import patch, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from friday.modules.music import extract_artist_title


# --- Property 1: Artist/Title Parsing Round-Trip ---

# Strategies for generating meaningful artist/title words
_word_chars = string.ascii_letters + string.digits
_word_strategy = st.text(
    alphabet=_word_chars, min_size=1, max_size=20
).filter(lambda s: s.strip() != "")

_multi_word_strategy = st.lists(
    _word_strategy, min_size=1, max_size=4
).map(lambda words: " ".join(words))

# Common YouTube suffixes that may be appended
_youtube_suffixes = st.sampled_from([
    "",
    " (Official Video)",
    " (Official Audio)",
    " [Official Music Video]",
    " (Lyrics)",
    " [Lyric Video]",
    " (Official Visualizer)",
    " (HD)",
    " [Audio]",
    " (Live)",
])


def _meaningful_words(text: str) -> set[str]:
    """Extract meaningful words (alphanumeric, lowercased) from text."""
    return {w.lower() for w in _re_module.findall(r"[a-zA-Z0-9]+", text) if len(w) > 0}


@settings(max_examples=10, deadline=None)
@given(
    artist=_multi_word_strategy,
    title=_multi_word_strategy,
    suffix=_youtube_suffixes,
)
def test_artist_dash_title_round_trip(artist: str, title: str, suffix: str):
    """
    Property 1: Artist/Title Parsing Round-Trip (Artist - Title format)

    For any YouTube video title in the format "Artist - Title", calling
    extract_artist_title SHALL produce an (artist, title) tuple where
    neither field is empty, and the concatenation of artist and title
    contains all meaningful words from the original.

    # Feature: music-player, Property 1: Artist/Title Parsing Round-Trip
    **Validates: Requirements 1.1, 6.2**
    """
    youtube_title = f"{artist} - {title}{suffix}"

    result_artist, result_title = extract_artist_title(youtube_title)

    # Neither field should be empty
    assert result_artist.strip() != "", (
        f"Artist is empty for input: {youtube_title!r}"
    )
    assert result_title.strip() != "", (
        f"Title is empty for input: {youtube_title!r}"
    )

    # The concatenation should contain all meaningful words from the
    # original artist and title (excluding the YouTube suffix)
    original_words = _meaningful_words(artist) | _meaningful_words(title)
    result_words = _meaningful_words(result_artist) | _meaningful_words(result_title)

    assert original_words.issubset(result_words), (
        f"Missing words: {original_words - result_words} "
        f"from input: {youtube_title!r}, "
        f"got artist={result_artist!r}, title={result_title!r}"
    )


@settings(max_examples=10, deadline=None)
@given(
    artist=_multi_word_strategy,
    title=_multi_word_strategy,
    suffix=_youtube_suffixes,
)
def test_title_by_artist_round_trip(artist: str, title: str, suffix: str):
    """
    Property 1: Artist/Title Parsing Round-Trip (Title by Artist format)

    For any YouTube video title in the format "Title by Artist", calling
    extract_artist_title SHALL produce an (artist, title) tuple where
    neither field is empty, and the concatenation of artist and title
    contains all meaningful words from the original.

    # Feature: music-player, Property 1: Artist/Title Parsing Round-Trip
    **Validates: Requirements 1.1, 6.2**
    """
    # Ensure the title part doesn't contain " - " or ": " which would match
    # higher-priority patterns
    assume(" - " not in title and ": " not in title)
    # Ensure artist doesn't contain " by " to avoid ambiguous splits
    assume(" by " not in artist.lower())

    youtube_title = f"{title} by {artist}{suffix}"

    result_artist, result_title = extract_artist_title(youtube_title)

    # Neither field should be empty
    assert result_artist.strip() != "", (
        f"Artist is empty for input: {youtube_title!r}"
    )
    assert result_title.strip() != "", (
        f"Title is empty for input: {youtube_title!r}"
    )

    # The concatenation should contain all meaningful words from the
    # original artist and title (excluding the YouTube suffix)
    original_words = _meaningful_words(artist) | _meaningful_words(title)
    result_words = _meaningful_words(result_artist) | _meaningful_words(result_title)

    assert original_words.issubset(result_words), (
        f"Missing words: {original_words - result_words} "
        f"from input: {youtube_title!r}, "
        f"got artist={result_artist!r}, title={result_title!r}"
    )


@settings(max_examples=10, deadline=None)
@given(
    artist=_multi_word_strategy,
    title=_multi_word_strategy,
    suffix=_youtube_suffixes,
)
def test_artist_colon_title_round_trip(artist: str, title: str, suffix: str):
    """
    Property 1: Artist/Title Parsing Round-Trip (Artist: Title format)

    For any YouTube video title in the format "Artist: Title", calling
    extract_artist_title SHALL produce an (artist, title) tuple where
    neither field is empty, and the concatenation of artist and title
    contains all meaningful words from the original.

    # Feature: music-player, Property 1: Artist/Title Parsing Round-Trip
    **Validates: Requirements 1.1, 6.2**
    """
    # Ensure the artist part doesn't contain " - " which would match
    # a higher-priority pattern
    assume(" - " not in artist)

    youtube_title = f"{artist}: {title}{suffix}"

    result_artist, result_title = extract_artist_title(youtube_title)

    # Neither field should be empty
    assert result_artist.strip() != "", (
        f"Artist is empty for input: {youtube_title!r}"
    )
    assert result_title.strip() != "", (
        f"Title is empty for input: {youtube_title!r}"
    )

    # The concatenation should contain all meaningful words from the
    # original artist and title (excluding the YouTube suffix)
    original_words = _meaningful_words(artist) | _meaningful_words(title)
    result_words = _meaningful_words(result_artist) | _meaningful_words(result_title)

    assert original_words.issubset(result_words), (
        f"Missing words: {original_words - result_words} "
        f"from input: {youtube_title!r}, "
        f"got artist={result_artist!r}, title={result_title!r}"
    )


# --- Property 3: Search Response Structure Invariant ---

# Strategy to generate mock YouTube API response items
def youtube_item_strategy():
    """Generate a realistic YouTube API search result item."""
    return st.fixed_dictionaries({
        "id": st.fixed_dictionaries({
            "videoId": st.text(
                alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
                min_size=11,
                max_size=11,
            ),
        }),
        "snippet": st.fixed_dictionaries({
            "title": st.text(min_size=1, max_size=100).filter(lambda s: s.strip()),
            "thumbnails": st.fixed_dictionaries({
                "high": st.fixed_dictionaries({
                    "url": st.from_regex(r"https://i\.ytimg\.com/vi/[a-zA-Z0-9_-]{11}/hqdefault\.jpg", fullmatch=True),
                }),
            }),
        }),
    })


# Strategy for YouTube API response with variable number of items (0 to 10)
def youtube_response_strategy(max_results: int = 10):
    """Generate a full YouTube API JSON response with 0 to max_results items."""
    return st.lists(youtube_item_strategy(), min_size=0, max_size=max_results)


@settings(max_examples=10, deadline=None)
@given(
    query=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
    items=youtube_response_strategy(),
)
def test_search_tracks_response_structure_invariant(query, items):
    """
    Property 3: Search Response Structure Invariant

    For any non-empty query string passed to search_tracks, the returned list SHALL
    have length between 0 and 10 inclusive, and every element in the list SHALL
    contain the keys video_id, title, artist, and thumbnail_url with non-empty
    string values.

    **Validates: Requirements 4.2, 6.2, 6.3**
    """
    # Ensure query is non-empty after stripping
    assume(len(query.strip()) > 0)

    # Build a mock response that mimics the YouTube Data API v3 response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"items": items}

    with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-api-key-for-testing"}):
        with patch("requests.get", return_value=mock_response):
            from friday.modules.music import search_tracks

            results = search_tracks(query, max_results=10)

    # Property: length is between 0 and 10 inclusive
    assert 0 <= len(results) <= 10, (
        f"Expected 0-10 results, got {len(results)}"
    )

    # Property: every element has the required keys with non-empty string values
    required_keys = {"video_id", "title", "artist", "thumbnail_url"}
    for i, track in enumerate(results):
        # Check all required keys are present
        assert required_keys.issubset(track.keys()), (
            f"Track at index {i} missing keys: {required_keys - track.keys()}"
        )

        # Check each value is a non-empty string
        for key in required_keys:
            value = track[key]
            assert isinstance(value, str), (
                f"Track[{i}]['{key}'] is not a string: {type(value)}"
            )
            assert len(value) > 0, (
                f"Track[{i}]['{key}'] is empty"
            )


# Feature: music-player, Property 2: Music Request Detection Consistency
"""
Property 2: Music Request Detection Consistency

For any message string that begins with "play " followed by one or more
non-whitespace characters, is_music_request SHALL return True.
For any message string that does not contain the words "play", "put on",
or "queue", is_music_request SHALL return False.

Validates: Requirements 1.1
"""

import re as _re

from friday.modules.music import is_music_request


# Strategy: generates non-whitespace content (at least 1 char) for the song query
_non_whitespace_start = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs", "Zs", "Zl", "Zp", "Cc"),
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) > 0 and s[0] not in (" ", "\t", "\n", "\r", "\x0b", "\x0c"))


# Strategy: messages starting with "play " followed by non-whitespace content
_play_prefix_messages = st.builds(
    lambda suffix: "play " + suffix,
    _non_whitespace_start,
)


# Strategy: messages that do NOT contain "play", "put on", or "queue" keywords
_no_music_keywords = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
    min_size=0,
    max_size=200,
).filter(
    lambda s: not _re.search(r"\bplay\b", s, _re.IGNORECASE)
    and not _re.search(r"\bput on\b", s, _re.IGNORECASE)
    and not _re.search(r"\bqueue\b", s, _re.IGNORECASE)
)


class TestMusicRequestDetectionConsistency:
    """
    Property 2: Music Request Detection Consistency

    **Validates: Requirements 1.1**
    """

    @settings(max_examples=10, deadline=None)
    @given(message=_play_prefix_messages)
    def test_play_prefix_returns_true(self, message: str):
        """
        For any message starting with 'play ' followed by one or more
        non-whitespace characters, is_music_request SHALL return True.

        # Feature: music-player, Property 2: Music Request Detection Consistency
        """
        assert is_music_request(message) is True, (
            f"is_music_request should return True for message starting with "
            f"'play ' followed by non-whitespace: {message!r}"
        )

    @settings(max_examples=10, deadline=None)
    @given(message=_no_music_keywords)
    def test_no_keywords_returns_false(self, message: str):
        """
        For any message without the words 'play', 'put on', or 'queue',
        is_music_request SHALL return False.

        # Feature: music-player, Property 2: Music Request Detection Consistency
        """
        assert is_music_request(message) is False, (
            f"is_music_request should return False for message without music "
            f"keywords: {message!r}"
        )
