from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient


def build_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()

    from api.main import create_app

    return TestClient(create_app())


def make_token(monkeypatch, vault_id="7"):
    build_client(monkeypatch)
    from api.security import create_access_token

    token, _expires_at = create_access_token(
        SimpleNamespace(
            id=vault_id,
            name="Karuna",
            vault_type="Individual",
            is_admin=True
        )
    )
    return token


def dashboard_payload():
    return {
        "status": {
            "accounts": 1,
            "income_templates": 1,
            "commitments": 1,
            "has_vault_login": True,
            "has_cycle_setting": True,
            "has_savings_goal": True,
            "has_accounts": True,
            "has_income_templates": True,
            "has_commitments": True,
            "is_complete": True
        },
        "summary": {
            "month": 7,
            "year": 2026,
            "income": Decimal("45000.00"),
            "primary_account_name": "HDFC Bank",
            "primary_account_balance": Decimal("82300.50"),
            "available_cash": Decimal("82300.50"),
            "total_assets": Decimal("90000.00"),
            "total_liabilities": Decimal("1200.00"),
            "actual_savings": Decimal("16600.00"),
            "remaining_commitments": Decimal("17800.00"),
            "expenses": Decimal("28400.00"),
            "personal_expenses": Decimal("20000.00"),
            "shared_paid": Decimal("8400.00"),
            "shared_share": Decimal("7000.00"),
            "settlement_balance": Decimal("-1250.00"),
            "settlement_summary": {
                "label": "You Owe:",
                "amount": Decimal("1250.00"),
                "direction": "payable",
                "receivable": Decimal("0.00"),
                "payable": Decimal("1250.00"),
                "net": Decimal("-1250.00"),
                "items": [
                    {
                        "direction": "payable",
                        "amount": Decimal("1250.00"),
                        "created_at": datetime(2026, 7, 12, 8, 30)
                    }
                ]
            },
            "credit_card_due": Decimal("12400.00"),
            "safe_to_spend": Decimal("38240.00")
        },
        "category_spending": [
            ("Food & Dining", Decimal("8800.00")),
            ("Shopping", Decimal("6500.00"))
        ],
        "recent_activity": [
            [1, date(2026, 7, 12), "HDFC Bank", "Coffee", Decimal("220.00"), "Expense", "Starbucks"],
            [2, "2026-07-11", "HDFC Bank", "Netflix", Decimal("649.00"), "Expense", None],
            [3, "2026-07-10", "HDFC Bank", "Salary", Decimal("45000.00"), "Income", None],
            [4, "2026-07-09", "ICICI Bank", "Groceries", Decimal("1250.00"), "Expense", None],
            [5, "2026-07-08", "HDFC Bank", "Fuel", Decimal("1100.00"), "Expense", None],
            [6, "2026-07-07", "HDFC Bank", "Extra", Decimal("10.00"), "Expense", None],
        ]
    }


def cycle():
    return SimpleNamespace(
        id=10,
        start_iso="2026-07-10",
        end_iso="2026-08-09",
        display_name="10 Jul 2026 -> 09 Aug 2026",
        status="Current",
        days_completed=3,
        days_remaining=28,
        total_days=31,
        progress_percent=9
    )


def test_missing_token_is_rejected(monkeypatch):
    client = build_client(monkeypatch)

    response = client.get("/api/dashboard")

    assert response.status_code == 401


def test_invalid_token_is_rejected(monkeypatch):
    client = build_client(monkeypatch)

    response = client.get(
        "/api/dashboard",
        headers={"Authorization": "Bearer invalid-token"}
    )

    assert response.status_code == 401


def test_dashboard_scopes_to_jwt_vault_id(monkeypatch):
    client = build_client(monkeypatch)
    token = make_token(monkeypatch, vault_id="42")
    called = {}

    def fake_dashboard(vault_id):
        called["vault_id"] = vault_id
        return dashboard_payload()

    monkeypatch.setattr("api.dashboard.get_dashboard_page_data", fake_dashboard)
    monkeypatch.setattr("api.dashboard.get_current_cycle", lambda vault_id: cycle())

    response = client.get(
        "/api/dashboard",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert called["vault_id"] == 42


def test_client_cannot_select_another_vault_id(monkeypatch):
    client = build_client(monkeypatch)
    token = make_token(monkeypatch, vault_id="42")
    called = {}

    def fake_dashboard(vault_id):
        called["vault_id"] = vault_id
        return dashboard_payload()

    monkeypatch.setattr("api.dashboard.get_dashboard_page_data", fake_dashboard)
    monkeypatch.setattr("api.dashboard.get_current_cycle", lambda vault_id: cycle())

    response = client.get(
        "/api/dashboard?vault_id=99",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert called["vault_id"] == 42


def test_dashboard_adapter_serializes_decimal_and_dates(monkeypatch):
    from api.dashboard import adapt_dashboard_response
    from api.schemas import VaultContext

    response = adapt_dashboard_response(
        VaultContext(id="7", name="Karuna", isAdmin=True, vaultType="Individual"),
        dashboard_payload(),
        cycle()
    )
    body = response.model_dump(by_alias=True)

    assert body["data"]["safeToSpend"] == 38240.0
    assert body["data"]["recentActivity"][0]["date"] == "2026-07-12"
    assert body["data"]["settlement"]["items"][0]["created_at"] == "2026-07-12T08:30:00"


def test_recent_activity_contains_at_most_five_records(monkeypatch):
    client = build_client(monkeypatch)
    token = make_token(monkeypatch)

    monkeypatch.setattr("api.dashboard.get_dashboard_page_data", lambda vault_id: dashboard_payload())
    monkeypatch.setattr("api.dashboard.get_current_cycle", lambda vault_id: cycle())

    response = client.get(
        "/api/dashboard",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert len(response.json()["data"]["recentActivity"]) == 5


def test_dashboard_response_matches_mobile_contract(monkeypatch):
    client = build_client(monkeypatch)
    token = make_token(monkeypatch)

    monkeypatch.setattr("api.dashboard.get_dashboard_page_data", lambda vault_id: dashboard_payload())
    monkeypatch.setattr("api.dashboard.get_current_cycle", lambda vault_id: cycle())

    response = client.get(
        "/api/dashboard",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"generatedAt", "vault", "data"}
    assert set(body["vault"].keys()) == {"id", "name", "isAdmin", "vaultType"}
    assert {
        "cycle",
        "safeToSpend",
        "primaryAccount",
        "expensesThisCycle",
        "remainingCommitments",
        "creditCardDue",
        "settlement",
        "recentActivity",
        "spendingByCategory",
        "setup",
        "summary"
    }.issubset(body["data"].keys())
