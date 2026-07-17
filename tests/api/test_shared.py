from types import SimpleNamespace

from fastapi.testclient import TestClient


def build_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()

    from api.main import create_app

    return TestClient(create_app())


def auth_header():
    from api.security import create_access_token

    token, _expires_at = create_access_token(
        SimpleNamespace(
            id="4",
            name="Karuna",
            vault_type="Individual",
            is_admin=False
        )
    )
    return {"Authorization": f"Bearer {token}"}


def test_shared_expenses_wraps_legacy_page_data(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr(
        "api.shared.resolve_shared_vault_id",
        lambda vault_id, shared_vault_id=None: 40
    )
    monkeypatch.setattr(
        "api.shared.cycle_bounds",
        lambda shared_vault_id: ("2026-07-01", "2026-07-31")
    )
    monkeypatch.setattr(
        "api.shared.require_shared_participant",
        lambda payer_vault_id, shared_vault_id: None
    )

    def fake_page_data(shared_vault_id, start_date, end_date, category_id=None, paid_by_vault_id=None):
        observed.update(
            {
                "category_id": category_id,
                "end_date": end_date,
                "paid_by_vault_id": paid_by_vault_id,
                "shared_vault_id": shared_vault_id,
                "start_date": start_date
            }
        )
        return {
            "expenses": [],
            "summary": {"total_shared_spend": 0}
        }

    monkeypatch.setattr(
        "api.shared.get_shared_expenses_page_data",
        fake_page_data
    )

    response = client.get(
        "/api/shared/expenses?sharedVaultId=40&categoryId=8&paidByVaultId=4",
        headers=auth_header()
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "expenses": [],
            "summary": {"total_shared_spend": 0}
        }
    }
    assert observed == {
        "category_id": 8,
        "end_date": "2026-07-31",
        "paid_by_vault_id": 4,
        "shared_vault_id": 40,
        "start_date": "2026-07-01"
    }


def test_shared_bills_wraps_legacy_page_data(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr(
        "api.shared.resolve_shared_vault_id",
        lambda vault_id, shared_vault_id=None: 41
    )

    def fake_bills_page(shared_vault_id, year=None, month=None):
        observed.update(
            {
                "month": month,
                "shared_vault_id": shared_vault_id,
                "year": year
            }
        )
        return {
            "pending_bills": [],
            "summary": {"pending_count": 0}
        }

    monkeypatch.setattr(
        "api.shared.get_shared_bills_page_data",
        fake_bills_page
    )

    response = client.get(
        "/api/shared/bills?sharedVaultId=41&year=2026&month=7",
        headers=auth_header()
    )

    assert response.status_code == 200
    assert response.json()["data"]["summary"]["pending_count"] == 0
    assert observed == {
        "month": 7,
        "shared_vault_id": 41,
        "year": 2026
    }


def test_shared_bill_paid_validates_instance_and_participant(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr(
        "api.shared.require_shared_bill_instance",
        lambda instance_id, vault_id: observed.update({"instance_id": instance_id, "vault_id": vault_id})
    )
    monkeypatch.setattr(
        "api.shared.shared_vault_id_for_instance",
        lambda instance_id: 41
    )
    monkeypatch.setattr(
        "api.shared.require_shared_participant",
        lambda payer_vault_id, shared_vault_id: observed.update(
            {
                "payer_vault_id": payer_vault_id,
                "shared_vault_id": shared_vault_id
            }
        )
    )
    monkeypatch.setattr(
        "api.shared.mark_bill_paid",
        lambda instance_id, payer_vault_id, payment_date, notes="": observed.update(
            {
                "notes": notes,
                "paid_instance_id": instance_id,
                "payment_date": payment_date
            }
        )
    )

    response = client.post(
        "/api/shared/bills/instances/12/paid",
        headers=auth_header(),
        json={
            "notes": "Paid from primary",
            "payerVaultId": 4,
            "paymentDate": "2026-07-17"
        }
    )

    assert response.status_code == 200
    assert observed == {
        "instance_id": 12,
        "notes": "Paid from primary",
        "paid_instance_id": 12,
        "payer_vault_id": 4,
        "payment_date": "2026-07-17",
        "shared_vault_id": 41,
        "vault_id": 4
    }


def test_shared_bill_update_cannot_change_shared_vault(monkeypatch):
    client = build_client(monkeypatch)

    monkeypatch.setattr(
        "api.shared.require_shared_bill",
        lambda bill_id, vault_id: None
    )
    monkeypatch.setattr(
        "api.shared.shared_vault_id_for_bill",
        lambda bill_id: 41
    )

    response = client.put(
        "/api/shared/bills/5",
        headers=auth_header(),
        json={
            "amount": 1200,
            "dueDay": 10,
            "frequency": "Monthly",
            "isActive": True,
            "name": "Internet",
            "notes": "",
            "sharedVaultId": 42
        }
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Bill shared vault cannot be changed."
    }


def test_shared_routes_require_authentication(monkeypatch):
    client = build_client(monkeypatch)

    response = client.get("/api/shared/bills")

    assert response.status_code == 401
