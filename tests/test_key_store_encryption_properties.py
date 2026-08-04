"""Property-based tests for encrypted API key storage.

Property 14: Encrypted Storage Round-Trip
- For any API key stored via set_key() to encrypted storage,
  load_from_encrypted_file() followed by get_key() SHALL return
  the identical key value.

Validates: Requirements 10.3
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Skip the whole module gracefully if cryptography is unavailable.
cryptography = pytest.importorskip(
    "cryptography",
    reason="cryptography library is required for encrypted storage tests",
)

from friday.modules.providers.key_store import API_Key_Store  # noqa: E402

# Providers that are treated as real API keys (Ollama is a host, not a key,
# and is only persisted when it differs from the default, so it is excluded
# from the general round-trip property).
PROVIDER_NAMES = [
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "grok",
    "openrouter",
    "cerebras",
]

# Non-empty key values. set_key() rejects empty/falsy keys, and the store
# lower-cases provider names, so any non-empty string is a valid key value.
key_values = st.text(min_size=1, max_size=200)
providers = st.sampled_from(PROVIDER_NAMES)


@settings(
    max_examples=200,
    deadline=None,  # Fernet + file I/O timing varies under full-suite CPU load
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(provider=providers, key=key_values)
def test_encrypted_storage_round_trip_single(
    tmp_path: Path, provider: str, key: str
) -> None:
    """Storing a single key, saving, and reloading returns the identical value.

    Validates: Requirements 10.3
    """
    encryption_key = API_Key_Store.generate_encryption_key()
    storage_path = tmp_path / "keys.enc"

    # Store the key and persist to an encrypted file.
    writer = API_Key_Store(encryption_key=encryption_key)
    assert writer.set_key(provider, key) is True
    assert writer.save_to_encrypted_file(storage_path) is True

    # A brand-new store with the same encryption key must recover the key.
    reader = API_Key_Store(encryption_key=encryption_key)
    assert reader.load_from_encrypted_file(storage_path) is True

    assert reader.get_key(provider) == key


@settings(
    max_examples=200,
    deadline=None,  # Fernet + file I/O timing varies under full-suite CPU load
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    keys=st.dictionaries(
        keys=providers,
        values=key_values,
        min_size=1,
        max_size=len(PROVIDER_NAMES),
    )
)
def test_encrypted_storage_round_trip_multiple(
    tmp_path: Path, keys: dict[str, str]
) -> None:
    """Multiple keys survive a save/load round-trip unchanged.

    Validates: Requirements 10.3
    """
    encryption_key = API_Key_Store.generate_encryption_key()
    storage_path = tmp_path / "keys.enc"

    writer = API_Key_Store(encryption_key=encryption_key)
    for provider, key in keys.items():
        assert writer.set_key(provider, key) is True
    assert writer.save_to_encrypted_file(storage_path) is True

    reader = API_Key_Store(encryption_key=encryption_key)
    assert reader.load_from_encrypted_file(storage_path) is True

    for provider, key in keys.items():
        assert reader.get_key(provider) == key
