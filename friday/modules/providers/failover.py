"""Failover Controller for automatic provider failover management.

This module implements the Failover_Controller class that manages automatic
provider failover when the active provider fails. It maintains an ordered list
of backup providers and attempts to restore the primary provider periodically.

The controller coordinates with Provider_Registry to:
- Track which providers are available as backups
- Handle provider failures by selecting the next available backup
- Periodically check if the primary provider has recovered
- Notify users when the primary provider becomes available again

Requirements: 9.1, 9.2, 9.4, 9.5, 9.6
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

from friday.modules.providers.models import ProviderStatus

if TYPE_CHECKING:
    from friday.modules.providers.base import Provider_Adapter
    from friday.modules.providers.registry import Provider_Registry


class Failover_Controller:
    """Manages automatic provider failover on errors.
    
    Maintains an ordered list of backup providers and coordinates failover
    when the active provider fails. Attempts to restore the primary provider
    periodically after failover occurs.
    
    The controller does NOT automatically switch back to the primary provider
    when it becomes available - instead, it notifies the user via a callback
    so they can decide whether to switch back manually.
    
    Attributes:
        registry: Reference to the Provider_Registry for getting adapters
        _backup_order: Ordered list of backup provider names
        _primary_provider: The original primary provider before failover
        _in_failover: Whether the system is currently operating on a backup
        _failover_time: Timestamp when failover occurred
        _restore_interval: Seconds between restore attempts (default 60)
        _notification_callback: Callback function for user notifications
        _restore_thread: Background thread for periodic restore attempts
        _stop_restore: Event to signal the restore thread to stop
    
    Example:
        registry = Provider_Registry.get_instance()
        failover = Failover_Controller(registry)
        failover.set_backup_order(["anthropic", "gemini", "ollama"])
        failover.set_notification_callback(notify_user)
        
        # When primary fails:
        backup_adapter = failover.handle_failure("openai", "API rate limit exceeded")
        if backup_adapter:
            response = backup_adapter.generate(messages)
    
    Requirements: 9.1, 9.2, 9.4, 9.5, 9.6
    """

    def __init__(
        self,
        registry: "Provider_Registry",
        restore_interval: int = 60,
    ) -> None:
        """Initialize the Failover_Controller.
        
        Args:
            registry: The Provider_Registry instance for getting adapters
            restore_interval: Seconds between restore attempts (default 60)
        """
        self.registry = registry
        self._backup_order: list[str] = []
        self._primary_provider: Optional[str] = None
        self._in_failover: bool = False
        self._failover_time: Optional[datetime] = None
        self._restore_interval: int = restore_interval
        self._notification_callback: Optional[Callable[[str, dict[str, Any]], None]] = None
        self._restore_thread: Optional[threading.Thread] = None
        self._stop_restore: threading.Event = threading.Event()
        self._lock: threading.Lock = threading.Lock()
        self._current_backup: Optional[str] = None
        self._failed_providers: set[str] = set()

    def set_backup_order(self, providers: list[str]) -> None:
        """Set the ordered list of backup providers.
        
        Property 9: Backup Order Maintenance
        For any backup provider list set via set_backup_order(), the 
        Failover_Controller SHALL maintain that exact ordered sequence
        retrievable via get_backup_order().
        
        Args:
            providers: List of provider names in priority order (first = highest priority)
        
        Example:
            failover.set_backup_order(["anthropic", "gemini", "ollama"])
        
        Requirements: 9.1
        """
        with self._lock:
            self._backup_order = list(providers)

    def get_backup_order(self) -> list[str]:
        """Get the current ordered list of backup providers.
        
        Returns:
            Copy of the backup provider list in priority order
        """
        with self._lock:
            return list(self._backup_order)

    def set_notification_callback(
        self,
        callback: Callable[[str, dict[str, Any]], None],
    ) -> None:
        """Set the callback function for user notifications.
        
        The callback will be called when the primary provider becomes
        available again after failover. It receives:
        - event_type: String identifying the notification type
        - data: Dictionary with event details
        
        Args:
            callback: Function to call for notifications
        
        Example:
            def notify_user(event_type: str, data: dict):
                if event_type == "primary_restored":
                    show_notification(f"Primary provider {data['provider']} is available again")
            
            failover.set_notification_callback(notify_user)
        """
        self._notification_callback = callback

    def handle_failure(
        self,
        failed_provider: str,
        error: str,
    ) -> Optional["Provider_Adapter"]:
        """Handle provider failure and return next available backup.
        
        Property 10: Failover on Provider Error
        For any error returned by the active provider and for any non-empty
        backup list, the Failover_Controller SHALL select the first available
        backup provider and retry the request.
        
        Property 11: Active Provider State After Failover
        For any successful failover event, get_active_adapter() SHALL return
        the backup provider that handled the request, and get_failover_status()
        SHALL indicate in_failover=True.
        
        This method:
        1. Records the failed provider
        2. If not already in failover, stores the original primary provider
        3. Iterates through backup providers to find one that is available
        4. Updates the active provider in the registry
        5. Starts the restore monitoring thread if not already running
        
        Args:
            failed_provider: Name of the provider that failed
            error: Error message describing the failure
            
        Returns:
            The next available Provider_Adapter, or None if all providers failed
        
        Example:
            backup = failover.handle_failure("openai", "Rate limit exceeded")
            if backup:
                response = backup.generate(messages)
            else:
                return error_response("All providers are unavailable")
        
        Requirements: 9.2, 9.4
        """
        with self._lock:
            # Track this provider as failed
            self._failed_providers.add(failed_provider)
            
            # If not already in failover, record the primary provider
            if not self._in_failover:
                self._primary_provider = failed_provider
                self._in_failover = True
                self._failover_time = datetime.now()
            
            # Find the first available backup provider
            backup_adapter = self._find_available_backup()
            
            if backup_adapter is not None:
                # Update the active provider in the registry
                provider_name = backup_adapter.provider_name
                self._current_backup = provider_name
                self.registry.set_active(provider_name)
                
                # Start the restore monitoring thread if not running
                self._start_restore_thread()
                
                return backup_adapter
            
            # All providers failed
            return None

    def _find_available_backup(self) -> Optional["Provider_Adapter"]:
        """Find the first available backup provider.
        
        Iterates through the backup order, skipping:
        - Providers that have already failed
        - Providers that are not configured
        - Providers that are unavailable
        
        Returns:
            First available Provider_Adapter, or None if none available
        """
        for provider_name in self._backup_order:
            # Skip providers that have already failed in this failover session
            if provider_name in self._failed_providers:
                continue
            
            adapter = self.registry.get_adapter(provider_name)
            if adapter is None:
                continue
            
            # Check if the provider is configured and available
            try:
                if not adapter.is_configured():
                    continue
                
                health = adapter.get_health()
                if health.status == ProviderStatus.UNAVAILABLE:
                    continue
                
                return adapter
            except Exception:
                # If we can't check the provider, skip it
                continue
        
        return None

    def _start_restore_thread(self) -> None:
        """Start the background thread for periodic restore attempts.
        
        The thread will check if the primary provider is available every
        _restore_interval seconds. If available, it emits a notification
        but does NOT automatically switch back.
        """
        if self._restore_thread is not None and self._restore_thread.is_alive():
            return
        
        self._stop_restore.clear()
        self._restore_thread = threading.Thread(
            target=self._restore_loop,
            daemon=True,
            name="FailoverRestoreThread",
        )
        self._restore_thread.start()

    def _restore_loop(self) -> None:
        """Background loop that periodically attempts to restore the primary provider.
        
        Runs every _restore_interval seconds while in failover mode.
        When the primary provider becomes available, emits a notification
        but does not automatically switch back (per Requirement 9.6).
        
        Requirements: 9.5, 9.6
        """
        while not self._stop_restore.is_set():
            # Wait for the restore interval
            if self._stop_restore.wait(timeout=self._restore_interval):
                # Stop event was set
                break
            
            # Check if we're still in failover mode
            with self._lock:
                if not self._in_failover:
                    break
                
                primary = self._primary_provider
            
            if primary is None:
                continue
            
            # Attempt to restore
            restored = self.attempt_restore()
            if restored:
                # Notification has been sent, but we continue monitoring
                # in case the primary goes down again
                pass

    def attempt_restore(self) -> bool:
        """Attempt to restore the primary provider.
        
        Property 12: Primary Restore Notification Without Auto-Switch
        For any restore event where the primary provider becomes available
        during failover, the system SHALL emit a notification but the active
        provider SHALL remain unchanged (still the backup).
        
        Called periodically (every 60 seconds by default) after failover to
        check if the primary is available again. When available:
        - Emits a notification via the callback
        - Does NOT automatically switch back
        - User must manually switch via Model Manager
        
        Returns:
            True if primary was found available and notification sent
        
        Requirements: 9.5, 9.6
        """
        with self._lock:
            if not self._in_failover or self._primary_provider is None:
                return False
            
            primary = self._primary_provider
        
        # Check if the primary provider is available
        adapter = self.registry.get_adapter(primary)
        if adapter is None:
            return False
        
        try:
            # Check configuration
            if not adapter.is_configured():
                return False
            
            # Check health status
            health = adapter.get_health()
            if health.status == ProviderStatus.UNAVAILABLE:
                return False
            
            # Try to validate the configuration (makes a test API call)
            is_valid, error_msg = adapter.validate_config()
            if not is_valid:
                return False
            
            # Primary is available! Emit notification but don't switch back
            self._emit_restore_notification(primary)
            
            # Remove from failed providers so it can be used again
            with self._lock:
                self._failed_providers.discard(primary)
            
            return True
            
        except Exception:
            return False

    def _emit_restore_notification(self, provider: str) -> None:
        """Emit a notification that the primary provider is available.
        
        Args:
            provider: Name of the restored primary provider
        """
        if self._notification_callback is not None:
            try:
                self._notification_callback(
                    "primary_restored",
                    {
                        "provider": provider,
                        "message": f"Primary provider '{provider}' is available again. "
                                   "You can switch back via the Model Manager.",
                        "current_provider": self._current_backup,
                        "timestamp": datetime.now().isoformat(),
                    },
                )
            except Exception:
                # Don't let notification failures break the restore logic
                pass

    def get_failover_status(self) -> dict[str, Any]:
        """Get current failover status for UI display.
        
        Returns a dictionary with:
        - in_failover: Whether currently operating on a backup provider
        - primary: The original primary provider (if in failover)
        - current: The current active provider
        - elapsed_time: Seconds since failover occurred
        - backup_order: The ordered list of backup providers
        - failed_providers: Set of providers that have failed
        
        Returns:
            Dictionary with failover status information
        
        Example:
            status = failover.get_failover_status()
            if status["in_failover"]:
                show_banner(f"Using backup provider. Primary was: {status['primary']}")
        """
        with self._lock:
            elapsed_seconds: Optional[float] = None
            if self._failover_time is not None:
                elapsed_seconds = (datetime.now() - self._failover_time).total_seconds()
            
            return {
                "in_failover": self._in_failover,
                "primary": self._primary_provider,
                "current": self._current_backup or self.registry.get_active_provider_name(),
                "elapsed_time": elapsed_seconds,
                "backup_order": list(self._backup_order),
                "failed_providers": list(self._failed_providers),
            }

    def reset_failover(self) -> None:
        """Reset the failover state.
        
        Call this when manually switching providers or when the user
        chooses to switch back to the primary provider.
        
        This will:
        - Clear the failover state
        - Stop the restore monitoring thread
        - Clear the list of failed providers
        """
        with self._lock:
            self._in_failover = False
            self._primary_provider = None
            self._failover_time = None
            self._current_backup = None
            self._failed_providers.clear()
        
        # Stop the restore thread
        self._stop_restore.set()
        if self._restore_thread is not None:
            self._restore_thread.join(timeout=2.0)
            self._restore_thread = None

    def mark_provider_recovered(self, provider: str) -> None:
        """Mark a provider as recovered (no longer failed).
        
        Use this when a provider that previously failed becomes available again.
        
        Args:
            provider: Name of the provider that has recovered
        """
        with self._lock:
            self._failed_providers.discard(provider)

    def is_in_failover(self) -> bool:
        """Check if currently in failover mode.
        
        Returns:
            True if operating on a backup provider
        """
        with self._lock:
            return self._in_failover

    def get_primary_provider(self) -> Optional[str]:
        """Get the original primary provider name.
        
        Returns:
            Name of the primary provider if in failover, None otherwise
        """
        with self._lock:
            return self._primary_provider

    def shutdown(self) -> None:
        """Shutdown the failover controller.
        
        Stops the restore monitoring thread and cleans up resources.
        Call this when shutting down the application.
        """
        self._stop_restore.set()
        if self._restore_thread is not None:
            self._restore_thread.join(timeout=5.0)
            self._restore_thread = None
