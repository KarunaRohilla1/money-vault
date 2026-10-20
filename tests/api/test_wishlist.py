from types import SimpleNamespace
from fastapi.testclient import TestClient
import pytest


def build_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()

    from api.main import create_app

    return TestClient(create_app())


def auth_header(vault_id="1", vault_type="Individual"):
    from api.security import create_access_token

    token, _ = create_access_token(
        SimpleNamespace(
            id=vault_id,
            name="Test Vault",
            vault_type=vault_type,
            is_admin=True,
            user_id="00000000-0000-4000-8000-000000000001"
        ),
        authenticated_vault=SimpleNamespace(
            id=vault_id,
            name="Test Vault",
            vault_type=vault_type,
            is_admin=True,
            user_id="00000000-0000-4000-8000-000000000001"
        )
    )
    return {"Authorization": f"Bearer {token}"}


def test_wishlist_get_and_complete_flow(monkeypatch):
    client = build_client(monkeypatch)
    headers = auth_header("1")

    # Mock DB functions
    fake_items = [
        (
            1, "MacBook Pro", "Tech", 200000.0, 50000.0, "2026-12-31", None, "",
            "", "notes", "HIGH", "", None, "2026-07-01", 1,
            "ACTIVE", None, None
        ),
        (
            2, "Mechanical Keyboard", "Tech", 12000.0, 0.0, None, None, "",
            "", "notes", "MEDIUM", "", None, "2026-07-02", 1,
            "COMPLETED", 11500.0, "2026-07-15"
        )
    ]
    fake_categories = [
        (1, 1, "Tech", "monitor", "purple", 0, 2)
    ]
    fake_summary = {
        "total_items": 2,
        "total_cost": 212000.0,
        "total_saved": 50000.0,
        "completed_items": 1,
        "completed_spent": 11500.0,
        "progress": 24
    }

    monkeypatch.setattr("api.wishlist.get_wishlist_categories", lambda vault_id: fake_categories)
    monkeypatch.setattr("api.wishlist.get_wishlist_items", lambda vault_id, search, account_id, date_filter, category, status: fake_items)
    monkeypatch.setattr("api.wishlist.get_wishlist_summary", lambda vault_id: fake_summary)

    response = client.get("/api/wishlist", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["items"][0]["status"] == "ACTIVE"
    assert data["items"][0]["purchasedAmount"] is None
    assert data["items"][1]["status"] == "COMPLETED"
    assert data["items"][1]["purchasedAmount"] == 11500.0
    assert data["items"][1]["purchasedDate"] == "2026-07-15"
    assert data["summary"]["completedItems"] == 1
    assert data["summary"]["completedSpent"] == 11500.0


def test_mark_item_as_completed(monkeypatch):
    client = build_client(monkeypatch)
    headers = auth_header("1")

    completed_call = {}

    monkeypatch.setattr("api.wishlist.require_wishlist_item", lambda item_id, vault_id: None)
    monkeypatch.setattr(
        "api.wishlist.complete_wishlist_item",
        lambda item_id, vault_id, purchased_amount=None, purchased_date=None: completed_call.update({
            "item_id": item_id,
            "vault_id": vault_id,
            "purchased_amount": purchased_amount,
            "purchased_date": purchased_date
        })
    )

    response = client.post(
        "/api/wishlist/items/42/complete",
        headers=headers,
        json={"purchasedAmount": 18500.0, "purchasedDate": "2026-10-18"}
    )
    assert response.status_code == 200
    assert completed_call["item_id"] == 42
    assert completed_call["vault_id"] == 1
    assert completed_call["purchased_amount"] == 18500.0
    assert completed_call["purchased_date"] == "2026-10-18"


def test_prevent_duplicate_completion(monkeypatch):
    client = build_client(monkeypatch)
    headers = auth_header("1")

    monkeypatch.setattr("api.wishlist.require_wishlist_item", lambda item_id, vault_id: None)

    def mock_complete(item_id, vault_id, purchased_amount=None, purchased_date=None):
        raise ValueError("Wishlist item is already completed.")

    monkeypatch.setattr("api.wishlist.complete_wishlist_item", mock_complete)

    response = client.post(
        "/api/wishlist/items/42/complete",
        headers=headers,
        json={"purchasedAmount": 18500.0, "purchasedDate": "2026-10-18"}
    )
    assert response.status_code == 400
    assert "already completed" in response.json()["message"].lower()


def test_reopen_completed_item(monkeypatch):
    client = build_client(monkeypatch)
    headers = auth_header("1")

    reopened_call = {}

    monkeypatch.setattr("api.wishlist.require_wishlist_item", lambda item_id, vault_id: None)
    monkeypatch.setattr(
        "api.wishlist.reopen_wishlist_item",
        lambda item_id, vault_id: reopened_call.update({"item_id": item_id, "vault_id": vault_id})
    )

    response = client.post("/api/wishlist/items/42/reopen", headers=headers)
    assert response.status_code == 200
    assert reopened_call["item_id"] == 42
    assert reopened_call["vault_id"] == 1


def test_reopen_already_active_item(monkeypatch):
    client = build_client(monkeypatch)
    headers = auth_header("1")

    monkeypatch.setattr("api.wishlist.require_wishlist_item", lambda item_id, vault_id: None)

    def mock_reopen(item_id, vault_id):
        raise ValueError("Wishlist item is already active.")

    monkeypatch.setattr("api.wishlist.reopen_wishlist_item", mock_reopen)

    response = client.post("/api/wishlist/items/42/reopen", headers=headers)
    assert response.status_code == 400
    assert "already active" in response.json()["message"].lower()
