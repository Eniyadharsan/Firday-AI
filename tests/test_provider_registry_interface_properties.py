"""Property-based tests for Provider_Registry interface validation.

Property 3: Interface Validation on Registration
- For any Provider_Adapter implementation, registration in Provider_Registry
  SHALL succeed if and only if all required interface methods
  (generate, stream_generate, translate_tools, parse_tool_calls,
   get_available_models, get_health, is_configured, validate_config)
  AND properties (provider_name, capabilities) are implemented.

Validates: Requirements 1.4

Implementation notes
--------------------
`Provider_Registry._validate_adapter_interface()` inspects a candidate adapter
using ``hasattr`` / ``callable`` / ``__isabstractmethod__`` checks rather than an
``isinstance`` check, so it accepts any object that exposes the required surface.

Because ``Provider_Adapter`` is an ``abc.ABC``, a subclass that omits an abstract
method cannot be instantiated. To exercise the *incomplete* cases we therefore
build plain dynamic classes (via ``type(...)``) that expose only a chosen subset
of the required members. The *complete* case is covered both by a dynamic class
with the full surface and by a real ``Provider_Adapter`` subclass.
"""

from __future__ import annotations

from typing import Any, Generator, Optional

import pytest
from hypothesis import given
from hypothesis import strategies as st

from friday.modules.providers.base import Provider_Adapter
from friday.modules.providers.models import (
    GenerateResponse,
    ProviderCapabilities,
    ProviderHealth,
    ProviderStatus,
)
from friday.modules.providers.registry import (
    REQUIRED_INTERFACE_METHODS,
    REQUIRED_INTERFACE_PROPERTIES,
    Provider_Registry,
)

# The complete set of interface members that must be present for a successful
# registration. Read directly from the registry so the test stays in sync with
# the production requirement lists.
ALL_METHODS = list(REQUIRED_INTERFACE_METHODS)
ALL_PROPERTIES = list(REQUIRED_INTERFACE_PROPERTIES)
ALL_MEMBERS = ALL_METHODS + ALL_PROPERTIES


# --------------------------------------------------------------------------- #
# Singleton isolation
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _isolate_registry_singleton() -> Generator[None, None, None]:
    """Reset the Provider_Registry singleton around every test/example."""
    Provider_Registry.reset_instance()
    yield
    Provider_Registry.reset_instance()


# --------------------------------------------------------------------------- #
# A complete, real Provider_Adapter subclass (positive control)
# --------------------------------------------------------------------------- #
class CompleteMockAdapter(Provider_Adapter):
    """A fully-implemented adapter that satisfies the entire interface."""

    @property
    def provider_name(self) -> str:
        return "complete_mock"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_models=["mock-model-1"])

    def is_configured(self) -> bool:
        return True

    def validate_config(self) -> tuple[bool, Optional[str]]:
        return True, None

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
            model="mock-model-1",
            provider="complete_mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
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
        return [{"id": "mock-model-1", "name": "Mock", "context_window": 8192}]

    def get_health(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderStatus.OPERATIONAL,
            latency_ms=0.0,
            success_rate=1.0,
            error_rate=0.0,
        )


# --------------------------------------------------------------------------- #
# Dynamic adapter construction for arbitrary member subsets
# --------------------------------------------------------------------------- #
def _make_method(name: str):
    """Create a concrete callable for the given interface method name.

    The returned callables are plain functions (no ``__isabstractmethod__``),
    so the registry treats them as implemented. Return values are chosen so the
    registry's post-validation success path (which calls ``is_configured`` and
    reads ``capabilities``) behaves sensibly.
    """
    if name == "is_configured":
        def is_configured(self) -> bool:
            return False
        return is_configured
    if name == "validate_config":
        def validate_config(self):
            return True, None
        return validate_config

    def _generic(self, *args, **kwargs):
        return None

    _generic.__name__ = name
    return _generic


def build_adapter(included: frozenset[str]):
    """Build and instantiate a plain adapter object exposing only `included`.

    Uses a plain ``object`` subclass (not the ABC) so that objects with a
    partial interface can be instantiated for testing the negative cases.
    """
    namespace: dict[str, Any] = {}

    for method_name in ALL_METHODS:
        if method_name in included:
            namespace[method_name] = _make_method(method_name)

    if "provider_name" in included:
        namespace["provider_name"] = "dynamic_mock"
    if "capabilities" in included:
        namespace["capabilities"] = ProviderCapabilities(
            supported_models=["mock-model-1"]
        )

    adapter_cls = type("DynamicAdapter", (object,), namespace)
    return adapter_cls()


# --------------------------------------------------------------------------- #
# Property 3: registration succeeds iff the full interface is present
# --------------------------------------------------------------------------- #
@given(included=st.sets(st.sampled_from(ALL_MEMBERS)).map(frozenset))
def test_registration_succeeds_iff_interface_complete(included: frozenset[str]) -> None:
    """register() returns None iff every required member is present.

    Validates: Requirements 1.4
    """
    # Reset per Hypothesis example: @given reuses one test-function invocation
    # (and thus one singleton) across many generated examples.
    Provider_Registry.reset_instance()
    registry = Provider_Registry.get_instance()
    adapter = build_adapter(included)

    result = registry.register(adapter)

    is_complete = included.issuperset(ALL_MEMBERS)
    registered = registry.get_adapter("dynamic_mock") is not None

    if is_complete:
        # All methods + properties present -> success (returns None).
        assert result is None, (
            f"Expected success for complete interface, got error: {result!r}"
        )
        assert registered, "Complete adapter should be retrievable after registration"
    else:
        # At least one member missing -> failure (returns an error string).
        assert isinstance(result, str) and result, (
            f"Expected an error string for incomplete interface "
            f"(missing={set(ALL_MEMBERS) - included}), got {result!r}"
        )
        assert not registered, "Incomplete adapter must not be registered"


@given(
    # Guarantee at least one missing member by dropping a required one.
    dropped=st.sampled_from(ALL_MEMBERS),
    extra_included=st.sets(st.sampled_from(ALL_MEMBERS)).map(frozenset),
)
def test_registration_fails_when_any_member_missing(
    dropped: str, extra_included: frozenset[str]
) -> None:
    """Removing any single required member causes registration to fail.

    Validates: Requirements 1.4
    """
    included = frozenset(extra_included | frozenset(ALL_MEMBERS)) - {dropped}
    assert dropped not in included  # invariant: the member is truly missing

    # Reset per Hypothesis example to isolate singleton state.
    Provider_Registry.reset_instance()
    registry = Provider_Registry.get_instance()
    adapter = build_adapter(included)

    result = registry.register(adapter)

    assert isinstance(result, str) and result, (
        f"Registration should fail when '{dropped}' is missing, got {result!r}"
    )
    # The error message should name the missing member.
    assert dropped in result


# --------------------------------------------------------------------------- #
# Positive controls using dynamic + real ABC subclass adapters
# --------------------------------------------------------------------------- #
def test_complete_dynamic_adapter_registers() -> None:
    """A dynamic adapter exposing the full interface registers successfully.

    Validates: Requirements 1.4
    """
    registry = Provider_Registry.get_instance()
    adapter = build_adapter(frozenset(ALL_MEMBERS))

    result = registry.register(adapter)

    assert result is None
    assert registry.get_adapter("dynamic_mock") is adapter


def test_complete_abc_subclass_adapter_registers() -> None:
    """A real Provider_Adapter subclass with full interface registers.

    Validates: Requirements 1.4
    """
    registry = Provider_Registry.get_instance()
    adapter = CompleteMockAdapter()

    result = registry.register(adapter)

    assert result is None
    assert registry.get_adapter("complete_mock") is adapter
