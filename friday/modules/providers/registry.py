"""Provider Registry for managing all provider adapters.

This module implements the Provider_Registry singleton class that maintains
the list of registered providers, tracks their configuration and health status,
and provides the active provider for requests.

The registry validates that adapters implement all required interface methods
upon registration (Property 3: Interface Validation on Registration).

Requirements: 1.3, 1.4, 7.2
"""

from __future__ import annotations

import inspect
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from friday.modules.providers.base import Provider_Adapter
from friday.modules.providers.models import (
    ProviderHealth,
    ProviderMetrics,
    ProviderStatus,
    get_status_color,
)

if TYPE_CHECKING:
    pass


# Required interface methods that all Provider_Adapters must implement
# Property 3: Interface Validation on Registration
REQUIRED_INTERFACE_METHODS = [
    "generate",
    "stream_generate",
    "translate_tools",
    "parse_tool_calls",
    "get_available_models",
    "get_health",
    "is_configured",
    "validate_config",
]

# Required interface properties that all Provider_Adapters must have
REQUIRED_INTERFACE_PROPERTIES = [
    "provider_name",
    "capabilities",
]


class Provider_Registry:
    """Registry and manager for all provider adapters.
    
    Maintains the list of registered providers, tracks their configuration
    and health status, and provides the active provider for requests.
    
    This class implements the Singleton pattern to ensure consistent state
    across the application. Use get_instance() to obtain the registry instance.
    
    Attributes:
        _adapters: Dictionary mapping provider names to their adapters
        _active_provider: Name of the currently active provider
        _active_model: Name of the currently active model
        _metrics: Dictionary mapping provider names to their metrics
    
    Example:
        registry = Provider_Registry.get_instance()
        registry.register(OpenAI_Adapter(api_key_store))
        registry.set_active("openai", "gpt-4o")
        adapter = registry.get_active_adapter()
        response = adapter.generate(messages)
    
    Requirements: 1.3, 1.4, 7.2
    """

    _instance: Optional["Provider_Registry"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the Provider_Registry.
        
        Note: Use get_instance() instead of direct instantiation to ensure
        singleton behavior.
        """
        self._adapters: dict[str, Provider_Adapter] = {}
        self._active_provider: Optional[str] = None
        self._active_model: Optional[str] = None
        self._metrics: dict[str, ProviderMetrics] = {}

    @classmethod
    def get_instance(cls) -> "Provider_Registry":
        """Get the singleton instance of Provider_Registry.
        
        This method is thread-safe and will create the instance on first call.
        
        Returns:
            The singleton Provider_Registry instance.
        
        Example:
            registry = Provider_Registry.get_instance()
        """
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. Primarily for testing purposes.
        
        This method clears the singleton instance, allowing a fresh registry
        to be created on the next get_instance() call.
        """
        with cls._lock:
            cls._instance = None

    def _validate_adapter_interface(self, adapter: Provider_Adapter) -> tuple[bool, Optional[str]]:
        """Validate that an adapter implements all required interface methods.
        
        Property 3: Interface Validation on Registration
        For any Provider_Adapter implementation, registration in Provider_Registry
        SHALL succeed if and only if all required interface methods are implemented.
        
        Args:
            adapter: The adapter to validate
            
        Returns:
            Tuple of (is_valid, error_message) where:
            - is_valid: True if all required methods/properties are implemented
            - error_message: None if valid, or describes what's missing
        """
        missing_methods = []
        missing_properties = []
        
        # Check required methods
        for method_name in REQUIRED_INTERFACE_METHODS:
            if not hasattr(adapter, method_name):
                missing_methods.append(method_name)
                continue
            
            method = getattr(adapter, method_name)
            if not callable(method):
                missing_methods.append(method_name)
                continue
            
            # Check if method is abstract (not implemented)
            # A method that raises NotImplementedError is considered not implemented
            # We check if it's still an abstract method by looking at the __isabstractmethod__ attribute
            if getattr(method, "__isabstractmethod__", False):
                missing_methods.append(method_name)
        
        # Check required properties
        for prop_name in REQUIRED_INTERFACE_PROPERTIES:
            if not hasattr(adapter, prop_name):
                missing_properties.append(prop_name)
                continue
            
            # Try to access the property to ensure it's properly implemented
            try:
                getattr(adapter, prop_name)
            except (NotImplementedError, AttributeError):
                missing_properties.append(prop_name)
        
        if missing_methods or missing_properties:
            error_parts = []
            if missing_methods:
                error_parts.append(f"missing methods: {', '.join(missing_methods)}")
            if missing_properties:
                error_parts.append(f"missing properties: {', '.join(missing_properties)}")
            return False, f"Adapter validation failed - {'; '.join(error_parts)}"
        
        return True, None

    def register(self, adapter: Provider_Adapter) -> Optional[str]:
        """Register a provider adapter with validation.
        
        Property 2: Provider Registration Tracking
        For any valid Provider_Adapter registration, the Provider_Registry SHALL
        contain that adapter with its correct configuration and ProviderStatus
        accessible via get_adapter().
        
        Property 3: Interface Validation on Registration
        For any Provider_Adapter implementation, registration in Provider_Registry
        SHALL succeed if and only if all required interface methods are implemented.
        
        Args:
            adapter: The Provider_Adapter instance to register
            
        Returns:
            None on success, or an error message string if validation fails.
        
        Example:
            error = registry.register(OpenAI_Adapter(key_store))
            if error:
                print(f"Registration failed: {error}")
        
        Requirements: 1.3, 1.4
        """
        # Validate the adapter implements all required interface methods
        is_valid, error_message = self._validate_adapter_interface(adapter)
        if not is_valid:
            return error_message
        
        # Get the provider name
        try:
            provider_name = adapter.provider_name
        except (NotImplementedError, AttributeError) as e:
            return f"Failed to get provider_name: {e}"
        
        if not provider_name or not isinstance(provider_name, str):
            return "provider_name must be a non-empty string"
        
        # Register the adapter
        self._adapters[provider_name] = adapter
        
        # Initialize metrics for this provider if not already present
        if provider_name not in self._metrics:
            self._metrics[provider_name] = ProviderMetrics()
        
        # If this is the first adapter and no active provider is set, make it active
        if self._active_provider is None:
            self._active_provider = provider_name
            # Try to set a default model from the adapter's capabilities
            try:
                capabilities = adapter.capabilities
                if capabilities.supported_models:
                    self._active_model = capabilities.supported_models[0]
            except (NotImplementedError, AttributeError):
                pass
        
        return None  # Success

    def unregister(self, provider_name: str) -> bool:
        """Unregister a provider adapter.
        
        Args:
            provider_name: The name of the provider to unregister
            
        Returns:
            True if the provider was unregistered, False if it wasn't registered.
        """
        if provider_name not in self._adapters:
            return False
        
        del self._adapters[provider_name]
        
        # Clear metrics for this provider
        if provider_name in self._metrics:
            del self._metrics[provider_name]
        
        # If the unregistered provider was active, clear active state or set to another
        if self._active_provider == provider_name:
            if self._adapters:
                # Set to the first available adapter
                self._active_provider = next(iter(self._adapters))
                try:
                    adapter = self._adapters[self._active_provider]
                    capabilities = adapter.capabilities
                    if capabilities.supported_models:
                        self._active_model = capabilities.supported_models[0]
                    else:
                        self._active_model = None
                except (NotImplementedError, AttributeError):
                    self._active_model = None
            else:
                self._active_provider = None
                self._active_model = None
        
        return True

    def get_adapter(self, provider_name: str) -> Optional[Provider_Adapter]:
        """Get a specific provider adapter by name.
        
        Property 2: Provider Registration Tracking
        For any valid Provider_Adapter registration, the Provider_Registry SHALL
        contain that adapter with its correct configuration and ProviderStatus
        accessible via get_adapter().
        
        Args:
            provider_name: The name of the provider to retrieve
            
        Returns:
            The Provider_Adapter instance, or None if not found.
        
        Example:
            openai = registry.get_adapter("openai")
            if openai:
                response = openai.generate(messages)
        
        Requirements: 1.3
        """
        return self._adapters.get(provider_name)

    def get_active_adapter(self) -> Optional[Provider_Adapter]:
        """Get the currently active provider adapter.
        
        Returns:
            The currently active Provider_Adapter, or None if no provider is active.
        
        Example:
            adapter = registry.get_active_adapter()
            if adapter:
                response = adapter.generate(messages)
        """
        if self._active_provider is None:
            return None
        return self._adapters.get(self._active_provider)

    def get_active_provider_name(self) -> Optional[str]:
        """Get the name of the currently active provider.
        
        Returns:
            The name of the active provider, or None if no provider is active.
        """
        return self._active_provider

    def get_active_model(self) -> Optional[str]:
        """Get the name of the currently active model.
        
        Returns:
            The name of the active model, or None if no model is active.
        """
        return self._active_model

    def set_active(self, provider_name: str, model: Optional[str] = None) -> bool:
        """Set the active provider and optionally the model.
        
        Args:
            provider_name: The name of the provider to make active
            model: Optional model name to use. If None and the provider
                has supported_models, the first one will be used.
            
        Returns:
            True if the active provider was set successfully, False if the
            provider is not registered.
        
        Example:
            success = registry.set_active("openai", "gpt-4o")
            if success:
                print("Switched to OpenAI GPT-4o")
        
        Requirements: 7.2
        """
        if provider_name not in self._adapters:
            return False
        
        self._active_provider = provider_name
        
        if model is not None:
            self._active_model = model
        else:
            # Try to set a default model from the adapter's capabilities
            try:
                adapter = self._adapters[provider_name]
                capabilities = adapter.capabilities
                if capabilities.supported_models:
                    self._active_model = capabilities.supported_models[0]
                else:
                    self._active_model = None
            except (NotImplementedError, AttributeError):
                self._active_model = None
        
        return True

    def get_all_providers(self) -> list[dict[str, Any]]:
        """Get status of all registered providers for Model Manager.
        
        Returns a list of provider information including their configuration
        status, health metrics, available models, and capabilities.
        
        Returns:
            List of dictionaries with provider information. Each dict contains:
            - name: Provider identifier
            - is_configured: Whether the provider has valid configuration
            - status: Current ProviderStatus value
            - status_color: Color for UI display
            - is_active: Whether this is the active provider
            - models: List of available models
            - capabilities: Provider capabilities
            - metrics: Current health metrics
        
        Example:
            providers = registry.get_all_providers()
            for p in providers:
                print(f"{p['name']}: {p['status']}")
        
        Requirements: 7.1
        """
        providers = []
        
        for name, adapter in self._adapters.items():
            provider_info: dict[str, Any] = {
                "name": name,
                "is_active": name == self._active_provider,
            }
            
            # Get configuration status
            try:
                provider_info["is_configured"] = adapter.is_configured()
            except (NotImplementedError, AttributeError):
                provider_info["is_configured"] = False
            
            # Get health status
            try:
                health = adapter.get_health()
                provider_info["status"] = health.status.value
                provider_info["status_color"] = get_status_color(health.status)
                provider_info["latency_ms"] = health.latency_ms
                provider_info["success_rate"] = health.success_rate
                provider_info["error_rate"] = health.error_rate
                provider_info["last_error"] = health.last_error
            except (NotImplementedError, AttributeError):
                # If health check fails, derive status from configuration
                if provider_info.get("is_configured", False):
                    status = ProviderStatus.OPERATIONAL
                else:
                    status = ProviderStatus.NOT_CONFIGURED
                provider_info["status"] = status.value
                provider_info["status_color"] = get_status_color(status)
                provider_info["latency_ms"] = 0.0
                provider_info["success_rate"] = 1.0
                provider_info["error_rate"] = 0.0
                provider_info["last_error"] = None
            
            # Get available models
            try:
                provider_info["models"] = adapter.get_available_models()
            except (NotImplementedError, AttributeError):
                provider_info["models"] = []
            
            # Get capabilities
            try:
                capabilities = adapter.capabilities
                provider_info["capabilities"] = {
                    "supports_streaming": capabilities.supports_streaming,
                    "supports_tool_calling": capabilities.supports_tool_calling,
                    "supports_vision": capabilities.supports_vision,
                    "max_context_window": capabilities.max_context_window,
                    "supported_models": capabilities.supported_models,
                }
            except (NotImplementedError, AttributeError):
                provider_info["capabilities"] = {}
            
            # Add internal metrics
            if name in self._metrics:
                metrics = self._metrics[name]
                provider_info["metrics"] = {
                    "total_requests": metrics.total_requests,
                    "successful_requests": metrics.successful_requests,
                    "failed_requests": metrics.failed_requests,
                    "average_latency_ms": metrics.average_latency_ms,
                    "success_rate": metrics.success_rate,
                    "error_rate": metrics.error_rate,
                    "consecutive_failures": metrics.consecutive_failures,
                }
            else:
                provider_info["metrics"] = {}
            
            providers.append(provider_info)
        
        return providers

    def has_provider(self, provider_name: str) -> bool:
        """Check if a provider is registered.
        
        Args:
            provider_name: The name of the provider to check
            
        Returns:
            True if the provider is registered, False otherwise.
        """
        return provider_name in self._adapters

    def get_provider_count(self) -> int:
        """Get the number of registered providers.
        
        Returns:
            The number of registered provider adapters.
        """
        return len(self._adapters)

    def get_all_provider_names(self) -> list[str]:
        """Get the names of all registered providers.
        
        Returns:
            List of registered provider names.
        """
        return list(self._adapters.keys())

    def record_request(
        self,
        provider: str,
        success: bool,
        latency_ms: float,
        error: Optional[str] = None,
    ) -> None:
        """Record request metrics for health monitoring.
        
        Updates the provider's metrics and determines status based on thresholds:
        - Property 23: Success and error rates are calculated from successful/total and failed/total
        - Property 24: When error rate exceeds 50% over 10 requests → DEGRADED
        - Property 25: When 5 consecutive failures occur → UNAVAILABLE
        
        Args:
            provider: The name of the provider
            success: Whether the request was successful
            latency_ms: Response latency in milliseconds
            error: Optional error message if the request failed
        
        Requirements: 16.1, 16.2, 16.4, 16.5
        """
        if provider not in self._metrics:
            self._metrics[provider] = ProviderMetrics()
        
        metrics = self._metrics[provider]
        
        # Update request counts
        metrics.total_requests += 1
        
        if success:
            metrics.successful_requests += 1
            metrics.total_latency_ms += latency_ms
            # Reset consecutive failures on success
            metrics.consecutive_failures = 0
        else:
            metrics.failed_requests += 1
            metrics.consecutive_failures += 1
            if error:
                metrics.last_error = error
                metrics.last_error_time = datetime.now()

    def _calculate_provider_status(self, provider: str) -> ProviderStatus:
        """Calculate the current status of a provider based on its metrics.
        
        Status determination rules (checked in order of priority):
        1. If not configured → NOT_CONFIGURED
        2. If 5 or more consecutive failures → UNAVAILABLE (Property 25)
        3. If error rate > 50% over at least 10 requests → DEGRADED (Property 24)
        4. Otherwise → OPERATIONAL
        
        Args:
            provider: The name of the provider
            
        Returns:
            The calculated ProviderStatus
        """
        # Check if provider is configured
        adapter = self._adapters.get(provider)
        if adapter is None:
            return ProviderStatus.NOT_CONFIGURED
        
        try:
            if not adapter.is_configured():
                return ProviderStatus.NOT_CONFIGURED
        except (NotImplementedError, AttributeError):
            pass
        
        # Get metrics for this provider
        metrics = self._metrics.get(provider)
        if metrics is None:
            return ProviderStatus.OPERATIONAL
        
        # Property 25: 5 consecutive failures → UNAVAILABLE
        if metrics.consecutive_failures >= 5:
            return ProviderStatus.UNAVAILABLE
        
        # Property 24: >50% error rate over at least 10 requests → DEGRADED
        if metrics.total_requests >= 10 and metrics.error_rate > 0.5:
            return ProviderStatus.DEGRADED
        
        return ProviderStatus.OPERATIONAL

    def get_health_metrics(self) -> dict[str, ProviderHealth]:
        """Get health metrics for all providers.
        
        Returns a dictionary mapping provider names to their ProviderHealth objects,
        containing status, latency, success rate, error rate, and last error.
        
        Property 23: Success and error rates match successful/total and failed/total
        
        Returns:
            Dictionary mapping provider names to ProviderHealth objects
        
        Requirements: 16.1, 16.2, 16.3
        """
        health_metrics: dict[str, ProviderHealth] = {}
        
        for provider_name in self._adapters:
            metrics = self._metrics.get(provider_name, ProviderMetrics())
            status = self._calculate_provider_status(provider_name)
            
            health_metrics[provider_name] = ProviderHealth(
                status=status,
                latency_ms=metrics.average_latency_ms,
                success_rate=metrics.success_rate,
                error_rate=metrics.error_rate,
                last_error=metrics.last_error,
                last_checked=metrics.last_error_time.isoformat() if metrics.last_error_time else None,
            )
        
        return health_metrics

    def get_degraded_providers(self) -> list[str]:
        """Get list of providers with degraded status.
        
        A provider is DEGRADED when its error rate exceeds 50% over at least
        10 requests (Property 24).
        
        Returns:
            List of provider names with DEGRADED status
        
        Requirements: 16.4
        """
        degraded = []
        for provider_name in self._adapters:
            status = self._calculate_provider_status(provider_name)
            if status == ProviderStatus.DEGRADED:
                degraded.append(provider_name)
        return degraded

    def get_unavailable_providers(self) -> list[str]:
        """Get list of unavailable providers.
        
        A provider is UNAVAILABLE when it has 5 or more consecutive failures
        (Property 25).
        
        Returns:
            List of provider names with UNAVAILABLE status
        
        Requirements: 16.5
        """
        unavailable = []
        for provider_name in self._adapters:
            status = self._calculate_provider_status(provider_name)
            if status == ProviderStatus.UNAVAILABLE:
                unavailable.append(provider_name)
        return unavailable
