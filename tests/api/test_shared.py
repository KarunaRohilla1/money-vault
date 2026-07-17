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


def test_shared_settlements_exposes_legacy_settlement_accounts(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr(
        "api.shared.get_current_cycle",
        lambda vault_id: SimpleNamespace(start_iso="2026-07-01", end_iso="2026-07-31")
    )

    def fake_settlement_summary(vault_id, start_date, end_date):
        observed.update(
            {
                "end_date": end_date,
                "start_date": start_date,
                "vault_id": vault_id
            }
        )
        return {
            "amount": 1200,
            "direction": "payable",
            "items": [
                {
                    "amount": 1200,
                    "counterparty_name": "Aman",
                    "counterparty_vault_id": 5,
                    "direction": "payable",
                    "from_name": "Karuna",
                    "from_vault_id": 4,
                    "label": "You Owe:",
                    "shared_vault_id": 41,
                    "shared_vault_name": "Home",
                    "to_name": "Aman",
                    "to_vault_id": 5
                }
            ],
            "label": "You Owe:",
            "net": -1200,
            "payable": 1200,
            "receivable": 0
        }

    monkeypatch.setattr(
        "api.shared.get_settlement_summary",
        fake_settlement_summary
    )
    monkeypatch.setattr(
        "api.shared.get_accounts_with_balances",
        lambda vault_id: [
            (vault_id * 10, "Primary", "Bank", 0, 1, 2500)
        ]
    )

    response = client.get(
        "/api/shared/settlements",
        headers=auth_header()
    )

    body = response.json()
    assert response.status_code == 200
    assert observed == {
        "end_date": "2026-07-31",
        "start_date": "2026-07-01",
        "vault_id": 4
    }
    assert body["data"]["items"][0]["from_accounts"][0] == {
        "balance": 2500.0,
        "id": 40,
        "is_primary": True,
        "name": "Primary",
        "type": "Bank"
    }
    assert body["data"]["items"][0]["to_accounts"][0]["id"] == 50


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


def test_shared_settlement_uses_legacy_settle_function(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr(
        "api.shared.require_shared_vault",
        lambda shared_vault_id, vault_id: observed.update(
            {
                "authorized_shared_vault_id": shared_vault_id,
                "authorized_vault_id": vault_id
            }
        )
    )
    monkeypatch.setattr(
        "api.shared.require_shared_participant",
        lambda participant_vault_id, shared_vault_id: observed.setdefault(
            "participants",
            []
        ).append((participant_vault_id, shared_vault_id))
    )
    monkeypatch.setattr(
        "api.shared.settle_outstanding_settlement",
        lambda shared_vault_id, from_vault_id, from_account_id, to_vault_id, to_account_id, amount, settlement_date: observed.update(
            {
                "amount": amount,
                "from_account_id": from_account_id,
                "from_vault_id": from_vault_id,
                "settlement_date": settlement_date,
                "settled_shared_vault_id": shared_vault_id,
                "to_account_id": to_account_id,
                "to_vault_id": to_vault_id
            }
        )
    )

    response = client.post(
        "/api/shared/settlements",
        headers=auth_header(),
        json={
            "amount": 1200,
            "fromAccountId": 31,
            "fromVaultId": 4,
            "settlementDate": "2026-07-17",
            "sharedVaultId": 41,
            "toAccountId": 52,
            "toVaultId": 5
        }
    )

    assert response.status_code == 200
    assert observed == {
        "amount": 1200.0,
        "authorized_shared_vault_id": 41,
        "authorized_vault_id": 4,
        "from_account_id": 31,
        "from_vault_id": 4,
        "participants": [
            (4, 41),
            (5, 41)
        ],
        "settled_shared_vault_id": 41,
        "settlement_date": "2026-07-17",
        "to_account_id": 52,
        "to_vault_id": 5
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
