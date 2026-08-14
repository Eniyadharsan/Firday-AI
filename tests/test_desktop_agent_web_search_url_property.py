"""Property-based tests for web-search URL construction.

Property 9: Web-search URL construction
- For any search query string, the web-search command SHALL construct a
  well-formed search URL that contains the URL-encoded query.

The Command Executor builds the URL via ``build_search_url``
(friday/desktop_agent/executor.py), percent-encoding the query with
``urllib.parse.quote_plus`` and substituting it into ``SEARCH_URL_TEMPLATE``
before handing it to the default browser (Req 4.3). This property exercises
``build_search_url`` across arbitrary query text -- including spaces, reserved
URL characters, unicode, and empty strings -- and asserts that:

  * the result is a well-formed ``https`` URL with the expected search path,
  * the ``q`` query parameter contains exactly the URL-encoded query, and
  * decoding the ``q`` parameter round-trips back to the original query.

Validates: Requirements 4.3
"""

from __future__ import annotations

import urllib.parse

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.executor import build_search_url


# Arbitrary query text: general unicode text plus targeted samples that stress
# URL encoding (spaces, reserved characters, query delimiters, and empty).
_query = st.one_of(
    st.text(),
    st.sampled_from(
        [
            "",
            "hello world",
            "a b c",
            "c++ tutorial",
            "1 & 2 = 3",
            "search?q=nested",
            "100% coverage",
            "path/to/thing",
            "#hashtag @handle",
            "café résumé naïve",
            "emoji 😀 test",
            "quotes \"and\" 'apostrophes'",
        ]
    ),
)


# Feature: friday-desktop-agent, Property 9: Web-search URL construction
@settings(max_examples=200)
@given(query=_query)
def test_web_search_url_contains_encoded_query(query: str) -> None:
    """For any query, the URL is well-formed and carries the encoded query.

    Validates: Requirements 4.3
    """
    url = build_search_url(query)

    # Well-formed https search URL with the expected host and path.
    parsed = urllib.parse.urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.google.com"
    assert parsed.path == "/search"

    # The URL literally contains the URL-encoded query.
    encoded = urllib.parse.quote_plus(query)
    assert encoded in url

    # The ``q`` parameter round-trips back to the original query, proving the
    # query is preserved (not truncated or corrupted) through encoding.
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    assert params.get("q", [""])[0] == query
