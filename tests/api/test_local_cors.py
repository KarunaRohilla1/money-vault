from fastapi.testclient import TestClient


def test_development_defaults_enable_cors_star(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    from api.config import get_config

    get_config.cache_clear()
    config = get_config()
    assert config.cors_allowed_origins == ["*"]
    assert config.is_production is False

    from api.main import create_app

    client = TestClient(create_app())
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == "*"
