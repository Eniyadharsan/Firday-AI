"""Metrics Collector for tool calling routing observability.

This module implements the MetricsCollector that tracks routing metrics
with a rolling 5-minute window for observability purposes. Metrics are
exposed via the health endpoint for monitoring.

**Validates: Requirement 10.4**
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from friday.modules.tool_calling.models import RoutingMetrics


@dataclass
class SelectionEvent:
    """A single tool selection event with timestamp.

    Attributes:
        timestamp: Unix timestamp when the event occurred.
        latency_ms: Selection latency in milliseconds.
        success: Whether the LLM tool selection succeeded.
        fallback: Whether fallback routing was used.
    """

    timestamp: float
    latency_ms: float
    success: bool
    fallback: bool


class MetricsCollector:
    """Collects routing metrics with a rolling 5-minute window.

    This class implements a singleton pattern via `get_instance()` to ensure
    a single collector is shared across the application. Events are stored
    with timestamps and automatically pruned when calculating metrics.

    Thread safety is ensured via a threading.Lock for concurrent access.

    Attributes:
        _instance: Class-level singleton instance.
        _events: List of recorded selection events.
        _lock: Threading lock for thread-safe operations.
        _window_seconds: Duration of the rolling window in seconds (300 = 5 minutes).
    """

    _instance: MetricsCollector | None = None
    _window_seconds: float = 300.0  # 5 minutes

    def __init__(self) -> None:
        """Initialize an empty metrics collector.

        Note: Use `get_instance()` instead of direct instantiation to ensure
        singleton behavior.
        """
        self._events: list[SelectionEvent] = []
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> MetricsCollector:
        """Return the singleton instance of the MetricsCollector.

        Creates a new instance on first call, returns the existing instance
        on subsequent calls.

        Returns:
            The singleton MetricsCollector instance.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (primarily for testing).

        This method clears the singleton instance, allowing a fresh collector
        to be created on the next `get_instance()` call.
        """
        cls._instance = None

    def record_selection(
        self,
        latency_ms: float,
        success: bool,
        fallback: bool,
    ) -> None:
        """Record a tool selection event.

        Stores the event with a timestamp for later metric calculation.
        Thread-safe via internal locking.

        Args:
            latency_ms: Selection latency in milliseconds.
            success: Whether the LLM tool selection succeeded.
            fallback: Whether fallback routing was used.

        **Validates: Requirement 10.4**
        """
        event = SelectionEvent(
            timestamp=time.time(),
            latency_ms=latency_ms,
            success=success,
            fallback=fallback,
        )
        with self._lock:
            self._events.append(event)

    def get_metrics(self) -> RoutingMetrics:
        """Get current metrics calculated over the rolling 5-minute window.

        Prunes events older than 5 minutes before calculating metrics.
        Thread-safe via internal locking.

        Returns:
            RoutingMetrics with aggregated statistics from the window.

        **Validates: Requirement 10.4**
        """
        with self._lock:
            self._prune_old_events()
            return self._calculate_metrics()

    def _prune_old_events(self) -> None:
        """Remove events older than the rolling window.

        Must be called while holding the lock.
        """
        cutoff = time.time() - self._window_seconds
        self._events = [e for e in self._events if e.timestamp >= cutoff]

    def _calculate_metrics(self) -> RoutingMetrics:
        """Calculate metrics from current events.

        Must be called while holding the lock after pruning.

        Returns:
            RoutingMetrics aggregated from all events in the window.
        """
        total_requests = len(self._events)
        successful_selections = sum(1 for e in self._events if e.success)
        fallback_count = sum(1 for e in self._events if e.fallback)
        total_latency_ms = sum(e.latency_ms for e in self._events if e.success)

        return RoutingMetrics(
            total_requests=total_requests,
            successful_selections=successful_selections,
            fallback_count=fallback_count,
            total_latency_ms=total_latency_ms,
        )

    def clear(self) -> None:
        """Remove all recorded events (primarily for testing).

        Thread-safe via internal locking.
        """
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        """Return the number of events in the current window.

        Thread-safe via internal locking.
        """
        with self._lock:
            self._prune_old_events()
            return len(self._events)
