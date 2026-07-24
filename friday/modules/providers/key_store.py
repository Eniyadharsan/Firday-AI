"""Secure API key storage for provider adapters.

This module provides the API_Key_Store class for securely storing and managing
API keys for all AI providers. Keys can be loaded from environment variables
or encrypted file storage using Fernet symmetric encryption.

Security Principles:
- Keys are stored only on the backend server (never transmitted to frontend)
- Encrypted storage uses Fernet (AES-128-CBC with HMAC)
- Keys are validated before being stored
- Decryption failures are logged and providers marked as Not_Configured

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None
    InvalidToken = Exception

from friday.modules.providers.models import ProviderStatus, ProviderType


logger = logging.getLogger(__name__)


# Environment variable mapping for each provider
# Maps provider name (lowercase) to the environment variable name
ENV_VAR_MAPPING: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_AI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "grok": "XAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "ollama": "OLLAMA_HOST",  # Note: This is an endpoint, not an API key
}

# Default Ollama host if not configured
DEFAULT_OLLAMA_HOST = "http://localhost:11434"


class API_Key_Store:
    """Secure storage for provider API keys.
    
    Supports loading keys from environment variables or encrypted
    file storage. Keys are never transmitted to the frontend.
    
    The store maintains an in-memory cache of keys and can persist
    them to encrypted storage for persistence across restarts.
    
    Attributes:
        _keys: In-memory dictionary of provider keys
        _encryption_key: Fernet key for encrypting/decrypting stored keys
        _storage_path: Path to encrypted key storage file
        _provider_status: Tracks status of each provider for decryption failures
        
    Example:
        # Create store and load keys from environment
        store = API_Key_Store()
        store.load_from_env()
        
        # Get a key for a provider
        openai_key = store.get_key("openai")
        
        # Store with encryption
        store = API_Key_Store(encryption_key="your-fernet-key")
        store.set_key("openai", "sk-...")
        store.save_to_encrypted_file(Path(".friday-data/keys.enc"))
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """Initialize the API key store.
        
        Args:
            encryption_key: Optional Fernet encryption key for encrypted storage.
                If not provided, encrypted storage operations will fail.
                The key should be a valid Fernet key (base64-encoded 32 bytes).
        """
        self._keys: dict[str, str] = {}
        self._encryption_key = encryption_key
        self._storage_path: Optional[Path] = None
        self._provider_status: dict[str, ProviderStatus] = {}
        self._fernet: Optional[Fernet] = None
        
        if encryption_key and CRYPTOGRAPHY_AVAILABLE:
            try:
                self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
            except Exception as e:
                logger.error(f"Invalid encryption key provided: {e}")
                self._fernet = None

    def load_from_env(self) -> None:
        """Load API keys from environment variables.
        
        Scans all known provider environment variables and loads any
        that are set with non-empty values.
        
        Expected environment variables:
        - OPENAI_API_KEY
        - ANTHROPIC_API_KEY
        - GOOGLE_AI_API_KEY
        - DEEPSEEK_API_KEY
        - XAI_API_KEY (Grok)
        - OPENROUTER_API_KEY
        - CEREBRAS_API_KEY (existing)
        - OLLAMA_HOST (not a key, but endpoint)
        
        For Ollama, if OLLAMA_HOST is not set, it defaults to
        http://localhost:11434.
        
        Property 13: Environment Variable Key Loading
        For any environment variable following the naming pattern
        {PROVIDER}_API_KEY with a non-empty value, load_from_env()
        SHALL make that key available via get_key(provider).
        """
        for provider, env_var in ENV_VAR_MAPPING.items():
            value = os.environ.get(env_var)
            
            if provider == "ollama":
                # Ollama uses a host URL instead of an API key
                # Default to localhost if not set
                if value:
                    self._keys[provider] = value
                else:
                    self._keys[provider] = DEFAULT_OLLAMA_HOST
                self._provider_status[provider] = ProviderStatus.OPERATIONAL
                logger.debug(f"Loaded Ollama host: {self._keys[provider]}")
            elif value:
                self._keys[provider] = value
                self._provider_status[provider] = ProviderStatus.OPERATIONAL
                logger.debug(f"Loaded API key for {provider} from environment")
            else:
                self._provider_status[provider] = ProviderStatus.NOT_CONFIGURED
                logger.debug(f"No API key found for {provider} in environment")

    def load_from_encrypted_file(self, path: Path) -> bool:
        """Load API keys from encrypted file storage.
        
        Reads an encrypted JSON file containing API keys for multiple
        providers. The file is decrypted using the Fernet key provided
        at initialization.
        
        Args:
            path: Path to the encrypted keys file.
            
        Returns:
            True if loaded successfully, False on decryption failure
            or if the file doesn't exist.
            
        Note:
            If decryption fails, all providers in the file are marked
            as NOT_CONFIGURED and an error is logged (Requirement 10.6).
            
        Property 14: Encrypted Storage Round-Trip
        For any API key stored via set_key() to encrypted storage,
        load_from_encrypted_file() followed by get_key() SHALL return
        the identical key value.
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            logger.error("cryptography library not available - cannot load encrypted file")
            return False
            
        if not self._fernet:
            logger.error("No encryption key configured - cannot load encrypted file")
            return False
            
        if not path.exists():
            logger.warning(f"Encrypted key file not found: {path}")
            return False
            
        self._storage_path = path
        
        try:
            encrypted_data = path.read_bytes()
            decrypted_data = self._fernet.decrypt(encrypted_data)
            keys_data = json.loads(decrypted_data.decode('utf-8'))
            
            if not isinstance(keys_data, dict):
                logger.error("Invalid encrypted key file format - expected JSON object")
                return False
            
            for provider, key in keys_data.items():
                if isinstance(key, str) and key:
                    self._keys[provider] = key
                    self._provider_status[provider] = ProviderStatus.OPERATIONAL
                    logger.debug(f"Loaded encrypted API key for {provider}")
                    
            logger.info(f"Successfully loaded {len(keys_data)} API keys from encrypted storage")
            return True
            
        except InvalidToken:
            logger.error(f"Failed to decrypt key file at {path} - invalid encryption key or corrupted file")
            # Mark all providers as NOT_CONFIGURED per Requirement 10.6
            for provider in ENV_VAR_MAPPING:
                if provider not in self._keys:
                    self._provider_status[provider] = ProviderStatus.NOT_CONFIGURED
            return False
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse decrypted key file: {e}")
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error loading encrypted key file: {e}")
            return False

    def save_to_encrypted_file(self, path: Optional[Path] = None) -> bool:
        """Save current API keys to encrypted file storage.
        
        Writes all stored API keys to an encrypted JSON file using
        Fernet symmetric encryption.
        
        Args:
            path: Path to save the encrypted file. If not provided,
                uses the path from the last load_from_encrypted_file call.
                
        Returns:
            True if saved successfully, False on failure.
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            logger.error("cryptography library not available - cannot save encrypted file")
            return False
            
        if not self._fernet:
            logger.error("No encryption key configured - cannot save encrypted file")
            return False
            
        save_path = path or self._storage_path
        if not save_path:
            logger.error("No storage path specified for saving encrypted keys")
            return False
            
        try:
            # Only save actual API keys, not Ollama host or empty values
            keys_to_save = {
                provider: key 
                for provider, key in self._keys.items()
                if key and provider != "ollama"  # Ollama uses host, not key
            }
            
            # Also save Ollama host if it's not the default
            if "ollama" in self._keys and self._keys["ollama"] != DEFAULT_OLLAMA_HOST:
                keys_to_save["ollama"] = self._keys["ollama"]
            
            json_data = json.dumps(keys_to_save, indent=2)
            encrypted_data = self._fernet.encrypt(json_data.encode('utf-8'))
            
            # Ensure parent directory exists
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(encrypted_data)
            
            self._storage_path = save_path
            logger.info(f"Successfully saved {len(keys_to_save)} API keys to encrypted storage")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save encrypted key file: {e}")
            return False

    def get_key(self, provider: str) -> Optional[str]:
        """Get API key for a provider (backend only).
        
        This method should only be called from backend code. API keys
        are never transmitted to the frontend (Requirement 10.4).
        
        Args:
            provider: Provider name (lowercase, e.g., 'openai', 'anthropic').
                Can also be a ProviderType enum value.
                
        Returns:
            The API key if configured, None otherwise.
            For Ollama, returns the host URL instead of an API key.
        """
        # Handle ProviderType enum
        if isinstance(provider, ProviderType):
            provider = provider.value
            
        provider = provider.lower()
        return self._keys.get(provider)

    def set_key(self, provider: str, key: str) -> bool:
        """Set/update an API key (persists to encrypted storage).
        
        Updates the API key for a provider in memory. If encrypted
        storage is configured, also persists the change to disk.
        
        This method should only be called from backend code after
        validating the key (Requirement 10.5).
        
        Args:
            provider: Provider name (lowercase).
            key: The API key value to store.
            
        Returns:
            True if the key was set (and persisted if storage is configured),
            False on persistence failure.
        """
        # Handle ProviderType enum
        if isinstance(provider, ProviderType):
            provider = provider.value
            
        provider = provider.lower()
        
        if not key:
            logger.warning(f"Attempted to set empty key for {provider}")
            return False
            
        self._keys[provider] = key
        self._provider_status[provider] = ProviderStatus.OPERATIONAL
        logger.debug(f"Set API key for {provider}")
        
        # Persist to encrypted storage if configured
        if self._storage_path and self._fernet:
            return self.save_to_encrypted_file()
            
        return True

    def remove_key(self, provider: str) -> bool:
        """Remove an API key for a provider.
        
        Removes the key from memory and, if encrypted storage is
        configured, persists the removal.
        
        Args:
            provider: Provider name (lowercase).
            
        Returns:
            True if the key was removed (and persisted if storage is configured),
            False if the key didn't exist or on persistence failure.
        """
        # Handle ProviderType enum
        if isinstance(provider, ProviderType):
            provider = provider.value
            
        provider = provider.lower()
        
        if provider not in self._keys:
            return False
            
        del self._keys[provider]
        self._provider_status[provider] = ProviderStatus.NOT_CONFIGURED
        logger.debug(f"Removed API key for {provider}")
        
        # Persist to encrypted storage if configured
        if self._storage_path and self._fernet:
            return self.save_to_encrypted_file()
            
        return True

    def is_configured(self, provider: str) -> bool:
        """Check if a provider has a configured key.
        
        Args:
            provider: Provider name (lowercase).
            
        Returns:
            True if the provider has a non-empty key configured.
        """
        # Handle ProviderType enum
        if isinstance(provider, ProviderType):
            provider = provider.value
            
        provider = provider.lower()
        key = self._keys.get(provider)
        return bool(key)

    def validate_key(self, provider: str, key: str) -> tuple[bool, Optional[str]]:
        """Validate an API key by making a test call.
        
        Attempts to validate the provided key by making a lightweight
        API call to the provider. This is used when users enter new
        keys through the Model Manager.
        
        Args:
            provider: Provider name (lowercase).
            key: The API key to validate.
            
        Returns:
            Tuple of (is_valid, error_message) where:
            - is_valid: True if the key is valid
            - error_message: None if valid, or a descriptive error message
            
        Note:
            This method makes network requests and may block. It should
            be called asynchronously in the Model Manager UI.
        """
        # Handle ProviderType enum
        if isinstance(provider, ProviderType):
            provider = provider.value
            
        provider = provider.lower()
        
        if not key:
            return False, "API key cannot be empty"
        
        # Basic format validation for known providers
        validation_result = self._validate_key_format(provider, key)
        if not validation_result[0]:
            return validation_result
        
        # Provider-specific validation with actual API calls
        try:
            return self._validate_key_with_api(provider, key)
        except Exception as e:
            logger.error(f"Error validating key for {provider}: {e}")
            return False, str(e)

    def _validate_key_format(self, provider: str, key: str) -> tuple[bool, Optional[str]]:
        """Validate API key format without making API calls.
        
        Args:
            provider: Provider name (lowercase).
            key: The API key to validate.
            
        Returns:
            Tuple of (is_valid, error_message).
        """
        # OpenAI keys start with sk-
        if provider == "openai":
            if not key.startswith("sk-"):
                return False, "OpenAI API keys should start with 'sk-'"
                
        # Anthropic keys start with sk-ant-
        elif provider == "anthropic":
            if not key.startswith("sk-ant-"):
                return False, "Anthropic API keys should start with 'sk-ant-'"
                
        # Ollama validation - should be a valid URL
        elif provider == "ollama":
            if not key.startswith(("http://", "https://")):
                return False, "Ollama host should be a valid URL (e.g., http://localhost:11434)"
                
        return True, None

    def _validate_key_with_api(self, provider: str, key: str) -> tuple[bool, Optional[str]]:
        """Validate API key by making a test API call.
        
        This method makes lightweight API calls to validate keys.
        Each provider has its own validation endpoint/method.
        
        Args:
            provider: Provider name (lowercase).
            key: The API key to validate.
            
        Returns:
            Tuple of (is_valid, error_message).
        """
        import requests
        
        try:
            if provider == "openai":
                # OpenAI: List models endpoint is lightweight
                response = requests.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10
                )
                if response.status_code == 200:
                    return True, None
                elif response.status_code == 401:
                    return False, "Invalid API key"
                else:
                    return False, f"API error: {response.status_code}"
                    
            elif provider == "anthropic":
                # Anthropic: Use a minimal message request
                response = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "claude-3-haiku-20240307",
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "Hi"}]
                    },
                    timeout=10
                )
                # A valid key should give 200 or at least not 401
                if response.status_code in (200, 201):
                    return True, None
                elif response.status_code == 401:
                    return False, "Invalid API key"
                else:
                    # Other errors might be rate limits, etc. - key is likely valid
                    return True, None
                    
            elif provider == "gemini":
                # Google AI: List models endpoint
                response = requests.get(
                    f"https://generativelanguage.googleapis.com/v1/models?key={key}",
                    timeout=10
                )
                if response.status_code == 200:
                    return True, None
                elif response.status_code == 400:
                    return False, "Invalid API key"
                else:
                    return False, f"API error: {response.status_code}"
                    
            elif provider == "ollama":
                # Ollama: Check if server is reachable
                response = requests.get(
                    f"{key}/api/version",
                    timeout=3
                )
                if response.status_code == 200:
                    return True, None
                else:
                    return False, "Ollama server not responding"
                    
            elif provider == "deepseek":
                # DeepSeek: Similar to OpenAI
                response = requests.get(
                    "https://api.deepseek.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10
                )
                if response.status_code == 200:
                    return True, None
                elif response.status_code == 401:
                    return False, "Invalid API key"
                else:
                    return False, f"API error: {response.status_code}"
                    
            elif provider == "grok":
                # xAI/Grok: Similar to OpenAI
                response = requests.get(
                    "https://api.x.ai/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10
                )
                if response.status_code == 200:
                    return True, None
                elif response.status_code == 401:
                    return False, "Invalid API key"
                else:
                    return False, f"API error: {response.status_code}"
                    
            elif provider == "openrouter":
                # OpenRouter: Similar to OpenAI
                response = requests.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10
                )
                if response.status_code == 200:
                    return True, None
                elif response.status_code == 401:
                    return False, "Invalid API key"
                else:
                    return False, f"API error: {response.status_code}"
                    
            elif provider == "cerebras":
                # Cerebras: Similar to OpenAI
                response = requests.get(
                    "https://api.cerebras.ai/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10
                )
                if response.status_code == 200:
                    return True, None
                elif response.status_code == 401:
                    return False, "Invalid API key"
                else:
                    return False, f"API error: {response.status_code}"
                    
            else:
                # Unknown provider - just check key is not empty
                return True, None
                
        except requests.exceptions.Timeout:
            if provider == "ollama":
                return False, "Ollama server connection timed out"
            return False, "API request timed out"
        except requests.exceptions.ConnectionError:
            if provider == "ollama":
                return False, "Could not connect to Ollama server"
            return False, "Could not connect to API"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    def get_provider_status(self, provider: str) -> ProviderStatus:
        """Get the configuration status of a provider.
        
        Args:
            provider: Provider name (lowercase).
            
        Returns:
            ProviderStatus indicating whether the provider is configured.
        """
        # Handle ProviderType enum
        if isinstance(provider, ProviderType):
            provider = provider.value
            
        provider = provider.lower()
        return self._provider_status.get(provider, ProviderStatus.NOT_CONFIGURED)

    def get_all_provider_status(self) -> dict[str, ProviderStatus]:
        """Get configuration status for all known providers.
        
        Returns:
            Dictionary mapping provider names to their ProviderStatus.
        """
        result = {}
        for provider in ENV_VAR_MAPPING:
            result[provider] = self.get_provider_status(provider)
        return result

    def get_configured_providers(self) -> list[str]:
        """Get list of providers that have configured keys.
        
        Returns:
            List of provider names that are configured.
        """
        return [
            provider 
            for provider in ENV_VAR_MAPPING 
            if self.is_configured(provider)
        ]

    @staticmethod
    def generate_encryption_key() -> str:
        """Generate a new Fernet encryption key.
        
        Returns:
            A base64-encoded Fernet key suitable for use with this class.
            
        Example:
            key = API_Key_Store.generate_encryption_key()
            store = API_Key_Store(encryption_key=key)
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            raise RuntimeError("cryptography library not available")
        return Fernet.generate_key().decode('utf-8')
