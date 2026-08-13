"""Property-based tests for API_Key_Store environment variable loading.

Uses Hypothesis to validate universal properties of the key store's
environment variable loading behavior.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from friday.modules.providers.key_store import API_Key_Store, ENV_VAR_MAPPING


# Providers that use a real {PROVIDER}_API_KEY-style environment variable.
# Ollama is excluded because OLLAMA_HOST is an endpoint (not an API key) and
# has special default-value behavior that is out of scope for Property 13.
API_KEY_PROVIDERS = [p for p in ENV_VAR_MAPPING if p != "ollama"]

# All environment variable names the store reads, so we can isolate the test
# environment from any real keys present in the shell / .env.
ALL_ENV_VARS = list(ENV_VAR_MAPPING.values())


# Strategy: a non-empty key string for a random subset of the API-key providers.
# Null characters are excluded because they cannot be stored in an OS
# environment variable value (this is an OS constraint, not behavior under test).
key_text = st.text(
    alphabet=st.characters(blacklist_characters="\x00"),
    min_size=1,
    max_size=64,
).filter(lambda s: s.strip() != "")

provider_key_maps = st.dictionaries(
    keys=st.sampled_from(API_KEY_PROVIDERS),
    values=key_text,
    min_size=1,
    max_size=len(API_KEY_PROVIDERS),
)


# ============================================================
# Property 13: Environment Variable Key Loading
# Validates: Requirements 10.2
# ============================================================

@settings(max_examples=200)
@given(provider_keys=provider_key_maps)
def test_property_13_env_var_key_loading(provider_keys):
    """
    **Validates: Requirements 10.2**

    For any environment variable following the naming pattern
    {PROVIDER}_API_KEY with a non-empty value, load_from_env() SHALL make
    that key available via get_key(provider). This is a round-trip property:
    the value set in the environment must be returned exactly by get_key(),
    and is_configured() must report True for every configured provider.
    """
    # Snapshot and isolate the environment so pre-existing real keys don't
    # interfere with the generated inputs.
    saved = {name: os.environ.get(name) for name in ALL_ENV_VARS}
    try:
        # Clear every mapped env var to start from a known-empty state.
        for name in ALL_ENV_VARS:
            os.environ.pop(name, None)

        # Set the generated subset of provider keys.
        for provider, key in provider_keys.items():
            os.environ[ENV_VAR_MAPPING[provider]] = key

        store = API_Key_Store()
        store.load_from_env()

        # Round-trip: every configured provider returns the exact value set.
        for provider, key in provider_keys.items():
            assert store.get_key(provider) == key
            assert store.is_configured(provider) is True

        # Providers whose env var was not set must not be configured.
        for provider in API_KEY_PROVIDERS:
            if provider not in provider_keys:
                assert store.get_key(provider) is None
                assert store.is_configured(provider) is False
    finally:
        # Restore the original environment.
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
