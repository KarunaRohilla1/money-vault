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


def auth_header_for(vault, authenticated_vault=None):
    from api.security import create_access_token

    token, _expires_at = create_access_token(
        vault,
        authenticated_vault
    )
    return {"Authorization": f"Bearer {token}"}


def personal_vault(vault_id="4", name="Personal vault"):
    return SimpleNamespace(
        id=vault_id,
        name=name,
        vault_type="Individual",
        is_admin=True
    )


def shared_vault(vault_id="12", name="Shared vault"):
    return SimpleNamespace(
        id=vault_id,
        name=name,
        vault_type="Shared",
        is_admin=False
    )


def install_vault_lookup(monkeypatch):
    rows = {
        "4": (4, "Personal vault", 1, 1, "Individual"),
        "12": (12, "Shared vault", 0, 1, "Shared"),
        "99": (99, "Unrelated shared vault", 0, 1, "Shared")
    }

    monkeypatch.setattr(
        "api.auth.get_vault_by_id",
        lambda vault_id: rows.get(str(vault_id))
    )


def test_session_validation_returns_active_and_authenticated_vault(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )

    response = client.get(
        "/api/session",
        headers=auth_header_for(personal_vault())
    )

    assert response.status_code == 200
    body = response.json()
    assert body["vault"]["id"] == "4"
    assert body["authenticatedVault"]["id"] == "4"
    assert body["accessibleVaults"] == [
        {
            "id": 4,
            "name": "Personal vault",
            "isAdmin": True,
            "vaultType": "Individual"
        },
        {
            "id": 12,
            "name": "Shared vault",
            "isAdmin": False,
            "vaultType": "Shared"
        }
    ]


def test_connected_shared_vault_listing_is_scoped_to_authenticated_personal_vault(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )

    response = client.get(
        "/api/vaults/shared",
        headers=auth_header_for(personal_vault())
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 12,
            "name": "Shared vault",
            "isAdmin": False,
            "vaultType": "Shared"
        }
    ]


def test_shared_vault_activation_requires_correct_shared_pin(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    observed = {}
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )

    def fake_verify_pin(vault_name, pin):
        observed["vault_name"] = vault_name
        observed["pin"] = pin
        return (12, "Shared vault", "hash", 0, "2026-01-01")

    monkeypatch.setattr("api.auth.verify_pin", fake_verify_pin)

    response = client.post(
        "/api/vaults/shared/activate",
        headers=auth_header_for(personal_vault()),
        json={
            "sharedVaultId": 12,
            "pin": "0123"
        }
    )

    assert response.status_code == 200
    assert observed == {
        "vault_name": "Shared vault",
        "pin": "0123"
    }
    body = response.json()
    assert body["token"]
    assert body["vault"]["id"] == "12"
    assert body["vault"]["vaultType"] == "Shared"
    assert body["authenticatedVault"]["id"] == "4"
    assert "0123" not in response.text
    assert "hash" not in response.text



def test_shared_vault_activation_without_pin_for_connected_vault(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    observed = {"verify_called": False}
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )

    def fake_verify_pin(_vault_name, _pin):
        observed["verify_called"] = True
        return None

    monkeypatch.setattr("api.auth.verify_pin", fake_verify_pin)

    response = client.post(
        "/api/vaults/shared/activate",
        headers=auth_header_for(personal_vault()),
        json={
            "sharedVaultId": 12
        }
    )

    assert response.status_code == 200
    assert observed["verify_called"] is False
    body = response.json()
    assert body["token"]
    assert body["vault"]["id"] == "12"
    assert body["vault"]["vaultType"] == "Shared"
    assert body["authenticatedVault"]["id"] == "4"

def test_shared_vault_activation_rejects_wrong_pin_without_switching(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )
    monkeypatch.setattr("api.auth.verify_pin", lambda _vault_name, _pin: None)

    response = client.post(
        "/api/vaults/shared/activate",
        headers=auth_header_for(personal_vault()),
        json={
            "sharedVaultId": 12,
            "pin": "9999"
        }
    )

    assert response.status_code == 401
    assert response.json() == {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid vault credentials."
    }


def test_unrelated_shared_vault_cannot_be_activated(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )
    monkeypatch.setattr("api.auth.verify_pin", lambda _vault_name, _pin: (99, "Unrelated", "hash", 0, "2026-01-01"))

    response = client.post(
        "/api/vaults/shared/activate",
        headers=auth_header_for(personal_vault()),
        json={
            "sharedVaultId": 99,
            "pin": "1234"
        }
    )

    assert response.status_code == 403
    assert response.json() == {
        "code": "SHARED_VAULT_FORBIDDEN",
        "message": "Shared vault is not connected to this personal vault."
    }


def test_return_to_personal_vault_does_not_require_personal_pin(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )

    response = client.post(
        "/api/vaults/personal/activate",
        headers=auth_header_for(shared_vault(), personal_vault())
    )

    assert response.status_code == 200
    body = response.json()
    assert body["vault"]["id"] == "4"
    assert body["vault"]["vaultType"] == "Individual"
    assert body["authenticatedVault"]["id"] == "4"


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
