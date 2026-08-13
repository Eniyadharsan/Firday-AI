"""Unit tests for the Multi-Provider AI management API routes in app.py.

Covers (spec task 14.4):
- GET  /api/providers                    (list + status)
- GET  /api/providers/active             (current active provider/model)
- PUT  /api/providers/active             (switch active provider; 200 valid / 404 unknown)
- POST /api/providers/<provider>/validate (key validation, monkeypatched — no network I/O)
- GET  /api/providers/<provider>/models  (available models; 404 for unknown provider)
- GET  /health                           (provider health metrics section)

Auth uses the real dev-login flow (DEV_AUTO_LOGIN is enabled in .env). Importing
`app` triggers friday.config which runs load_dotenv(), so the dev credentials are
available. No real provider API calls are made — validate_key is monkeypatched.
"""

from __future__ import annotations

import pytest

# Importing app runs friday.config (load_dotenv) at import time, so dev-login works.
import app as app_module
from app import app

# Multi-provider routes return 503 when provider support failed to import. The
# providers package imports cleanly in this environment, but guard anyway so the
# suite degrades gracefully rather than producing misleading failures.
pytestmark = pytest.mark.skipif(
    not getattr(app_module, "_MULTI_PROVIDER_AVAILABLE", False)
    or getattr(app_module, "_provider_registry", None) is None,
    reason="Multi-provider support is not available in this environment",
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth_headers(client):
    """Obtain a real JWT via the dev-login endpoint and build the Bearer header."""
    resp = client.post("/auth/dev-login")
    assert resp.status_code == 200, f"dev-login failed: {resp.status_code} {resp.data!r}"
    token = resp.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _registered_provider_name(client, auth_headers):
    """Return the name of one registered provider from GET /api/providers."""
    resp = client.get("/api/providers", headers=auth_headers)
    assert resp.status_code == 200
    providers = resp.get_json()["providers"]
    assert providers, "expected at least one registered provider"
    return providers[0]["name"]


class TestListProviders:
    def test_requires_auth(self, client):
        resp = client.get("/api/providers")
        assert resp.status_code == 401

    def test_returns_provider_list_and_active_keys(self, client, auth_headers):
        resp = client.get("/api/providers", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "providers" in data
        assert isinstance(data["providers"], list)
        assert "active_provider" in data
        assert "active_model" in data

    def test_each_provider_has_name_and_status(self, client, auth_headers):
        data = client.get("/api/providers", headers=auth_headers).get_json()
        for p in data["providers"]:
            assert "name" in p
            assert "status" in p
            assert "is_active" in p


class TestActiveProviderGet:
    def test_requires_auth(self, client):
        assert client.get("/api/providers/active").status_code == 401

    def test_returns_provider_and_model(self, client, auth_headers):
        resp = client.get("/api/providers/active", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "provider" in data
        assert "model" in data


class TestActiveProviderPut:
    def test_set_valid_provider_returns_200(self, client, auth_headers):
        name = _registered_provider_name(client, auth_headers)
        resp = client.put(
            "/api/providers/active",
            json={"provider": name},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["provider"] == name

    def test_set_unregistered_provider_returns_404(self, client, auth_headers):
        resp = client.put(
            "/api/providers/active",
            json={"provider": "definitely-not-a-real-provider"},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert "error" in resp.get_json()

    def test_missing_provider_returns_400(self, client, auth_headers):
        resp = client.put("/api/providers/active", json={}, headers=auth_headers)
        assert resp.status_code == 400
        assert "error" in resp.get_json()


class TestValidateProviderKey:
    def test_valid_key_returns_valid_true(self, client, auth_headers, monkeypatch):
        # Monkeypatch so no network I/O happens and no key is really stored.
        monkeypatch.setattr(app_module._key_store, "validate_key", lambda p, k: (True, None))
        monkeypatch.setattr(app_module._key_store, "set_key", lambda p, k: None)

        resp = client.post(
            "/api/providers/openai/validate",
            json={"api_key": "sk-test-key"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"valid": True}

    def test_invalid_key_returns_400_with_error(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(app_module._key_store, "validate_key", lambda p, k: (False, "bad"))

        resp = client.post(
            "/api/providers/openai/validate",
            json={"api_key": "sk-bad"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["valid"] is False
        assert data["error"] == "bad"

    def test_missing_api_key_returns_400(self, client, auth_headers):
        resp = client.post(
            "/api/providers/openai/validate",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.get_json()["valid"] is False

    def test_key_never_returned_to_client(self, client, auth_headers, monkeypatch):
        # Requirement 10.4 — the validated key must never be echoed back.
        secret = "sk-super-secret-value"
        monkeypatch.setattr(app_module._key_store, "validate_key", lambda p, k: (True, None))
        monkeypatch.setattr(app_module._key_store, "set_key", lambda p, k: None)

        resp = client.post(
            "/api/providers/openai/validate",
            json={"api_key": secret},
            headers=auth_headers,
        )
        assert secret not in resp.get_data(as_text=True)


class TestProviderModels:
    def test_returns_models_for_registered_provider(self, client, auth_headers):
        name = _registered_provider_name(client, auth_headers)
        resp = client.get(f"/api/providers/{name}/models", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["provider"] == name
        assert isinstance(data["models"], list)

    def test_unregistered_provider_returns_404(self, client, auth_headers):
        resp = client.get(
            "/api/providers/definitely-not-a-real-provider/models",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert "error" in resp.get_json()


class TestHealthProviderMetrics:
    def test_health_ok_and_reports_database(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "running"
        assert "database" in data

    def test_health_includes_provider_metrics_when_available(self, client):
        data = client.get("/health").get_json()
        # Multi-provider support is loaded in this environment, so the health
        # payload should surface per-provider metrics and the active provider.
        if app_module._MULTI_PROVIDER_AVAILABLE and app_module._provider_registry is not None:
            assert "providers" in data
            assert isinstance(data["providers"], dict)
            for metrics in data["providers"].values():
                assert "status" in metrics
                assert "latency_ms" in metrics
                assert "success_rate" in metrics
                assert "error_rate" in metrics
            assert "active_provider" in data
