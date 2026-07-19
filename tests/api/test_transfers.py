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
            name="Karuna",
            vault_type="Individual",
            is_admin=False
        )
    )
    return {"Authorization": f"Bearer {token}"}


def transfer_payload(date="2026-07-17"):
    return {
        "amount": 100.50,
        "date": date,
        "fromAccountId": 1,
        "notes": "Savings",
        "toAccountId": 2
    }


def test_create_transfer_rejects_invalid_calendar_date(monkeypatch):
    client = build_client(monkeypatch)

    response = client.post(
        "/api/transfers",
        headers=auth_header(),
        json=transfer_payload(date="2026-02-31")
    )

    assert response.status_code == 422


def test_transfer_filters_reject_invalid_calendar_dates(monkeypatch):
    client = build_client(monkeypatch)

    response = client.get(
        "/api/transfers?dateFrom=2026-02-31",
        headers=auth_header()
    )

    assert response.status_code == 422


def test_create_transfer_passes_iso_date_to_legacy_helper(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr("api.transfers.require_account", lambda account_id, vault_id: None)
    monkeypatch.setattr("api.transfers.add_transfer", lambda vault_id, from_id, to_id, transfer_date, amount, notes: observed.update({
        "amount": amount,
        "date": transfer_date,
        "from": from_id,
        "notes": notes,
        "to": to_id,
        "vault": vault_id
    }) or "group-1")
    monkeypatch.setattr("api.transfers.get_transfer_by_group", lambda transfer_group_id: ("group-1", 4, "2026-07-17", 1, 2, 100.50, "Savings"))

    response = client.post(
        "/api/transfers",
        headers=auth_header(),
        json=transfer_payload()
    )

    assert response.status_code == 200
    assert observed == {
        "amount": 100.50,
        "date": "2026-07-17",
        "from": 1,
        "notes": "Savings",
        "to": 2,
        "vault": 4
    }
