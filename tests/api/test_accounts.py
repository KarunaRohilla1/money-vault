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
            name="Personal",
            vault_type="Individual",
            is_admin=True
        )
    )
    return {"Authorization": f"Bearer {token}"}


def account_payload(**overrides):
    payload = {
        "isPrimary": False,
        "name": "Salary",
        "openingBalance": 1000,
        "type": "Salary Account"
    }
    payload.update(overrides)
    return payload


def test_create_account_accepts_legacy_account_types(monkeypatch):
    client = build_client(monkeypatch)
    observed = []

    monkeypatch.setattr("api.accounts.account_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "api.accounts.add_account",
        lambda vault_id, name, account_type, opening_balance, is_primary: observed.append(
            {
                "account_type": account_type,
                "is_primary": is_primary,
                "name": name,
                "opening_balance": opening_balance,
                "vault_id": vault_id
            }
        )
    )

    for account_type in ("Salary Account", "Savings Account", "Credit Card", "Cash", "Other"):
        response = client.post(
            "/api/accounts",
            headers=auth_header(),
            json=account_payload(type=account_type)
        )

        assert response.status_code == 200

    assert [item["account_type"] for item in observed] == ["Salary Account", "Savings Account", "Credit Card", "Cash", "Other"]


def test_create_account_rejects_missing_account_type(monkeypatch):
    client = build_client(monkeypatch)

    response = client.post(
        "/api/accounts",
        headers=auth_header(),
        json={**account_payload(), "type": None}
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Account type is required."
    }


def test_create_account_rejects_empty_account_type(monkeypatch):
    client = build_client(monkeypatch)

    for value in ("", "   "):
        response = client.post(
            "/api/accounts",
            headers=auth_header(),
            json=account_payload(type=value)
        )

        assert response.status_code == 400
        assert response.json() == {
            "code": "VALIDATION_ERROR",
            "message": "Account type is required."
        }


def test_create_account_rejects_non_legacy_account_type(monkeypatch):
    client = build_client(monkeypatch)

    response = client.post(
        "/api/accounts",
        headers=auth_header(),
        json=account_payload(type="Bank")
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Choose a valid account type."
    }


def test_create_account_rejects_duplicate_name(monkeypatch):
    client = build_client(monkeypatch)

    monkeypatch.setattr("api.accounts.account_exists", lambda *_args, **_kwargs: True)

    response = client.post(
        "/api/accounts",
        headers=auth_header(),
        json=account_payload(name="salary")
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Account already exists."
    }


def test_non_credit_card_opening_balance_cannot_be_negative(monkeypatch):
    client = build_client(monkeypatch)

    response = client.post(
        "/api/accounts",
        headers=auth_header(),
        json=account_payload(openingBalance=-50, type="Salary Account")
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Opening balance cannot be negative."
    }


def test_opening_balance_zero_is_rejected(monkeypatch):
    client = build_client(monkeypatch)

    for value in (0, 0.0, -0.0, "0", "0.00", "-0"):
        response = client.post(
            "/api/accounts",
            headers=auth_header(),
            json=account_payload(openingBalance=value)
        )

        assert response.status_code == 400
        assert response.json() == {
            "code": "VALIDATION_ERROR",
            "message": "Opening balance must be greater than zero."
        }


def test_opening_balance_non_finite_values_are_rejected(monkeypatch):
    client = build_client(monkeypatch)

    for value in ("NaN", "Infinity", "-Infinity"):
        response = client.post(
            "/api/accounts",
            headers=auth_header(),
            json=account_payload(openingBalance=value)
        )

        assert response.status_code == 400
        assert response.json() == {
            "code": "VALIDATION_ERROR",
            "message": "Opening balance must be a number."
        }


def test_credit_card_opening_balance_can_be_negative(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr("api.accounts.account_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "api.accounts.add_account",
        lambda _vault_id, _name, _type, opening_balance, _is_primary: observed.update(
            {"opening_balance": opening_balance}
        )
    )

    response = client.post(
        "/api/accounts",
        headers=auth_header(),
        json=account_payload(openingBalance=-500, type="Credit Card")
    )

    assert response.status_code == 200
    assert observed["opening_balance"] == -500


def test_account_list_preserves_backend_order_and_balances(monkeypatch):
    client = build_client(monkeypatch)

    monkeypatch.setattr(
        "api.accounts.get_accounts_with_balances",
        lambda vault_id: [
            (2, "Primary Salary", "Salary Account", 1000, 1, 1250),
            (3, "Card", "Credit Card", -500, 0, -750),
            (1, "Savings", "Savings Account", 2000, 0, 2200)
        ]
    )

    response = client.get(
        "/api/accounts",
        headers=auth_header()
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "balance": 1250.0,
            "id": 2,
            "isPrimary": True,
            "name": "Primary Salary",
            "openingBalance": 1000.0,
            "type": "Salary Account"
        },
        {
            "balance": -750.0,
            "id": 3,
            "isPrimary": False,
            "name": "Card",
            "openingBalance": -500.0,
            "type": "Credit Card"
        },
        {
            "balance": 2200.0,
            "id": 1,
            "isPrimary": False,
            "name": "Savings",
            "openingBalance": 2000.0,
            "type": "Savings Account"
        }
    ]


def test_set_primary_requires_vault_account_and_updates_primary(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr("api.accounts.require_account", lambda account_id, vault_id: observed.update({"required": (account_id, vault_id)}))
    monkeypatch.setattr("api.accounts.set_primary_account", lambda account_id: observed.update({"primary": account_id}))

    response = client.post(
        "/api/accounts/8/primary",
        headers=auth_header()
    )

    assert response.status_code == 200
    assert observed == {
        "primary": 8,
        "required": (8, 4)
    }


def test_archive_account_with_transactions_uses_legacy_archive_behavior(monkeypatch):
    client = build_client(monkeypatch)
    archived = {}

    monkeypatch.setattr("api.accounts.get_account_by_id", lambda account_id: (account_id, "Salary", "Salary Account", 0, 1, 4))
    monkeypatch.setattr("api.accounts.archive_account", lambda account_id: archived.update({"account_id": account_id}))

    response = client.delete(
        "/api/accounts/7",
        headers=auth_header()
    )

    assert response.status_code == 200
    assert archived == {"account_id": 7}


def test_repeated_archive_for_inactive_same_vault_is_safe(monkeypatch):
    client = build_client(monkeypatch)
    archived = {}

    monkeypatch.setattr("api.accounts.get_account_by_id", lambda account_id: (account_id, "Salary", "Salary Account", 0, 0, 4))
    monkeypatch.setattr("api.accounts.archive_account", lambda account_id: archived.update({"account_id": account_id}))

    response = client.delete(
        "/api/accounts/7",
        headers=auth_header()
    )

    assert response.status_code == 200
    assert archived == {"account_id": 7}


def test_rejects_another_vault_account_archive(monkeypatch):
    client = build_client(monkeypatch)
    from api.resources import not_found

    monkeypatch.setattr("api.accounts.get_account_by_id", lambda account_id: (account_id, "Other", "Salary Account", 0, 1, 99))
    monkeypatch.setattr(
        "api.accounts.require_account",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(not_found())
    )

    response = client.delete(
        "/api/accounts/7",
        headers=auth_header()
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "Resource not found."
    }
