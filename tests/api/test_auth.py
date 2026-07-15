from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient


def build_client(monkeypatch, *, raise_server_exceptions=True):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()

    from api.main import create_app

    return TestClient(
        create_app(),
        raise_server_exceptions=raise_server_exceptions
    )


def test_valid_login_returns_token_and_safe_vault_metadata(monkeypatch):
    client = build_client(monkeypatch)

    monkeypatch.setattr(
        "api.auth.verify_pin",
        lambda vault_name, pin: (7, vault_name, "pin-hash", 1, "2026-01-01")
    )
    monkeypatch.setattr(
        "api.auth.get_vault_by_id",
        lambda vault_id: (vault_id, "Karuna", 1, 1, "Individual")
    )

    response = client.post(
        "/api/login",
        json={
            "vaultName": "Karuna",
            "pin": "1234"
        }
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["vault"] == {
        "id": "7",
        "name": "Karuna",
        "isAdmin": True,
        "vaultType": "Individual"
    }
    assert "expiresAt" in body
    assert "pin" not in body
    assert "pin_hash" not in body


@pytest.mark.parametrize(
    "payload",
    [
        {"vaultName": "Exact Vault", "pin": "0123"},
        {"vault_name": "Exact Vault", "pin": "0123"},
    ]
)
def test_login_accepts_supported_vault_name_fields_and_preserves_pin(monkeypatch, payload):
    client = build_client(monkeypatch)
    observed = {}

    def fake_verify_pin(vault_name, pin):
        observed["vault_name"] = vault_name
        observed["pin"] = pin
        return (9, vault_name, "pin-hash", 0, "2026-01-01")

    monkeypatch.setattr("api.auth.verify_pin", fake_verify_pin)
    monkeypatch.setattr(
        "api.auth.get_vault_by_id",
        lambda vault_id: (vault_id, "Exact Vault", 0, 1, "Individual")
    )

    response = client.post("/api/login", json=payload)

    assert response.status_code == 200
    assert observed == {
        "vault_name": "Exact Vault",
        "pin": "0123"
    }


def test_login_uses_legacy_verify_pin_row_then_loads_safe_vault_metadata(monkeypatch):
    client = build_client(monkeypatch)

    monkeypatch.setattr(
        "api.auth.verify_pin",
        lambda vault_name, pin: (11, vault_name, "pin-hash", 1, "2026-01-01")
    )
    monkeypatch.setattr(
        "api.auth.get_vault_by_id",
        lambda vault_id: (vault_id, "Shared Vault", 1, 7, "Shared")
    )

    response = client.post(
        "/api/login",
        json={
            "vaultName": "Shared Vault",
            "pin": "1234"
        }
    )

    assert response.status_code == 200
    assert response.json()["vault"] == {
        "id": "11",
        "name": "Shared Vault",
        "isAdmin": True,
        "vaultType": "Shared"
    }


@pytest.mark.parametrize("verify_result", [None, False])
def test_invalid_pin_and_unknown_vault_return_generic_invalid_credentials(monkeypatch, verify_result):
    client = build_client(monkeypatch)

    monkeypatch.setattr(
        "api.auth.verify_pin",
        lambda _vault_name, _pin: verify_result
    )

    response = client.post(
        "/api/login",
        json={
            "vault_name": "Unknown",
            "pin": "0000"
        }
    )

    assert response.status_code == 401
    assert response.json() == {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid vault credentials."
    }


def test_login_database_error_returns_safe_api_error(monkeypatch):
    client = build_client(
        monkeypatch,
        raise_server_exceptions=False
    )

    from db.postgres import OperationalError

    def raise_database_error(_vault_name, _pin):
        raise OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(
        "api.auth.verify_pin",
        raise_database_error
    )

    response = client.post(
        "/api/login",
        json={
            "vault_name": "Vault",
            "pin": "0000"
        }
    )

    assert response.status_code == 500
    assert response.json() == {
        "code": "SERVER_ERROR",
        "message": "Unexpected server error."
    }
    assert "server closed" not in response.text


def test_login_response_never_contains_pin_or_pin_hash(monkeypatch):
    client = build_client(monkeypatch)

    monkeypatch.setattr(
        "api.auth.verify_pin",
        lambda vault_name, _pin: (1, vault_name, "sensitive-pin-hash", 0, "2026-01-01")
    )
    monkeypatch.setattr(
        "api.auth.get_vault_by_id",
        lambda vault_id: (vault_id, "Vault", 0, 1, "Shared")
    )

    response = client.post(
        "/api/login",
        json={
            "vaultName": "Vault",
            "pin": "9999"
        }
    )
    encoded = response.text.lower()

    assert response.status_code == 200
    assert "9999" not in encoded
    assert "sensitive-pin-hash" not in encoded
    assert "pin_hash" not in encoded


def test_valid_jwt_is_accepted(monkeypatch):
    build_client(monkeypatch)

    from api.security import create_access_token, verify_access_token

    token, _expires_at = create_access_token(
        SimpleNamespace(
            id="4",
            name="Vault",
            vault_type="Individual",
            is_admin=False
        )
    )

    vault = verify_access_token(token)

    assert vault.id == "4"
    assert vault.name == "Vault"
    assert vault.vault_type == "Individual"


def test_expired_jwt_is_rejected(monkeypatch):
    build_client(monkeypatch)

    from api.security import ExpiredAuthError, JWT_ALGORITHM, verify_access_token

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "4",
            "vault_name": "Vault",
            "vault_type": "Individual",
            "is_admin": False,
            "iat": int((now - timedelta(days=2)).timestamp()),
            "exp": int((now - timedelta(days=1)).timestamp())
        },
        "test-secret-value-with-at-least-32-bytes",
        algorithm=JWT_ALGORITHM
    )

    with pytest.raises(ExpiredAuthError):
        verify_access_token(token)


def test_malformed_jwt_is_rejected(monkeypatch):
    build_client(monkeypatch)

    from api.security import AuthError, verify_access_token

    with pytest.raises(AuthError):
        verify_access_token("not-a-jwt")
