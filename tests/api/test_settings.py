from types import SimpleNamespace

from fastapi.testclient import TestClient


def build_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()

    from api.main import create_app

    return TestClient(create_app())


def auth_header(vault_id="4"):
    from api.security import create_access_token

    token, _expires_at = create_access_token(
        SimpleNamespace(
            id=vault_id,
            name="Personal vault",
            vault_type="Individual",
            is_admin=True
        )
    )
    return {"Authorization": f"Bearer {token}"}


def vault_row(name="Personal vault"):
    return (4, name, 1, 1, "Individual")


def test_update_settings_persists_onboarding_values(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr("api.settings.get_vault_by_id", lambda vault_id: vault_row("Old vault"))
    monkeypatch.setattr("api.settings.get_vault_financial_settings", lambda vault_id: (10, 2500))
    monkeypatch.setattr("api.settings.accessible_vaults_for", lambda current: [api_vault(current)])

    def fake_update_vault(vault_id, name, **kwargs):
        observed["vault_id"] = vault_id
        observed["name"] = name
        observed.update(kwargs)

    monkeypatch.setattr("api.settings.update_vault", fake_update_vault)

    response = client.patch(
        "/api/settings",
        headers=auth_header(),
        json={
            "vaultName": "New personal vault",
            "cycleStartDay": 10,
            "monthlySavingsGoal": 2500
        }
    )

    assert response.status_code == 200
    assert observed == {
        "vault_id": 4,
        "name": "New personal vault",
        "month_start_day": 10,
        "monthly_savings_goal": 2500
    }


def test_update_settings_allows_cycle_day_31(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr("api.settings.get_vault_by_id", lambda vault_id: vault_row())
    monkeypatch.setattr("api.settings.get_vault_financial_settings", lambda vault_id: (31, 0))
    monkeypatch.setattr("api.settings.accessible_vaults_for", lambda current: [api_vault(current)])
    monkeypatch.setattr(
        "api.settings.update_vault",
        lambda vault_id, name, **kwargs: observed.update(kwargs)
    )

    response = client.patch(
        "/api/settings",
        headers=auth_header(),
        json={
            "cycleStartDay": 31
        }
    )

    assert response.status_code == 200
    assert observed["month_start_day"] == 31


def test_update_settings_returns_safe_validation_error(monkeypatch):
    client = build_client(monkeypatch)

    monkeypatch.setattr("api.settings.get_vault_by_id", lambda vault_id: vault_row())

    def fake_update_vault(*_args, **_kwargs):
        raise ValueError("Vault name is required.")

    monkeypatch.setattr("api.settings.update_vault", fake_update_vault)

    response = client.patch(
        "/api/settings",
        headers=auth_header(),
        json={
            "vaultName": ""
        }
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Vault name is required."
    }


def api_vault(row):
    from api.settings import adapt_vault

    return adapt_vault(row)
