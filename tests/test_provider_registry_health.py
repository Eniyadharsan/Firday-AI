"""Tests for Provider_Registry health metrics tracking.

This module tests the health metrics tracking functionality in Provider_Registry,
including record_request(), get_health_metrics(), get_degraded_providers(), and
get_unavailable_providers().

Requirements: 16.1, 16.2, 16.4, 16.5
Properties: 23, 24, 25
"""

from __future__ import annotations

from typing import Any, Generator, Optional
from unittest.mock import MagicMock

import pytest

from friday.modules.providers.base import Provider_Adapter
from friday.modules.providers.models import (
    GenerateResponse,
    ProviderCapabilities,
    ProviderHealth,
    ProviderStatus,
)
from friday.modules.providers.registry import Provider_Registry


class MockAdapter(Provider_Adapter):
    """A minimal mock adapter for testing registry functionality."""
    
    def __init__(self, name: str = "mock_provider", configured: bool = True):
        self._name = name
        self._configured = configured
        self._capabilities = ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=True,
            supports_vision=False,
            max_context_window=8192,
            supported_models=["mock-model-1", "mock-model-2"],
        )
    
    @property
    def provider_name(self) -> str:
        return self._name
    
    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities
    
    def is_configured(self) -> bool:
        return self._configured
    
    def validate_config(self) -> tuple[bool, Optional[str]]:
        if self._configured:
            return True, None
        return False, "Not configured"
    
    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        return GenerateResponse(
            content="Mock response",
            model=model or "mock-model-1",
            provider=self._name,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )
    
    def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        yield "Mock "
        yield "stream "
        yield "response"
    
    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        return friday_tools
    
    def parse_tool_calls(self, response: Any) -> list[dict]:
        return []
    
    def get_available_models(self) -> list[dict[str, Any]]:
        return [
            {"id": "mock-model-1", "name": "Mock Model 1", "context_window": 8192},
            {"id": "mock-model-2", "name": "Mock Model 2", "context_window": 16384},
        ]
    
    def get_health(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderStatus.OPERATIONAL,
            latency_ms=100.0,
            success_rate=1.0,
            error_rate=0.0,
        )


class TestRecordRequest:
    """Tests for record_request() method.
    
    Requirements: 16.1, 16.2
    Property 23: Success and Error Rate Calculation
    """
    
    def setup_method(self):
        """Reset the registry before each test."""
        Provider_Registry.reset_instance()
        self.registry = Provider_Registry.get_instance()
        self.adapter = MockAdapter("test_provider")
        self.registry.register(self.adapter)
    
    def teardown_method(self):
        """Clean up after each test."""
        Provider_Registry.reset_instance()
    
    def test_record_successful_request_increments_total(self):
        """Recording a successful request should increment total_requests."""
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        
        metrics = self.registry._metrics["test_provider"]
        assert metrics.total_requests == 1
    
    def test_record_successful_request_increments_successful(self):
        """Recording a successful request should increment successful_requests."""
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        
        metrics = self.registry._metrics["test_provider"]
        assert metrics.successful_requests == 1
        assert metrics.failed_requests == 0
    
    def test_record_failed_request_increments_failed(self):
        """Recording a failed request should increment failed_requests."""
        self.registry.record_request("test_provider", success=False, latency_ms=0.0, error="API Error")
        
        metrics = self.registry._metrics["test_provider"]
        assert metrics.failed_requests == 1
        assert metrics.successful_requests == 0
    
    def test_record_request_tracks_latency(self):
        """Recording successful requests should accumulate latency."""
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        self.registry.record_request("test_provider", success=True, latency_ms=200.0)
        
        metrics = self.registry._metrics["test_provider"]
        assert metrics.total_latency_ms == 300.0
        assert metrics.average_latency_ms == 150.0
    
    def test_record_request_tracks_last_error(self):
        """Recording a failed request should store the error message."""
        self.registry.record_request("test_provider", success=False, latency_ms=0.0, error="Connection timeout")
        
        metrics = self.registry._metrics["test_provider"]
        assert metrics.last_error == "Connection timeout"
        assert metrics.last_error_time is not None
    
    def test_record_request_resets_consecutive_failures_on_success(self):
        """A successful request should reset consecutive_failures to 0."""
        # Record some failures
        for _ in range(3):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        metrics = self.registry._metrics["test_provider"]
        assert metrics.consecutive_failures == 3
        
        # Record a success
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        
        assert metrics.consecutive_failures == 0
    
    def test_record_request_increments_consecutive_failures(self):
        """Failed requests should increment consecutive_failures."""
        for i in range(1, 4):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
            metrics = self.registry._metrics["test_provider"]
            assert metrics.consecutive_failures == i
    
    def test_record_request_creates_metrics_for_new_provider(self):
        """Recording for an unregistered provider should create metrics."""
        self.registry.record_request("new_provider", success=True, latency_ms=50.0)
        
        assert "new_provider" in self.registry._metrics
        metrics = self.registry._metrics["new_provider"]
        assert metrics.total_requests == 1


class TestSuccessErrorRateCalculation:
    """Tests for Property 23: Success and Error Rate Calculation.
    
    success_rate and error_rate should match successful/total and failed/total.
    """
    
    def setup_method(self):
        """Reset the registry before each test."""
        Provider_Registry.reset_instance()
        self.registry = Provider_Registry.get_instance()
        self.adapter = MockAdapter("test_provider")
        self.registry.register(self.adapter)
    
    def teardown_method(self):
        """Clean up after each test."""
        Provider_Registry.reset_instance()
    
    def test_success_rate_calculation(self):
        """Success rate should equal successful_requests / total_requests."""
        # 3 successes, 2 failures = 60% success rate
        for _ in range(3):
            self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        for _ in range(2):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        metrics = self.registry._metrics["test_provider"]
        assert metrics.success_rate == pytest.approx(0.6)
    
    def test_error_rate_calculation(self):
        """Error rate should equal failed_requests / total_requests."""
        # 3 successes, 2 failures = 40% error rate
        for _ in range(3):
            self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        for _ in range(2):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        metrics = self.registry._metrics["test_provider"]
        assert metrics.error_rate == pytest.approx(0.4)
    
    def test_success_rate_default_when_no_requests(self):
        """Success rate should be 1.0 when no requests have been made."""
        metrics = self.registry._metrics["test_provider"]
        assert metrics.success_rate == 1.0
    
    def test_error_rate_default_when_no_requests(self):
        """Error rate should be 0.0 when no requests have been made."""
        metrics = self.registry._metrics["test_provider"]
        assert metrics.error_rate == 0.0
    
    def test_success_plus_error_rate_equals_one(self):
        """Success rate + error rate should always equal 1.0."""
        for _ in range(7):
            self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        for _ in range(3):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        metrics = self.registry._metrics["test_provider"]
        assert metrics.success_rate + metrics.error_rate == pytest.approx(1.0)


class TestDegradedStatusThreshold:
    """Tests for Property 24: Degraded Status Threshold.
    
    Provider with >50% error rate over 10 requests → DEGRADED.
    """
    
    def setup_method(self):
        """Reset the registry before each test."""
        Provider_Registry.reset_instance()
        self.registry = Provider_Registry.get_instance()
        self.adapter = MockAdapter("test_provider")
        self.registry.register(self.adapter)
    
    def teardown_method(self):
        """Clean up after each test."""
        Provider_Registry.reset_instance()
    
    def test_not_degraded_with_fewer_than_10_requests(self):
        """Provider should not be DEGRADED with fewer than 10 requests even with high error rate."""
        # 1 success, 8 failures = 88% error rate, but only 9 requests
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        for _ in range(8):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        degraded = self.registry.get_degraded_providers()
        assert "test_provider" not in degraded
    
    def test_degraded_with_more_than_50_percent_error_rate_over_10_requests(self):
        """Provider should be DEGRADED when error rate >50% over at least 10 requests."""
        # Interleave to avoid 5 consecutive failures (which would trigger UNAVAILABLE)
        # Pattern: F F S F F S F F S F = 3 successes, 7 failures = 70% error rate
        # With no more than 2 consecutive failures at any point
        for _ in range(10):
            # 2 failures followed by 1 success (repeat pattern)
            pass
        
        # Simpler approach: fail, fail, succeed pattern to avoid consecutive failure threshold
        # We need >50% error rate over 10 requests without hitting 5 consecutive failures
        # 3 successes, 7 failures interspersed:
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)  # Reset consecutive
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)  # Reset consecutive
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)  # Reset consecutive
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        # Total: 3 success, 7 failures = 70% error rate, max 2 consecutive failures
        
        degraded = self.registry.get_degraded_providers()
        assert "test_provider" in degraded
    
    def test_not_degraded_at_exactly_50_percent_error_rate(self):
        """Provider should NOT be DEGRADED at exactly 50% error rate (must be >50%)."""
        # 5 successes, 5 failures = exactly 50% error rate
        for _ in range(5):
            self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        for _ in range(5):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        degraded = self.registry.get_degraded_providers()
        assert "test_provider" not in degraded
    
    def test_not_degraded_with_low_error_rate(self):
        """Provider should not be DEGRADED with low error rate."""
        # 9 successes, 1 failure = 10% error rate
        for _ in range(9):
            self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        degraded = self.registry.get_degraded_providers()
        assert "test_provider" not in degraded


class TestUnavailableStatusThreshold:
    """Tests for Property 25: Unavailable Status Threshold.
    
    Provider with 5 consecutive failures → UNAVAILABLE.
    """
    
    def setup_method(self):
        """Reset the registry before each test."""
        Provider_Registry.reset_instance()
        self.registry = Provider_Registry.get_instance()
        self.adapter = MockAdapter("test_provider")
        self.registry.register(self.adapter)
    
    def teardown_method(self):
        """Clean up after each test."""
        Provider_Registry.reset_instance()
    
    def test_unavailable_after_5_consecutive_failures(self):
        """Provider should be UNAVAILABLE after 5 consecutive failures."""
        for _ in range(5):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        unavailable = self.registry.get_unavailable_providers()
        assert "test_provider" in unavailable
    
    def test_not_unavailable_with_4_consecutive_failures(self):
        """Provider should not be UNAVAILABLE with only 4 consecutive failures."""
        for _ in range(4):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        unavailable = self.registry.get_unavailable_providers()
        assert "test_provider" not in unavailable
    
    def test_success_resets_unavailable_countdown(self):
        """A success should reset consecutive failures, preventing UNAVAILABLE."""
        # 4 failures, 1 success, 4 more failures = should NOT be unavailable
        for _ in range(4):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        for _ in range(4):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        unavailable = self.registry.get_unavailable_providers()
        assert "test_provider" not in unavailable
    
    def test_unavailable_takes_priority_over_degraded(self):
        """UNAVAILABLE status should take priority over DEGRADED."""
        # This creates both conditions: >50% error over 10 requests AND 5 consecutive failures
        for _ in range(3):
            self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        for _ in range(7):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        # Should be in unavailable but not degraded (UNAVAILABLE takes priority)
        unavailable = self.registry.get_unavailable_providers()
        degraded = self.registry.get_degraded_providers()
        
        assert "test_provider" in unavailable
        assert "test_provider" not in degraded


class TestGetHealthMetrics:
    """Tests for get_health_metrics() method.
    
    Requirements: 16.1, 16.2, 16.3
    """
    
    def setup_method(self):
        """Reset the registry before each test."""
        Provider_Registry.reset_instance()
        self.registry = Provider_Registry.get_instance()
    
    def teardown_method(self):
        """Clean up after each test."""
        Provider_Registry.reset_instance()
    
    def test_returns_health_for_all_providers(self):
        """get_health_metrics should return health for all registered providers."""
        adapter1 = MockAdapter("provider1")
        adapter2 = MockAdapter("provider2")
        self.registry.register(adapter1)
        self.registry.register(adapter2)
        
        health = self.registry.get_health_metrics()
        
        assert "provider1" in health
        assert "provider2" in health
    
    def test_returns_provider_health_objects(self):
        """get_health_metrics should return ProviderHealth objects."""
        adapter = MockAdapter("test_provider")
        self.registry.register(adapter)
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        
        health = self.registry.get_health_metrics()
        
        assert isinstance(health["test_provider"], ProviderHealth)
    
    def test_health_contains_correct_status(self):
        """Health metrics should contain correct status based on thresholds."""
        adapter = MockAdapter("test_provider")
        self.registry.register(adapter)
        
        # Make provider UNAVAILABLE
        for _ in range(5):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        health = self.registry.get_health_metrics()
        
        assert health["test_provider"].status == ProviderStatus.UNAVAILABLE
    
    def test_health_contains_latency(self):
        """Health metrics should contain average latency."""
        adapter = MockAdapter("test_provider")
        self.registry.register(adapter)
        self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        self.registry.record_request("test_provider", success=True, latency_ms=200.0)
        
        health = self.registry.get_health_metrics()
        
        assert health["test_provider"].latency_ms == pytest.approx(150.0)
    
    def test_health_contains_success_rate(self):
        """Health metrics should contain success rate."""
        adapter = MockAdapter("test_provider")
        self.registry.register(adapter)
        for _ in range(3):
            self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        health = self.registry.get_health_metrics()
        
        assert health["test_provider"].success_rate == pytest.approx(0.75)
    
    def test_health_contains_error_rate(self):
        """Health metrics should contain error rate."""
        adapter = MockAdapter("test_provider")
        self.registry.register(adapter)
        for _ in range(3):
            self.registry.record_request("test_provider", success=True, latency_ms=100.0)
        self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        health = self.registry.get_health_metrics()
        
        assert health["test_provider"].error_rate == pytest.approx(0.25)
    
    def test_health_contains_last_error(self):
        """Health metrics should contain last error message."""
        adapter = MockAdapter("test_provider")
        self.registry.register(adapter)
        self.registry.record_request("test_provider", success=False, latency_ms=0.0, error="Test error")
        
        health = self.registry.get_health_metrics()
        
        assert health["test_provider"].last_error == "Test error"


class TestNotConfiguredStatus:
    """Tests for NOT_CONFIGURED status handling."""
    
    def setup_method(self):
        """Reset the registry before each test."""
        Provider_Registry.reset_instance()
        self.registry = Provider_Registry.get_instance()
    
    def teardown_method(self):
        """Clean up after each test."""
        Provider_Registry.reset_instance()
    
    def test_unconfigured_provider_has_not_configured_status(self):
        """An unconfigured provider should have NOT_CONFIGURED status."""
        adapter = MockAdapter("test_provider", configured=False)
        self.registry.register(adapter)
        
        health = self.registry.get_health_metrics()
        
        assert health["test_provider"].status == ProviderStatus.NOT_CONFIGURED
    
    def test_not_configured_takes_priority_over_metrics_status(self):
        """NOT_CONFIGURED should take priority regardless of metrics."""
        adapter = MockAdapter("test_provider", configured=False)
        self.registry.register(adapter)
        
        # Even with failures, status should be NOT_CONFIGURED
        for _ in range(5):
            self.registry.record_request("test_provider", success=False, latency_ms=0.0)
        
        health = self.registry.get_health_metrics()
        
        assert health["test_provider"].status == ProviderStatus.NOT_CONFIGURED


class TestMultipleProviders:
    """Tests for health metrics with multiple providers."""
    
    def setup_method(self):
        """Reset the registry before each test."""
        Provider_Registry.reset_instance()
        self.registry = Provider_Registry.get_instance()
    
    def teardown_method(self):
        """Clean up after each test."""
        Provider_Registry.reset_instance()
    
    def test_different_providers_have_independent_metrics(self):
        """Each provider should track metrics independently."""
        adapter1 = MockAdapter("provider1")
        adapter2 = MockAdapter("provider2")
        self.registry.register(adapter1)
        self.registry.register(adapter2)
        
        # Provider1: 1 success
        self.registry.record_request("provider1", success=True, latency_ms=100.0)
        
        # Provider2: 1 failure
        self.registry.record_request("provider2", success=False, latency_ms=0.0)
        
        assert self.registry._metrics["provider1"].successful_requests == 1
        assert self.registry._metrics["provider1"].failed_requests == 0
        assert self.registry._metrics["provider2"].successful_requests == 0
        assert self.registry._metrics["provider2"].failed_requests == 1
    
    def test_get_degraded_returns_only_degraded_providers(self):
        """get_degraded_providers should only return providers with DEGRADED status."""
        adapter1 = MockAdapter("healthy")
        adapter2 = MockAdapter("degraded")
        self.registry.register(adapter1)
        self.registry.register(adapter2)
        
        # Make adapter2 degraded (>50% error over 10 requests, but avoid 5 consecutive failures)
        # Pattern: F F S F F S F F S F = 3 successes, 7 failures = 70% error rate
        self.registry.record_request("degraded", success=False, latency_ms=0.0)
        self.registry.record_request("degraded", success=False, latency_ms=0.0)
        self.registry.record_request("degraded", success=True, latency_ms=100.0)
        self.registry.record_request("degraded", success=False, latency_ms=0.0)
        self.registry.record_request("degraded", success=False, latency_ms=0.0)
        self.registry.record_request("degraded", success=True, latency_ms=100.0)
        self.registry.record_request("degraded", success=False, latency_ms=0.0)
        self.registry.record_request("degraded", success=False, latency_ms=0.0)
        self.registry.record_request("degraded", success=True, latency_ms=100.0)
        self.registry.record_request("degraded", success=False, latency_ms=0.0)
        
        # Keep adapter1 healthy
        for _ in range(10):
            self.registry.record_request("healthy", success=True, latency_ms=100.0)
        
        degraded = self.registry.get_degraded_providers()
        
        assert "degraded" in degraded
        assert "healthy" not in degraded
    
    def test_get_unavailable_returns_only_unavailable_providers(self):
        """get_unavailable_providers should only return providers with UNAVAILABLE status."""
        adapter1 = MockAdapter("healthy")
        adapter2 = MockAdapter("unavailable")
        self.registry.register(adapter1)
        self.registry.register(adapter2)
        
        # Make adapter2 unavailable (5 consecutive failures)
        for _ in range(5):
            self.registry.record_request("unavailable", success=False, latency_ms=0.0)
        
        # Keep adapter1 healthy
        for _ in range(5):
            self.registry.record_request("healthy", success=True, latency_ms=100.0)
        
        unavailable = self.registry.get_unavailable_providers()
        
        assert "unavailable" in unavailable
        assert "healthy" not in unavailable
