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


def shared_payload(participants=None):
    return {
        "accountId": 1,
        "allocationMethod": "Equal",
        "amount": 1200,
        "beneficiaryVaultId": 40,
        "categoryId": 2,
        "date": "2026-07-17",
        "notes": "Shared dinner",
        "participantVaults": participants or [4, 5],
        "transactionType": "Expense"
    }


def test_shared_transaction_requires_authenticated_vault_participant(monkeypatch):
    client = build_client(monkeypatch)

    monkeypatch.setattr(
        "api.transactions.require_shared_vault",
        lambda shared_vault_id, vault_id: None
    )
    monkeypatch.setattr(
        "api.transactions.require_shared_participant",
        lambda participant_vault_id, shared_vault_id: None
    )

    response = client.post(
        "/api/transactions",
        headers=auth_header(),
        json=shared_payload(participants=[5, 6])
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Shared transactions must include the authenticated vault as a participant."
    }


def test_shared_transaction_validates_shared_vault_and_participants(monkeypatch):
    client = build_client(monkeypatch)
    observed = {
        "participants": []
    }

    monkeypatch.setattr(
        "api.transactions.require_account",
        lambda account_id, vault_id: None
    )
    monkeypatch.setattr(
        "api.transactions.require_category",
        lambda category_id, vault_id: None
    )
    monkeypatch.setattr(
        "api.transactions.require_shared_vault",
        lambda shared_vault_id, vault_id: observed.update(
            {
                "shared_vault_id": shared_vault_id,
                "vault_id": vault_id
            }
        )
    )
    monkeypatch.setattr(
        "api.transactions.require_shared_participant",
        lambda participant_vault_id, shared_vault_id: observed["participants"].append(
            (participant_vault_id, shared_vault_id)
        )
    )
    monkeypatch.setattr(
        "api.transactions.add_transaction",
        lambda *args, **kwargs: 99
    )
    monkeypatch.setattr(
        "api.transactions.get_transaction_by_id",
        lambda transaction_id: (transaction_id, 1, 2, "2026-07-17", 1200, "Expense", "Shared dinner", 40, "Equal")
    )

    response = client.post(
        "/api/transactions",
        headers=auth_header(),
        json=shared_payload()
    )

    assert response.status_code == 200
    assert observed == {
        "participants": [
            (4, 40),
            (5, 40)
        ],
        "shared_vault_id": 40,
        "vault_id": 4
    }
    assert response.json()["beneficiaryVaultId"] == 40
