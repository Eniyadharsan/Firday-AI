"""Tests for the Failover_Controller.

Covers property-based tests (Properties 9-12) and unit tests for automatic
provider failover behavior.

Property 9:  Backup Order Maintenance                          (Requirement 9.1)
Property 10: Failover on Provider Error                         (Requirement 9.2)
Property 11: Active Provider State After Failover               (Requirement 9.3)
Property 12: Primary Restore Notification Without Auto-Switch   (Requirement 9.6)

The restore monitoring thread is neutralized in tests by using a very large
restore_interval (so it never fires on its own) and by calling attempt_restore()
directly. Every controller is shut down in teardown to avoid lingering threads.
"""

from __future__ import annotations

from typing import Any, Generator, Optional

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from friday.modules.providers.base import Provider_Adapter
from friday.modules.providers.models import (
    GenerateResponse,
    ProviderCapabilities,
    ProviderHealth,
    ProviderStatus,
)
from friday.modules.providers.failover import Failover_Controller
from friday.modules.providers.registry import Provider_Registry


# Use a huge restore interval so the background restore thread never fires
# on its own during a test. We drive attempt_restore() manually instead.
NEVER_FIRES_INTERVAL = 3600


class MockAdapter(Provider_Adapter):
    """Configurable mock adapter for exercising failover logic.

    Args:
        name: provider_name for this adapter
        configured: value returned by is_configured()
        status: ProviderStatus reported by get_health()
        valid_config: (is_valid, error) returned by validate_config()
    """

    def __init__(
        self,
        name: str,
        configured: bool = True,
        status: ProviderStatus = ProviderStatus.OPERATIONAL,
        valid_config: bool = True,
    ) -> None:
        self._name = name
        self._configured = configured
        self._status = status
        self._valid_config = valid_config
        self._capabilities = ProviderCapabilities(
            supported_models=[f"{name}-model-1"],
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
        if self._valid_config:
            return True, None
        return False, "invalid"

    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        return GenerateResponse(
            content="ok",
            model=model or f"{self._name}-model-1",
            provider=self._name,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        yield "ok"

    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        return friday_tools

    def parse_tool_calls(self, response: Any) -> list[dict]:
        return []

    def get_available_models(self) -> list[dict[str, Any]]:
        return [{"id": f"{self._name}-model-1", "name": self._name}]

    def get_health(self) -> ProviderHealth:
        return ProviderHealth(
            status=self._status,
            latency_ms=10.0,
            success_rate=1.0,
            error_rate=0.0,
        )


# Strategy for generating provider name tokens.
_name_token = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
    min_size=1,
    max_size=12,
)


def _fresh_registry() -> Provider_Registry:
    """Reset the singleton and return a clean registry instance."""
    Provider_Registry.reset_instance()
    return Provider_Registry.get_instance()


# ---------------------------------------------------------------------------
# Property 9: Backup Order Maintenance (task 11.2)
# ---------------------------------------------------------------------------
class TestBackupOrderMaintenanceProperty:
    """Property 9: Backup Order Maintenance.

    For any backup provider list set via set_backup_order(), the
    Failover_Controller SHALL maintain that exact ordered sequence retrievable
    via get_backup_order().

    **Validates: Requirements 9.1**
    """

    @settings(max_examples=10, deadline=None,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(backups=st.lists(_name_token, max_size=15))
    def test_backup_order_is_preserved_exactly(self, backups: list[str]) -> None:
        registry = _fresh_registry()
        controller = Failover_Controller(registry, restore_interval=NEVER_FIRES_INTERVAL)
        try:
            controller.set_backup_order(backups)
            assert controller.get_backup_order() == backups
        finally:
            controller.shutdown()
            Provider_Registry.reset_instance()

    @settings(max_examples=10, deadline=None,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(backups=st.lists(_name_token, max_size=15))
    def test_backup_order_is_a_defensive_copy(self, backups: list[str]) -> None:
        # Mutating the returned list must not affect internal state.
        registry = _fresh_registry()
        controller = Failover_Controller(registry, restore_interval=NEVER_FIRES_INTERVAL)
        try:
            controller.set_backup_order(backups)
            returned = controller.get_backup_order()
            returned.append("intruder")
            assert controller.get_backup_order() == backups
        finally:
            controller.shutdown()
            Provider_Registry.reset_instance()


# ---------------------------------------------------------------------------
# Property 10: Failover on Provider Error (task 11.3)
# ---------------------------------------------------------------------------
class TestFailoverOnProviderErrorProperty:
    """Property 10: Failover on Provider Error.

    For any error returned by the active provider and for any non-empty backup
    list, the Failover_Controller SHALL select the first available backup
    provider and retry the request.

    **Validates: Requirements 9.2**
    """

    @settings(max_examples=10, deadline=None,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        backups=st.lists(_name_token, min_size=1, max_size=8, unique=True),
        error=st.text(max_size=40),
    )
    def test_handle_failure_selects_first_available_backup(
        self, backups: list[str], error: str
    ) -> None:
        registry = _fresh_registry()
        controller = Failover_Controller(registry, restore_interval=NEVER_FIRES_INTERVAL)
        try:
            # Register every backup as configured + operational (available).
            for name in backups:
                registry.register(MockAdapter(name))
            controller.set_backup_order(backups)

            # The failed/primary provider is distinct from the backups.
            failed_provider = "primary_" + "".join(backups)[:20]

            adapter = controller.handle_failure(failed_provider, error)

            assert adapter is not None
            # The first backup in priority order is chosen.
            assert adapter.provider_name == backups[0]
        finally:
            controller.shutdown()
            Provider_Registry.reset_instance()


# ---------------------------------------------------------------------------
# Property 11: Active Provider State After Failover (task 11.5)
# ---------------------------------------------------------------------------
class TestActiveProviderStateAfterFailoverProperty:
    """Property 11: Active Provider State After Failover.

    For any successful failover event, get_active_adapter() SHALL return the
    backup provider that handled the request, and get_failover_status() SHALL
    indicate in_failover=True.

    **Validates: Requirements 9.3**
    """

    @settings(max_examples=10, deadline=None,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(backups=st.lists(_name_token, min_size=1, max_size=8, unique=True))
    def test_state_reflects_backup_after_failover(self, backups: list[str]) -> None:
        registry = _fresh_registry()
        controller = Failover_Controller(registry, restore_interval=NEVER_FIRES_INTERVAL)
        try:
            for name in backups:
                registry.register(MockAdapter(name))
            controller.set_backup_order(backups)

            failed_provider = "primary_" + "".join(backups)[:20]
            adapter = controller.handle_failure(failed_provider, "boom")
            assert adapter is not None

            expected_backup = backups[0]

            # Registry now points at the backup that handled the request.
            active = registry.get_active_adapter()
            assert active is not None
            assert active.provider_name == expected_backup

            # Failover status reports in_failover=True and the backup as current.
            status = controller.get_failover_status()
            assert status["in_failover"] is True
            assert status["current"] == expected_backup
            assert status["primary"] == failed_provider
        finally:
            controller.shutdown()
            Provider_Registry.reset_instance()


# ---------------------------------------------------------------------------
# Property 12: Primary Restore Notification Without Auto-Switch (task 11.6)
# ---------------------------------------------------------------------------
class TestPrimaryRestoreNotificationProperty:
    """Property 12: Primary Restore Notification Without Auto-Switch.

    For any restore event where the primary provider becomes available during
    failover, the system SHALL emit a notification but the active provider SHALL
    remain unchanged (still the backup).

    **Validates: Requirements 9.6**
    """

    def setup_method(self) -> None:
        self.registry = _fresh_registry()
        self.controller = Failover_Controller(
            self.registry, restore_interval=NEVER_FIRES_INTERVAL
        )

    def teardown_method(self) -> None:
        self.controller.shutdown()
        Provider_Registry.reset_instance()

    def test_restore_notifies_but_does_not_switch_back(self) -> None:
        # Primary starts unavailable, backup is available.
        primary = MockAdapter("primary", status=ProviderStatus.UNAVAILABLE)
        backup = MockAdapter("backup", status=ProviderStatus.OPERATIONAL)
        self.registry.register(primary)
        self.registry.register(backup)
        self.controller.set_backup_order(["backup"])

        notifications: list[tuple[str, dict]] = []
        self.controller.set_notification_callback(
            lambda event, data: notifications.append((event, data))
        )

        # Fail over from primary to backup.
        adapter = self.controller.handle_failure("primary", "primary down")
        assert adapter is not None
        assert adapter.provider_name == "backup"

        # Primary recovers (now operational + valid config).
        primary._status = ProviderStatus.OPERATIONAL

        restored = self.controller.attempt_restore()

        # A notification is emitted.
        assert restored is True
        assert len(notifications) == 1
        event, data = notifications[0]
        assert event == "primary_restored"
        assert data["provider"] == "primary"

        # But the active provider stays the backup (no auto-switch).
        assert self.registry.get_active_provider_name() == "backup"
        status = self.controller.get_failover_status()
        assert status["in_failover"] is True
        assert status["current"] == "backup"

    def test_no_notification_when_primary_still_unavailable(self) -> None:
        primary = MockAdapter("primary", status=ProviderStatus.UNAVAILABLE)
        backup = MockAdapter("backup", status=ProviderStatus.OPERATIONAL)
        self.registry.register(primary)
        self.registry.register(backup)
        self.controller.set_backup_order(["backup"])

        notifications: list[tuple[str, dict]] = []
        self.controller.set_notification_callback(
            lambda event, data: notifications.append((event, data))
        )

        self.controller.handle_failure("primary", "primary down")

        # Primary remains unavailable -> no restore, no notification.
        restored = self.controller.attempt_restore()

        assert restored is False
        assert notifications == []
        assert self.registry.get_active_provider_name() == "backup"


# ---------------------------------------------------------------------------
# Unit tests (task 11.7)
# ---------------------------------------------------------------------------
class TestFailoverControllerUnit:
    """Unit tests for Failover_Controller.

    Requirements: 9.1, 9.2, 9.5, 9.6
    """

    def setup_method(self) -> None:
        self.registry = _fresh_registry()
        self.controller = Failover_Controller(
            self.registry, restore_interval=NEVER_FIRES_INTERVAL
        )

    def teardown_method(self) -> None:
        self.controller.shutdown()
        Provider_Registry.reset_instance()

    # --- backup order preservation ---
    def test_backup_order_preserved(self) -> None:
        order = ["anthropic", "gemini", "ollama"]
        self.controller.set_backup_order(order)
        assert self.controller.get_backup_order() == order

    def test_set_backup_order_overwrites_previous(self) -> None:
        self.controller.set_backup_order(["a", "b"])
        self.controller.set_backup_order(["c", "d", "e"])
        assert self.controller.get_backup_order() == ["c", "d", "e"]

    def test_get_backup_order_empty_by_default(self) -> None:
        assert self.controller.get_backup_order() == []

    # --- first-available selection ---
    def test_selects_first_backup_when_all_available(self) -> None:
        for name in ["anthropic", "gemini", "ollama"]:
            self.registry.register(MockAdapter(name))
        self.controller.set_backup_order(["anthropic", "gemini", "ollama"])

        adapter = self.controller.handle_failure("openai", "rate limit")

        assert adapter is not None
        assert adapter.provider_name == "anthropic"

    # --- skipping unavailable backups ---
    def test_skips_unconfigured_backup(self) -> None:
        self.registry.register(MockAdapter("anthropic", configured=False))
        self.registry.register(MockAdapter("gemini", configured=True))
        self.controller.set_backup_order(["anthropic", "gemini"])

        adapter = self.controller.handle_failure("openai", "error")

        assert adapter is not None
        assert adapter.provider_name == "gemini"

    def test_skips_unavailable_status_backup(self) -> None:
        self.registry.register(
            MockAdapter("anthropic", status=ProviderStatus.UNAVAILABLE)
        )
        self.registry.register(
            MockAdapter("gemini", status=ProviderStatus.OPERATIONAL)
        )
        self.controller.set_backup_order(["anthropic", "gemini"])

        adapter = self.controller.handle_failure("openai", "error")

        assert adapter is not None
        assert adapter.provider_name == "gemini"

    def test_skips_unregistered_backup(self) -> None:
        # "anthropic" is listed but never registered -> skipped.
        self.registry.register(MockAdapter("gemini"))
        self.controller.set_backup_order(["anthropic", "gemini"])

        adapter = self.controller.handle_failure("openai", "error")

        assert adapter is not None
        assert adapter.provider_name == "gemini"

    def test_returns_none_when_no_backup_available(self) -> None:
        self.registry.register(MockAdapter("anthropic", configured=False))
        self.controller.set_backup_order(["anthropic"])

        adapter = self.controller.handle_failure("openai", "error")

        assert adapter is None

    def test_returns_none_with_empty_backup_list(self) -> None:
        adapter = self.controller.handle_failure("openai", "error")
        assert adapter is None

    def test_already_failed_provider_is_skipped(self) -> None:
        self.registry.register(MockAdapter("anthropic"))
        self.registry.register(MockAdapter("gemini"))
        self.controller.set_backup_order(["anthropic", "gemini"])

        first = self.controller.handle_failure("openai", "err1")
        assert first is not None and first.provider_name == "anthropic"

        # Now anthropic also fails -> should move to gemini.
        second = self.controller.handle_failure("anthropic", "err2")
        assert second is not None and second.provider_name == "gemini"

    # --- failover status ---
    def test_status_not_in_failover_initially(self) -> None:
        status = self.controller.get_failover_status()
        assert status["in_failover"] is False
        assert status["primary"] is None

    def test_status_after_failover(self) -> None:
        self.registry.register(MockAdapter("anthropic"))
        self.controller.set_backup_order(["anthropic"])

        self.controller.handle_failure("openai", "error")

        status = self.controller.get_failover_status()
        assert status["in_failover"] is True
        assert status["primary"] == "openai"
        assert status["current"] == "anthropic"
        assert "openai" in status["failed_providers"]

    def test_reset_failover_clears_state(self) -> None:
        self.registry.register(MockAdapter("anthropic"))
        self.controller.set_backup_order(["anthropic"])
        self.controller.handle_failure("openai", "error")

        self.controller.reset_failover()

        status = self.controller.get_failover_status()
        assert status["in_failover"] is False
        assert status["primary"] is None
        assert status["failed_providers"] == []

    # --- restore notification behavior ---
    def test_attempt_restore_returns_false_when_not_in_failover(self) -> None:
        # Not in failover, nothing to restore.
        assert self.controller.attempt_restore() is False

    def test_attempt_restore_false_when_primary_config_invalid(self) -> None:
        primary = MockAdapter(
            "openai", status=ProviderStatus.OPERATIONAL, valid_config=False
        )
        backup = MockAdapter("anthropic")
        self.registry.register(primary)
        self.registry.register(backup)
        self.controller.set_backup_order(["anthropic"])

        notifications: list[tuple[str, dict]] = []
        self.controller.set_notification_callback(
            lambda e, d: notifications.append((e, d))
        )

        self.controller.handle_failure("openai", "error")
        # Primary reports operational but validate_config fails.
        restored = self.controller.attempt_restore()

        assert restored is False
        assert notifications == []
        assert self.registry.get_active_provider_name() == "anthropic"

    def test_restore_notification_payload_contains_current_backup(self) -> None:
        primary = MockAdapter("openai", status=ProviderStatus.UNAVAILABLE)
        backup = MockAdapter("anthropic")
        self.registry.register(primary)
        self.registry.register(backup)
        self.controller.set_backup_order(["anthropic"])

        received: dict[str, Any] = {}
        self.controller.set_notification_callback(
            lambda event, data: received.update({"event": event, **data})
        )

        self.controller.handle_failure("openai", "error")
        primary._status = ProviderStatus.OPERATIONAL

        assert self.controller.attempt_restore() is True
        assert received["event"] == "primary_restored"
        assert received["provider"] == "openai"
        assert received["current_provider"] == "anthropic"

    def test_mark_provider_recovered_removes_from_failed(self) -> None:
        self.registry.register(MockAdapter("anthropic"))
        self.controller.set_backup_order(["anthropic"])
        self.controller.handle_failure("openai", "error")

        assert "openai" in self.controller.get_failover_status()["failed_providers"]
        self.controller.mark_provider_recovered("openai")
        assert "openai" not in self.controller.get_failover_status()["failed_providers"]

    def test_helper_state_accessors(self) -> None:
        self.registry.register(MockAdapter("anthropic"))
        self.controller.set_backup_order(["anthropic"])

        assert self.controller.is_in_failover() is False
        assert self.controller.get_primary_provider() is None

        self.controller.handle_failure("openai", "error")

        assert self.controller.is_in_failover() is True
        assert self.controller.get_primary_provider() == "openai"
