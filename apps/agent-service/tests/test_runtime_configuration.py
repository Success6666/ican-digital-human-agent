from __future__ import annotations

from starlette.testclient import TestClient

from app.main import build_container, create_app
from app.settings import Settings


def _headers(*, role: str = "admin") -> dict[str, str]:
    return {
        "X-Internal-Token": "test-token",
        "X-User-Id": "u1",
        "X-User-Name": "Operator",
        "X-User-Role": role,
    }


def _settings(path: str) -> Settings:
    return Settings(
        internal_token="test-token",
        runtime_configuration_file=path,
        mcp_allow_local_fallback=False,
    )


def test_admin_update_is_applied_and_persisted(tmp_path) -> None:
    configuration_path = str(tmp_path / "runtime.json")
    container = build_container(_settings(configuration_path))

    with TestClient(create_app(container=container)) as client:
        response = client.patch(
            "/internal/configuration",
            headers=_headers(),
            json={
                "defaultProvider": "mock",
                "session": {"ttlSeconds": 600, "cleanupIntervalSeconds": 12},
            },
        )
        assert response.status_code == 200
        assert response.json()["defaultProvider"] == "mock"
        assert response.json()["session"] == {"ttlSeconds": 600, "cleanupIntervalSeconds": 12}
        assert container.store.ttl_seconds == 600
        assert container.store.idle_timeout_seconds == 600
        assert container.cleanup.interval_seconds == 12

        created = client.post("/internal/sessions", headers=_headers(role="user"), json={})
        assert created.status_code == 201
        assert created.json()["provider"] == "mock"

    restarted = build_container(_settings(configuration_path))
    assert restarted.settings.default_provider == "mock"
    assert restarted.settings.session_ttl_seconds == 600
    assert restarted.settings.cleanup_interval_seconds == 12


def test_runtime_update_requires_admin_and_valid_provider(tmp_path) -> None:
    container = build_container(_settings(str(tmp_path / "runtime.json")))
    with TestClient(create_app(container=container)) as client:
        forbidden = client.patch(
            "/internal/configuration",
            headers=_headers(role="user"),
            json={"session": {"ttlSeconds": 900}},
        )
        assert forbidden.status_code == 403

        unavailable = client.patch(
            "/internal/configuration",
            headers=_headers(),
            json={"defaultProvider": "mofa"},
        )
        assert unavailable.status_code == 422

        invalid = client.patch(
            "/internal/configuration",
            headers=_headers(),
            json={"session": {"ttlSeconds": 20}},
        )
        assert invalid.status_code == 422


def test_configuration_response_does_not_expose_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MOFA_APP_ID", "private-app-id")
    monkeypatch.setenv("MOFA_APP_SECRET", "private-app-secret")
    settings = _settings(str(tmp_path / "runtime.json")).model_copy(
        update={"provider_enabled": {"mofa": True}}
    )
    container = build_container(settings)

    with TestClient(create_app(container=container)) as client:
        response = client.get("/internal/configuration", headers=_headers(role="user"))
        assert response.status_code == 200
        serialized = response.text
        assert "private-app-id" not in serialized
        assert "private-app-secret" not in serialized
