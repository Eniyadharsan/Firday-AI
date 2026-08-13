"""Example-based unit tests for API_Key_Store.

These tests cover key storage behavior using concrete examples and edge cases:
- Loading keys from environment variables
- Ollama default host handling
- Encryption/decryption failure handling (Requirement 10.6)
- set_key / remove_key round-trip
- validate_key format checks (no network calls)
- ProviderType enum acceptance for get/set/is_configured

Requirements: 10.2, 10.3, 10.6

Note: These are example-based unit tests (pytest), NOT property-based tests.
No real network calls are made - the API validation path is either avoided
(malformed keys fail format checks first) or monkeypatched.
"""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from friday.modules.providers.key_store import (
    DEFAULT_OLLAMA_HOST,
    ENV_VAR_MAPPING,
    API_Key_Store,
)
from friday.modules.providers.models import ProviderStatus, ProviderType


# All provider env vars that should be cleared before env-based tests so the
# host environment doesn't leak real keys into the assertions.
ALL_ENV_VARS = list(ENV_VAR_MAPPING.values())


@pytest.fixture
def clean_env(monkeypatch):
    """Remove all provider-related environment variables for a clean slate."""
    for env_var in ALL_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# Environment variable loading (Requirement 10.2)
# ---------------------------------------------------------------------------

class TestLoadFromEnv:
    def test_loads_set_keys_and_marks_configured(self, clean_env):
        clean_env.setenv("OPENAI_API_KEY", "sk-openai-test-123")
        clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-test-456")

        store = API_Key_Store()
        store.load_from_env()

        assert store.get_key("openai") == "sk-openai-test-123"
        assert store.get_key("anthropic") == "sk-ant-test-456"
        assert store.is_configured("openai") is True
        assert store.is_configured("anthropic") is True
        assert store.get_provider_status("openai") == ProviderStatus.OPERATIONAL
        assert store.get_provider_status("anthropic") == ProviderStatus.OPERATIONAL

    def test_unset_providers_are_not_configured(self, clean_env):
        # Only set openai; everything else should be NOT_CONFIGURED.
        clean_env.setenv("OPENAI_API_KEY", "sk-openai-only")

        store = API_Key_Store()
        store.load_from_env()

        assert store.is_configured("deepseek") is False
        assert store.get_key("deepseek") is None
        assert store.get_provider_status("deepseek") == ProviderStatus.NOT_CONFIGURED
        assert store.is_configured("grok") is False
        assert store.get_provider_status("openrouter") == ProviderStatus.NOT_CONFIGURED

    def test_empty_env_value_is_not_configured(self, clean_env):
        clean_env.setenv("CEREBRAS_API_KEY", "")

        store = API_Key_Store()
        store.load_from_env()

        assert store.is_configured("cerebras") is False
        assert store.get_provider_status("cerebras") == ProviderStatus.NOT_CONFIGURED


# ---------------------------------------------------------------------------
# Ollama default host (Requirement 10.3 / Requirement 5)
# ---------------------------------------------------------------------------

class TestOllamaDefaultHost:
    def test_default_host_when_unset(self, clean_env):
        # OLLAMA_HOST is cleared by the clean_env fixture.
        store = API_Key_Store()
        store.load_from_env()

        assert store.get_key("ollama") == DEFAULT_OLLAMA_HOST
        assert store.get_key("ollama") == "http://localhost:11434"
        assert store.is_configured("ollama") is True
        assert store.get_provider_status("ollama") == ProviderStatus.OPERATIONAL

    def test_custom_host_when_set(self, clean_env):
        clean_env.setenv("OLLAMA_HOST", "http://192.168.1.50:11434")

        store = API_Key_Store()
        store.load_from_env()

        assert store.get_key("ollama") == "http://192.168.1.50:11434"


# ---------------------------------------------------------------------------
# Encryption / decryption failure handling (Requirement 10.6)
# ---------------------------------------------------------------------------

class TestEncryptedFileFailureHandling:
    def test_corrupt_file_returns_false_and_does_not_crash(self, tmp_path):
        key = Fernet.generate_key().decode("utf-8")
        store = API_Key_Store(encryption_key=key)

        corrupt_file = tmp_path / "keys.enc"
        corrupt_file.write_bytes(b"this-is-not-valid-fernet-ciphertext-garbage")

        result = store.load_from_encrypted_file(corrupt_file)

        assert result is False
        # Providers should not have been loaded, and should be NOT_CONFIGURED.
        assert store.is_configured("openai") is False
        assert store.get_provider_status("openai") == ProviderStatus.NOT_CONFIGURED

    def test_wrong_encryption_key_returns_false(self, tmp_path):
        # Encrypt with one key...
        write_key = Fernet.generate_key().decode("utf-8")
        writer = API_Key_Store(encryption_key=write_key)
        writer.set_key("openai", "sk-secret-key")

        enc_file = tmp_path / "keys.enc"
        assert writer.save_to_encrypted_file(enc_file) is True

        # ...then try to read with a different key.
        wrong_key = Fernet.generate_key().decode("utf-8")
        reader = API_Key_Store(encryption_key=wrong_key)

        result = reader.load_from_encrypted_file(enc_file)

        assert result is False
        assert reader.is_configured("openai") is False
        assert reader.get_provider_status("openai") == ProviderStatus.NOT_CONFIGURED

    def test_missing_file_returns_false(self, tmp_path):
        key = Fernet.generate_key().decode("utf-8")
        store = API_Key_Store(encryption_key=key)

        result = store.load_from_encrypted_file(tmp_path / "does-not-exist.enc")

        assert result is False

    def test_encrypted_round_trip_succeeds(self, tmp_path):
        # Sanity check that a correct key round-trips (Property 14).
        key = Fernet.generate_key().decode("utf-8")
        writer = API_Key_Store(encryption_key=key)
        writer.set_key("openai", "sk-round-trip")

        enc_file = tmp_path / "keys.enc"
        assert writer.save_to_encrypted_file(enc_file) is True

        reader = API_Key_Store(encryption_key=key)
        assert reader.load_from_encrypted_file(enc_file) is True
        assert reader.get_key("openai") == "sk-round-trip"

    def test_valid_fernet_but_non_dict_json_returns_false(self, tmp_path):
        # A validly-encrypted payload that decrypts to a JSON list, not a dict.
        key = Fernet.generate_key().decode("utf-8")
        fernet = Fernet(key.encode())
        enc_file = tmp_path / "keys.enc"
        enc_file.write_bytes(fernet.encrypt(json.dumps(["not", "a", "dict"]).encode()))

        store = API_Key_Store(encryption_key=key)
        result = store.load_from_encrypted_file(enc_file)

        assert result is False


# ---------------------------------------------------------------------------
# set_key / remove_key
# ---------------------------------------------------------------------------

class TestSetAndRemoveKey:
    def test_set_key_then_configured(self):
        store = API_Key_Store()

        assert store.is_configured("openai") is False
        assert store.set_key("openai", "sk-abc") is True
        assert store.is_configured("openai") is True
        assert store.get_key("openai") == "sk-abc"
        assert store.get_provider_status("openai") == ProviderStatus.OPERATIONAL

    def test_set_empty_key_returns_false(self):
        store = API_Key_Store()
        assert store.set_key("openai", "") is False
        assert store.is_configured("openai") is False

    def test_remove_key(self):
        store = API_Key_Store()
        store.set_key("openai", "sk-abc")
        assert store.is_configured("openai") is True

        assert store.remove_key("openai") is True
        assert store.is_configured("openai") is False
        assert store.get_key("openai") is None
        assert store.get_provider_status("openai") == ProviderStatus.NOT_CONFIGURED

    def test_remove_missing_key_returns_false(self):
        store = API_Key_Store()
        assert store.remove_key("openai") is False


# ---------------------------------------------------------------------------
# validate_key format checks (no network)
# ---------------------------------------------------------------------------

class TestValidateKeyFormat:
    def test_empty_key_is_invalid(self):
        store = API_Key_Store()
        is_valid, msg = store.validate_key("openai", "")
        assert is_valid is False
        assert msg is not None

    def test_openai_key_without_sk_prefix_is_invalid(self):
        store = API_Key_Store()
        is_valid, msg = store.validate_key("openai", "not-a-real-key")
        assert is_valid is False
        assert "sk-" in msg

    def test_anthropic_key_without_prefix_is_invalid(self):
        store = API_Key_Store()
        is_valid, msg = store.validate_key("anthropic", "sk-missing-ant")
        assert is_valid is False
        assert "sk-ant-" in msg

    def test_ollama_host_without_url_scheme_is_invalid(self):
        store = API_Key_Store()
        is_valid, msg = store.validate_key("ollama", "localhost:11434")
        assert is_valid is False
        assert msg is not None

    def test_valid_format_reaches_api_path(self, monkeypatch):
        # Monkeypatch the network call so a well-formatted key validates
        # without touching the network.
        store = API_Key_Store()
        monkeypatch.setattr(
            store, "_validate_key_with_api", lambda provider, key: (True, None)
        )

        is_valid, msg = store.validate_key("openai", "sk-well-formatted-key")
        assert is_valid is True
        assert msg is None


# ---------------------------------------------------------------------------
# ProviderType enum acceptance
# ---------------------------------------------------------------------------

class TestProviderTypeEnumAcceptance:
    def test_set_and_get_with_enum(self):
        store = API_Key_Store()
        store.set_key(ProviderType.OPENAI, "sk-enum-key")

        assert store.get_key(ProviderType.OPENAI) == "sk-enum-key"
        assert store.is_configured(ProviderType.OPENAI) is True

    def test_enum_and_string_are_equivalent(self):
        store = API_Key_Store()
        store.set_key("anthropic", "sk-ant-mixed")

        # Set via string, read via enum.
        assert store.get_key(ProviderType.ANTHROPIC) == "sk-ant-mixed"
        assert store.is_configured(ProviderType.ANTHROPIC) is True

        # Remove via enum.
        assert store.remove_key(ProviderType.ANTHROPIC) is True
        assert store.is_configured("anthropic") is False

    def test_get_provider_status_with_enum(self):
        store = API_Key_Store()
        store.set_key(ProviderType.GEMINI, "gemini-key")
        assert store.get_provider_status(ProviderType.GEMINI) == ProviderStatus.OPERATIONAL
