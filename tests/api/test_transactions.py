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
        "api.transactions.get_shared_vault_participants",
        lambda shared_vault_id: [(4, "Karuna"), (5, "Asfar")]
    )

    def fake_add_transaction(*args, **kwargs):
        observed["participant_vaults"] = kwargs["participant_vaults"]
        return 99

    monkeypatch.setattr(
        "api.transactions.add_transaction",
        fake_add_transaction
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
        "participant_vaults": [(4, "Karuna"), (5, "Asfar")],
        "vault_id": 4
    }
    assert response.json()["beneficiaryVaultId"] == 40



def test_active_shared_vault_transaction_uses_authenticated_personal_vault(monkeypatch):
    client = build_client(monkeypatch)
    observed = {
        "participants": []
    }

    from api.security import create_access_token

    active_shared = SimpleNamespace(
        id="40",
        name="Shared",
        vault_type="Shared",
        is_admin=False
    )
    authenticated_personal = SimpleNamespace(
        id="4",
        name="Karuna",
        vault_type="Individual",
        is_admin=False
    )
    token, _expires_at = create_access_token(active_shared, authenticated_personal)

    monkeypatch.setattr(
        "api.transactions.require_account",
        lambda account_id, vault_id: observed.update({"account_vault_id": vault_id})
    )
    monkeypatch.setattr(
        "api.transactions.require_category",
        lambda category_id, vault_id: observed.update({"category_vault_id": vault_id})
    )
    monkeypatch.setattr(
        "api.transactions.require_shared_vault",
        lambda shared_vault_id, vault_id: observed.update(
            {
                "shared_vault_id": shared_vault_id,
                "authorized_vault_id": vault_id
            }
        )
    )
    monkeypatch.setattr(
        "api.transactions.require_shared_participant",
        lambda participant_vault_id, shared_vault_id: observed["participants"].append(
            (participant_vault_id, shared_vault_id)
        )
    )

    def fake_add_transaction(vault_id, *args, **kwargs):
        observed["created_vault_id"] = vault_id
        observed["beneficiary_vault_id"] = kwargs["beneficiary_vault_id"]
        observed["participant_vaults"] = kwargs["participant_vaults"]
        return 101

    monkeypatch.setattr(
        "api.transactions.get_shared_vault_participants",
        lambda shared_vault_id: [(4, "Karuna"), (5, "Asfar")]
    )
    monkeypatch.setattr("api.transactions.add_transaction", fake_add_transaction)
    monkeypatch.setattr(
        "api.transactions.get_transaction_by_id",
        lambda transaction_id: (transaction_id, 1, 2, "2026-07-17", 1200, "Expense", "Shared dinner", 40, "Equal")
    )

    response = client.post(
        "/api/transactions",
        headers={"Authorization": f"Bearer {token}"},
        json=shared_payload(participants=[4, 5])
    )

    assert response.status_code == 200
    assert observed == {
        "account_vault_id": 4,
        "authorized_vault_id": 4,
        "beneficiary_vault_id": 40,
        "category_vault_id": 4,
        "created_vault_id": 4,
        "participant_vaults": [(4, "Karuna"), (5, "Asfar")],
        "participants": [
            (4, 40),
            (5, 40)
        ],
        "shared_vault_id": 40
    }
    assert response.json()["beneficiaryVaultId"] == 40



def test_shared_transaction_normalizes_allocation_keys_for_legacy_split_helpers(monkeypatch):
    client = build_client(monkeypatch)
    observed = {
        "participants": []
    }

    monkeypatch.setattr("api.transactions.require_account", lambda account_id, vault_id: None)
    monkeypatch.setattr("api.transactions.require_category", lambda category_id, vault_id: None)
    monkeypatch.setattr("api.transactions.require_shared_vault", lambda shared_vault_id, vault_id: None)
    monkeypatch.setattr(
        "api.transactions.require_shared_participant",
        lambda participant_vault_id, shared_vault_id: observed["participants"].append((participant_vault_id, shared_vault_id))
    )
    monkeypatch.setattr(
        "api.transactions.get_shared_vault_participants",
        lambda shared_vault_id: [(4, "Karuna"), (5, "Asfar")]
    )

    def fake_add_transaction(*args, **kwargs):
        observed["participant_vaults"] = kwargs["participant_vaults"]
        observed["percentage_allocations"] = kwargs["percentage_allocations"]
        observed["amount_allocations"] = kwargs["amount_allocations"]
        return 102

    monkeypatch.setattr("api.transactions.add_transaction", fake_add_transaction)
    monkeypatch.setattr(
        "api.transactions.get_transaction_by_id",
        lambda transaction_id: (transaction_id, 1, 2, "2026-07-17", 1200, "Expense", "Shared dinner", 40, "Percentage")
    )

    response = client.post(
        "/api/transactions",
        headers=auth_header(),
        json={
            **shared_payload(participants=[4, 5]),
            "allocationMethod": "Percentage",
            "percentageAllocations": {"4": 60, "5": 40},
            "amountAllocations": {"4": 720, "5": 480}
        }
    )

    assert response.status_code == 200
    assert observed["participant_vaults"] == [(4, "Karuna"), (5, "Asfar")]
    assert observed["percentage_allocations"] == {4: 60, 5: 40}
    assert observed["amount_allocations"] == {4: 720, 5: 480}



def history_rows():
    return [
        (4, "2026-07-10", "HDFC Salary A/c", "Food & Dining", "coffee", 220, "Expense", "Starbucks Coffee", None, 42880, None, 1),
        (3, "2026-07-10", "HDFC Salary A/c", "Dining Out", "utensils", 670, "Expense", "Domino's Pizza", None, 43100, "Household", 1),
        (2, "2026-07-09", "HDFC Salary A/c", "Income", "briefcase", 45000, "Income", "Salary", None, 43770, None, 1),
        (10, "2026-07-08", "HDFC Salary A/c", "Transfer Out", "", 2500, "Transfer Out", "Savings", "transfer-1", 5120, None, 1),
        (11, "2026-07-08", "Savings A/c", "Transfer In", "", 2500, "Transfer In", "Savings", "transfer-1", 5680, None, 2)
    ]


def test_transaction_history_forwards_filters_and_groups_sections(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    def fake_history(vault_id, **kwargs):
        kwargs["vault_id"] = vault_id
        observed.update(kwargs)
        return history_rows()

    monkeypatch.setattr("api.transactions.get_transaction_history", fake_history)

    response = client.get(
        "/api/transactions?month=2026-07&search=coffee&transactionType=Expense",
        headers=auth_header()
    )

    assert response.status_code == 200
    assert observed["vault_id"] == 4
    assert observed["month"] == "2026-07"
    assert observed["search"] == "coffee"
    assert observed["transaction_type"] == "Expense"
    payload = response.json()
    assert payload["month"] == "2026-07"
    assert payload["transactionCount"] == 4
    assert payload["sections"][0]["date"] == "2026-07-10"
    assert payload["sections"][0]["spent"] == 890
    assert payload["sections"][0]["transactions"][0]["runningBalance"] == 42880


def test_transaction_history_collapses_transfer_pairs(monkeypatch):
    client = build_client(monkeypatch)
    monkeypatch.setattr("api.transactions.get_transaction_history", lambda vault_id, **kwargs: history_rows())

    response = client.get(
        "/api/transactions?transactionType=Transfer",
        headers=auth_header()
    )

    assert response.status_code == 200
    payload = response.json()
    transfer_items = [
        item
        for section in payload["sections"]
        for item in section["transactions"]
        if item["type"] == "transfer"
    ]
    assert len(transfer_items) == 1
    assert transfer_items[0]["id"] == "transfer-1"
    assert transfer_items[0]["transferMetadata"] == {
        "fromAccount": "HDFC Salary A/c",
        "toAccount": "Savings A/c",
        "fromRunningBalance": 5120,
        "toRunningBalance": 5680
    }


def test_transaction_history_marks_shared_rows(monkeypatch):
    client = build_client(monkeypatch)
    monkeypatch.setattr("api.transactions.get_transaction_history", lambda vault_id, **kwargs: history_rows())

    response = client.get("/api/transactions", headers=auth_header())

    assert response.status_code == 200
    shared_items = [
        item
        for section in response.json()["sections"]
        for item in section["transactions"]
        if item["shared"]
    ]
    assert len(shared_items) == 1
    assert shared_items[0]["sharedVaultName"] == "Household"



def test_transaction_month_range_endpoint(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    def fake_month_range(vault_id):
        observed["vault_id"] = vault_id
        return ("2020-01", "2026-07")

    monkeypatch.setattr("api.transactions.get_transaction_month_range", fake_month_range)

    response = client.get("/api/transactions/month-range", headers=auth_header())

    assert response.status_code == 200
    assert observed["vault_id"] == 4
    assert response.json() == {
        "oldestMonth": "2020-01",
        "latestMonth": "2026-07"
    }


def test_transaction_history_forwards_advanced_filters(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    def fake_history(vault_id, **kwargs):
        observed["vault_id"] = vault_id
        observed.update(kwargs)
        return []

    monkeypatch.setattr("api.transactions.get_transaction_history", fake_history)

    response = client.get(
        "/api/transactions?account=HDFC&category=Food&dateFrom=2026-07-01&dateTo=2026-07-31&sharedOnly=true&amountMin=100&amountMax=900&sortBy=Amount+High",
        headers=auth_header()
    )

    assert response.status_code == 200
    assert observed == {
        "account": "HDFC",
        "amount_max": 900.0,
        "amount_min": 100.0,
        "category": "Food",
        "date_from": "2026-07-01",
        "date_to": "2026-07-31",
        "month": None,
        "search": None,
        "shared_only": True,
        "sort_by": "Amount High",
        "transaction_type": "All",
        "vault_id": 4
    }
