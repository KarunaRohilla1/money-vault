from types import SimpleNamespace

from fastapi.testclient import TestClient


def build_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()

    from api.main import create_app

    return TestClient(create_app())


def auth_header(monkeypatch, vault_id="4", vault_type="Individual"):
    build_client(monkeypatch)
    from api.security import create_access_token

    token, _expires_at = create_access_token(
        SimpleNamespace(
            id=vault_id,
            name="Karuna",
            vault_type=vault_type,
            is_admin=False
        )
    )
    return {"Authorization": f"Bearer {token}"}


def cycle(start="2026-07-10", end="2026-08-09", status="Current"):
    return SimpleNamespace(
        start_iso=start,
        end_iso=end,
        start_date=__import__("datetime").date.fromisoformat(start),
        end_date=__import__("datetime").date.fromisoformat(end),
        start_month=7,
        start_year=2026,
        status=status,
    )


def summary():
    return {
        "income": 45000,
        "cash_outflow": 30000,
        "net_personal_cost": 28400,
        "household_spending": 0,
        "spent": 28400,
        "saved": 16600,
        "investments": 5000,
        "settlements": -1250,
        "outstanding_receivables": 0,
        "outstanding_payables": 1250,
        "net_outstanding": -1250,
        "settlements_completed": 1000,
        "settlements_pending": 1250,
        "shared_expenses_paid": 8400,
        "shared_expenses_received": 500,
        "net_cash_flow": 15000,
        "transactions": 8,
        "transfers": 2,
        "largest_expense": ("Rent", 15000),
        "most_used_category": ("Food", 3),
        "most_used_account": ("HDFC", 5),
    }


def install_report_fixtures(monkeypatch, shared=False):
    selected = cycle()
    options = [
        {"key": "2026-06-10", "label": "Previous", "cycle": cycle("2026-06-10", "2026-07-09", "Completed")},
        {"key": "2026-07-10", "label": "Current", "cycle": selected},
    ]
    called = {}

    monkeypatch.setattr("api.reports.get_current_cycle", lambda vault_id: selected)
    monkeypatch.setattr("api.reports.get_cycle_for_date", lambda vault_id, start: selected)
    monkeypatch.setattr("api.reports.build_cycle_navigation_options", lambda vault_id: options)
    monkeypatch.setattr("api.reports.report_period_context", lambda vault_id, selected_cycle: {
        "start_date": selected.start_date,
        "end_date": selected.end_date,
        "cycle_windows": ((selected.start_iso, selected.end_iso, 7, 2026),),
    })
    monkeypatch.setattr("api.reports.is_shared_vault", lambda vault_id: shared)

    def fake_summary(vault_id, *_args):
        called["vault_id"] = vault_id
        payload = summary()
        if shared:
            payload.update(
                {
                    "household_spending": 1200,
                    "income": 0,
                    "cash_outflow": 1200,
                    "spent": 1200,
                    "saved": 0,
                    "net_cash_flow": -1200,
                    "settlements": 200,
                    "settlements_pending": 200,
                }
            )
        return payload

    monkeypatch.setattr("api.reports.get_report_summary", fake_summary)
    monkeypatch.setattr("api.reports.get_cash_outflow_category_breakdown", lambda *_args: [("label", "Food", 18000), ("label", "Bills", 12000)])
    monkeypatch.setattr("api.reports.get_net_personal_category_breakdown", lambda *_args: [("label", "Food", 16400), ("label", "Bills", 12000)])
    monkeypatch.setattr("api.reports.get_monthly_trend", lambda *_args: [
        {
            "Cycle": "10 Jul - 09 Aug",
            "Cash Outflow": 30000,
            "Net Personal Cost": 28400,
            "Household Spending": 0,
            "Income": 45000,
            "Savings": 16600,
        }
    ])
    return called


def test_reports_reject_missing_token(monkeypatch):
    client = build_client(monkeypatch)

    response = client.get("/api/reports")

    assert response.status_code == 401


def test_reports_scope_to_authenticated_vault(monkeypatch):
    client = build_client(monkeypatch)
    called = install_report_fixtures(monkeypatch)

    response = client.get("/api/reports", headers=auth_header(monkeypatch, vault_id="42"))

    assert response.status_code == 200
    assert called["vault_id"] == 42
    body = response.json()
    assert body["vault"]["id"] == "42"
    assert body["filters"]["period"] == "cycle"
    assert body["filters"]["cycleStart"] == "2026-07-10"


def test_reports_category_totals_reconcile_with_cash_outflow(monkeypatch):
    client = build_client(monkeypatch)
    install_report_fixtures(monkeypatch)

    response = client.get("/api/reports", headers=auth_header(monkeypatch))

    assert response.status_code == 200
    body = response.json()
    cash_total = sum(row["amount"] for row in body["data"]["cashOutflowByCategory"])
    assert cash_total == body["data"]["summary"]["cash_outflow"]
    assert body["data"]["summary"]["net_cash_flow"] == 15000


def test_reports_reject_unknown_cycle(monkeypatch):
    client = build_client(monkeypatch)
    install_report_fixtures(monkeypatch)

    response = client.get(
        "/api/reports?cycleStart=2026-01-01",
        headers=auth_header(monkeypatch)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_shared_reports_do_not_include_personal_net_categories(monkeypatch):
    client = build_client(monkeypatch)
    install_report_fixtures(monkeypatch, shared=True)

    response = client.get("/api/reports", headers=auth_header(monkeypatch, vault_type="Shared"))

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["netPersonalCostByCategory"] == []
    assert body["data"]["sharedInsights"] == []
    assert body["data"]["overview"][0]["title"] == "Household Spending"
