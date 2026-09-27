from types import SimpleNamespace

from fastapi.testclient import TestClient

from db.identity import hash_app_pin, validate_app_pin, validate_username, verify_app_pin


def build_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()
    from api.main import create_app

    return TestClient(create_app())

def test_app_pin_hash_is_not_sha256_and_verifies():
    hashed = hash_app_pin("1234")
    assert hashed != "1234"
    assert "1234" not in hashed
    assert verify_app_pin("1234", hashed) is True
    assert verify_app_pin("5678", hashed) is False


def test_app_pin_length_rules():
    try:
        validate_app_pin("12")
        raised = False
    except ValueError:
        raised = True
    assert raised is True


def test_pin_endpoints_require_user_identity(monkeypatch):
    from api.dependencies import get_authenticated_vault
    from api.schemas import VaultContext

    client = build_client(monkeypatch)
    client.app.dependency_overrides[get_authenticated_vault] = lambda: VaultContext(
        id="4",
        name="Personal",
        isAdmin=False,
        vaultType="Individual",
        role="member",
        userId=None,
    )

    set_response = client.post(
        "/api/me/pin",
        json={"pin": "1234", "confirmPin": "1234"}
    )
    change_response = client.patch(
        "/api/me/pin",
        json={"currentPin": "1234", "newPin": "5678", "confirmPin": "5678"}
    )
    profile_response = client.patch(
        "/api/me",
        json={"displayName": "Karuna"}
    )

    assert set_response.status_code == 401
    assert change_response.status_code == 401
    assert profile_response.status_code == 401
    assert "1234" not in set_response.text
    assert "5678" not in change_response.text


def test_username_must_differ_from_display_name():
    from db.identity import validate_display_name

    try:
        validate_display_name("Karuna", "karuna")
        raised = False
    except ValueError:
        raised = True
    assert raised is True
    assert validate_username("Karuna_1") == "karuna_1"


def test_person_display_name_sql_uses_profile_then_vault_name():
    from db.identity import person_display_name_sql

    sql = person_display_name_sql("v.id", "v.name")
    assert "p.display_name" in sql
    assert "p.username" in sql
    assert "vault_members" in sql
    assert "v.name" in sql
