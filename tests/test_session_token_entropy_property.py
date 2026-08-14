# Feature: friday-desktop-agent, Property 2: Session token entropy and uniqueness
"""Property-based test for Desktop_Agent session token entropy and uniqueness.

Implements Property 2 from the friday-desktop-agent design:

    For any sequence of issued session tokens, every token SHALL contain at
    least 128 bits of entropy (meet the minimum length floor) and no two
    issued tokens SHALL collide.

The Session Token Authenticator issues tokens via
``secrets.token_urlsafe(32)``, which draws 32 random bytes (256 bits) and
encodes them as URL-safe base64. Each base64 character encodes 6 bits, so the
128-bit entropy floor corresponds to a minimum encoded length of
``ceil(128 / 6) == 22`` characters. This test asserts every issued token meets
that floor and that all issued token values across the sequence are unique.

**Validates: Requirements 1.4**
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from friday.desktop_agent.auth import SessionTokenAuthenticator


# Minimum encoded length that guarantees at least 128 bits of entropy for a
# URL-safe base64 token (6 bits per character): ceil(128 / 6) == 22.
BITS_PER_URLSAFE_CHAR = 6
MIN_ENTROPY_BITS = 128
MIN_TOKEN_LENGTH = math.ceil(MIN_ENTROPY_BITS / BITS_PER_URLSAFE_CHAR)


# A sequence of monotonically-usable issuance times. The concrete timestamps
# do not affect entropy or uniqueness, but generating a variable-length list
# drives a variable number of token issuances per example.
issuance_times = st.lists(
    st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=50,
)


@settings(max_examples=100)
@given(times=issuance_times)
def test_property_2_token_entropy_and_uniqueness(times):
    """
    **Validates: Requirements 1.4**

    For any sequence of issued session tokens, every token meets the 128-bit
    entropy floor (minimum encoded length) and no two issued token values
    collide.

    # Feature: friday-desktop-agent, Property 2: Session token entropy and uniqueness
    """
    authenticator = SessionTokenAuthenticator()

    issued_values = []
    for now in times:
        token = authenticator.issue_token(now=now)
        issued_values.append(token.value)

        # Entropy floor: the encoded token must be long enough to carry at
        # least 128 bits of entropy (>= 22 URL-safe base64 characters).
        encoded_entropy_bits = len(token.value) * BITS_PER_URLSAFE_CHAR
        assert len(token.value) >= MIN_TOKEN_LENGTH, (
            f"token length {len(token.value)} below the {MIN_TOKEN_LENGTH}-char "
            f"floor for {MIN_ENTROPY_BITS} bits of entropy"
        )
        assert encoded_entropy_bits >= MIN_ENTROPY_BITS, (
            f"token encodes only {encoded_entropy_bits} bits, "
            f"below the {MIN_ENTROPY_BITS}-bit floor"
        )

    # Uniqueness: no two issued tokens across the sequence collide.
    assert len(set(issued_values)) == len(issued_values), (
        "issued session tokens must be unique; a collision was detected"
    )
