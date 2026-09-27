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


def test_username_pin_login_rejects_invalid_credentials(monkeypatch):
    client = build_client(monkeypatch)
    monkeypatch.setattr(
        "api.auth.authenticate_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(__import__("db.identity", fromlist=["IdentityError"]).IdentityError("Username or PIN is incorrect."))
    )

    response = client.post(
        "/api/login",
        json={
            "username": "karuna",
            "pin": "0000"
        }
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert "0000" not in response.text


def test_register_and_login_return_user_session(monkeypatch):
    from db.identity import ProfileRecord, VaultRecord

    client = build_client(monkeypatch)
    profile = ProfileRecord(
        id="11111111-1111-4111-8111-111111111111",
        username="karuna",
        display_name="Karuna",
        pin_hash="hashed",
        active_vault_id=4
    )
    personal = VaultRecord(id="4", name="Personal", is_admin=False, vault_type="Individual")
    monkeypatch.setattr("api.auth.register_user", lambda *_args, **_kwargs: (profile, personal))
    monkeypatch.setattr("api.auth.authenticate_user", lambda *_args, **_kwargs: (profile, personal))
    monkeypatch.setattr("api.auth.issue_recovery_code", lambda *_args, **_kwargs: "ABCD-EFGH-IJKL")
    monkeypatch.setattr("api.auth.set_active_vault", lambda *_args, **_kwargs: None)

    register_response = client.post(
        "/api/register",
        json={
            "username": "karuna",
            "displayName": "Karuna",
            "pin": "1234",
            "confirmPin": "1234"
        }
    )
    login_response = client.post(
        "/api/login",
        json={
            "username": "karuna",
            "pin": "1234"
        }
    )

    assert register_response.status_code == 200
    assert login_response.status_code == 200
    assert register_response.json()["userId"] == profile.id
    assert register_response.json()["displayName"] == "Karuna"
    assert register_response.json()["pinSet"] is True
    assert register_response.json()["recoveryCode"] == "ABCD-EFGH-IJKL"
    assert "recoveryCode" not in login_response.json()
    assert register_response.json()["vault"]["name"] == "Personal"
    assert login_response.json()["token"]
    assert "1234" not in register_response.text


def test_register_rejects_short_pin(monkeypatch):
    client = build_client(monkeypatch)

    response = client.post(
        "/api/register",
        json={
            "username": "karuna",
            "displayName": "Karuna",
            "pin": "12",
            "confirmPin": "12"
        }
    )

    assert response.status_code == 422


def test_register_rejects_pin_mismatch(monkeypatch):
    client = build_client(monkeypatch)

    response = client.post(
        "/api/register",
        json={
            "username": "karuna",
            "displayName": "Karuna",
            "pin": "1234",
            "confirmPin": "5678"
        }
    )

    assert response.status_code == 400
    assert "1234" not in response.text


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
            "vaultType": "Individual",
            "role": "owner"
        },
        {
            "id": 12,
            "name": "Shared vault",
            "isAdmin": False,
            "vaultType": "Shared",
            "role": "member"
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
            "vaultType": "Shared",
            "role": "member",
            "memberCount": 0
        }
    ]


def test_shared_vault_activation_does_not_require_pin(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )

    response = client.post(
        "/api/vaults/shared/activate",
        headers=auth_header_for(personal_vault()),
        json={
            "sharedVaultId": 12,
            "pin": "0123"
        }
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["vault"]["id"] == "12"
    assert body["vault"]["vaultType"] == "Shared"
    assert body["authenticatedVault"]["id"] == "4"
    assert "0123" not in response.text




def test_shared_vault_activation_without_pin_for_connected_vault(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )

    response = client.post(
        "/api/vaults/shared/activate",
        headers=auth_header_for(personal_vault()),
        json={
            "sharedVaultId": 12
        }
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["vault"]["id"] == "12"
    assert body["vault"]["vaultType"] == "Shared"
    assert body["authenticatedVault"]["id"] == "4"

def test_unrelated_shared_vault_cannot_be_activated(monkeypatch):
    client = build_client(monkeypatch)
    install_vault_lookup(monkeypatch)
    monkeypatch.setattr(
        "api.auth.get_connected_shared_vaults",
        lambda vault_id: [(12, "Shared vault")] if str(vault_id) == "4" else []
    )

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


def user_vault_context():
    from api.schemas import VaultContext

    return VaultContext(
        id="4",
        name="Personal vault",
        isAdmin=True,
        vaultType="Individual",
        authenticatedVaultId="4",
        authenticatedVaultName="Personal vault",
        authenticatedVaultType="Individual",
        userId="11111111-1111-4111-8111-111111111111",
        pinSet=True
    )


def test_shared_vault_listing_uses_memberships_for_user_tokens(monkeypatch):
    from db.identity import SharedVaultMembership

    client = build_client(monkeypatch)
    monkeypatch.setattr("api.dependencies.verify_access_token", lambda _token: user_vault_context())
    monkeypatch.setattr(
        "api.auth.list_shared_memberships_for_user",
        lambda user_id: [
            SharedVaultMembership(id="12", name="Our Money", role="owner", member_count=2),
            SharedVaultMembership(id="40", name="Trip Fund", role="member", member_count=3),
        ],
    )

    response = client.get("/api/vaults/shared", headers={"Authorization": "Bearer jwt-token"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 12,
            "name": "Our Money",
            "isAdmin": True,
            "vaultType": "Shared",
            "role": "owner",
            "memberCount": 2,
        },
        {
            "id": 40,
            "name": "Trip Fund",
            "isAdmin": False,
            "vaultType": "Shared",
            "role": "member",
            "memberCount": 3,
        },
    ]


def test_create_shared_vault_returns_invite_code(monkeypatch):
    from db.identity import ProfileRecord, VaultRecord

    client = build_client(monkeypatch)
    profile = ProfileRecord(
        id="11111111-1111-4111-8111-111111111111",
        username="karuna",
        display_name="Karuna",
        pin_hash="hashed",
        active_vault_id=4
    )
    created = []

    monkeypatch.setattr("api.dependencies.verify_access_token", lambda _token: user_vault_context())
    monkeypatch.setattr("api.auth.get_vault_by_id", lambda vault_id: (4, "Personal vault", 1, 1, "Individual"))
    monkeypatch.setattr("api.auth.get_profile", lambda user_id: profile)
    monkeypatch.setattr(
        "api.auth.create_shared_vault_for_user",
        lambda user_id, name: created.append((user_id, name)) or VaultRecord(id="40", name=name, is_admin=False, vault_type="Shared")
    )

    response = client.post(
        "/api/vaults/shared/create",
        headers={"Authorization": "Bearer jwt-token"},
        json={"vaultName": "Household"}
    )

    assert response.status_code == 200
    body = response.json()
    assert created == [(profile.id, "Household")]
    assert body["inviteCode"] == "MV-000040"
    assert body["vault"] == {"id": "40", "name": "Household", "isAdmin": False, "vaultType": "Shared", "role": "member"}
    assert body["authenticatedVault"]["id"] == "4"
    assert body["userId"] == profile.id


def test_join_shared_vault_uses_invite_code(monkeypatch):
    from db.identity import ProfileRecord, VaultRecord

    client = build_client(monkeypatch)
    profile = ProfileRecord(
        id="11111111-1111-4111-8111-111111111111",
        username="karuna",
        display_name="Karuna",
        pin_hash="hashed",
        active_vault_id=4
    )
    joined = []

    monkeypatch.setattr("api.dependencies.verify_access_token", lambda _token: user_vault_context())
    monkeypatch.setattr("api.auth.get_vault_by_id", lambda vault_id: (4, "Personal vault", 1, 1, "Individual"))
    monkeypatch.setattr("api.auth.get_profile", lambda user_id: profile)
    monkeypatch.setattr(
        "api.auth.join_shared_vault_for_user",
        lambda user_id, invite_code: joined.append((user_id, invite_code)) or VaultRecord(id="40", name="Household", is_admin=False, vault_type="Shared")
    )

    response = client.post(
        "/api/vaults/shared/join",
        headers={"Authorization": "Bearer jwt-token"},
        json={"inviteCode": "MV-000040"}
    )

    assert response.status_code == 200
    body = response.json()
    assert joined == [(profile.id, "MV-000040")]
    assert body["vault"]["id"] == "40"
    assert body["vault"]["vaultType"] == "Shared"
    assert body["authenticatedVault"]["id"] == "4"


def test_recover_pin_with_valid_recovery_code(monkeypatch):
    from db.identity import ProfileRecord, VaultRecord

    client = build_client(monkeypatch)
    profile = ProfileRecord(
        id="11111111-1111-4111-8111-111111111111",
        username="karuna",
        display_name="Karuna",
        pin_hash="hashed",
        active_vault_id=4
    )
    personal = VaultRecord(id="4", name="Personal", is_admin=False, vault_type="Individual")
    monkeypatch.setattr(
        "api.auth.recover_pin_with_recovery_code",
        lambda *_args, **_kwargs: (profile, personal)
    )
    monkeypatch.setattr("api.auth.set_active_vault", lambda *_args, **_kwargs: None)

    response = client.post(
        "/api/recover-pin",
        json={
            "username": "karuna",
            "recoveryCode": "ABCD-EFGH-IJKL",
            "newPin": "5678",
            "confirmPin": "5678"
        }
    )

    assert response.status_code == 200
    assert response.json()["userId"] == profile.id
    assert response.json()["vault"]["vaultType"] == "Individual"
    assert "5678" not in response.text
    assert "ABCD-EFGH-IJKL" not in response.text


def test_recover_pin_rejects_invalid_recovery_code(monkeypatch):
    client = build_client(monkeypatch)
    monkeypatch.setattr(
        "api.auth.recover_pin_with_recovery_code",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            __import__("db.identity", fromlist=["IdentityError"]).IdentityError("Recovery code is invalid.")
        )
    )

    response = client.post(
        "/api/recover-pin",
        json={
            "username": "karuna",
            "recoveryCode": "AAAA-BBBB-CCCC",
            "newPin": "5678",
            "confirmPin": "5678"
        }
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_RECOVERY_CODE"
