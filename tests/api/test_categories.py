from types import SimpleNamespace
from fastapi.testclient import TestClient


def build_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()

    from api.main import create_app

    return TestClient(create_app())


def auth_header(vault_id="4", vault_type="Individual", authenticated_vault_id=None):
    from api.security import create_access_token

    token, _expires_at = create_access_token(
        SimpleNamespace(
            id=vault_id,
            name="Test Vault",
            vault_type=vault_type,
            is_admin=True,
            user_id="00000000-0000-4000-8000-000000000001"
        ),
        authenticated_vault=SimpleNamespace(
            id=authenticated_vault_id or vault_id,
            name="Personal Vault",
            vault_type="Individual",
            is_admin=True,
            user_id="00000000-0000-4000-8000-000000000001"
        )
    )
    return {"Authorization": f"Bearer {token}"}


def test_shared_vault_uses_same_vault_id_for_list_and_mutations(monkeypatch):
    client = build_client(monkeypatch)
    observed_vault_ids = {}

    monkeypatch.setattr(
        "api.categories.get_categories",
        lambda vault_id: observed_vault_ids.setdefault("list", []).append(vault_id) or []
    )
    monkeypatch.setattr(
        "api.categories.add_category",
        lambda vault_id, name, emoji, category_type: observed_vault_ids.setdefault("create", []).append(vault_id) or True
    )
    monkeypatch.setattr(
        "api.categories.require_category",
        lambda category_id, vault_id: observed_vault_ids.setdefault("require", []).append((category_id, vault_id))
    )
    monkeypatch.setattr(
        "api.categories.update_category",
        lambda category_id, name, emoji, category_type: True
    )
    monkeypatch.setattr(
        "api.categories.get_category_transaction_count",
        lambda category_id: 0
    )
    monkeypatch.setattr(
        "api.categories.delete_category",
        lambda category_id: True
    )

    headers = auth_header(vault_id="10", vault_type="Shared", authenticated_vault_id="2")

    # 1. List categories
    resp = client.get("/api/categories", headers=headers)
    assert resp.status_code == 200
    assert observed_vault_ids["list"] == [10]

    # 2. Create category
    resp = client.post("/api/categories", json={"name": "Snacks", "emoji": "🍿", "categoryType": "Expense"}, headers=headers)
    assert resp.status_code == 200
    assert observed_vault_ids["create"] == [10]

    # 3. Update category
    resp = client.put("/api/categories/99", json={"name": "Snacks 2", "emoji": "🍿", "categoryType": "Expense"}, headers=headers)
    assert resp.status_code == 200
    assert (99, 10) in observed_vault_ids["require"]

    # 4. Delete category
    resp = client.delete("/api/categories/99", headers=headers)
    assert resp.status_code == 200
    assert (99, 10) in observed_vault_ids["require"]


def test_categories_same_name_independent_in_different_vaults(monkeypatch):
    """Test that categories in different vaults are isolated and can share names."""
    from db.categories import add_category

    # Simulated in-memory database
    store = []

    class MockCursor:
        def __init__(self):
            self.last_query = None

        def execute(self, sql, params=()):
            self.last_query = (sql, params)
            if "SELECT id" in sql:
                vault_id, name = params
                matches = [
                    (row["id"],)
                    for row in store
                    if (row["vault_id"] == vault_id or row["is_system"] == 1)
                    and row["name"].lower() == name.lower()
                    and row["is_active"] == 1
                ]
                self._results = matches
            elif "INSERT INTO categories" in sql:
                vault_id, name, emoji, category_type = params
                new_id = len(store) + 1
                store.append({
                    "id": new_id,
                    "vault_id": vault_id,
                    "name": name,
                    "emoji": emoji,
                    "category_type": category_type,
                    "is_system": 0,
                    "is_active": 1
                })
                self._results = []
            return self

        def fetchone(self):
            return self._results[0] if getattr(self, "_results", None) else None

        def fetchall(self):
            return getattr(self, "_results", [])

        def close(self):
            pass

    class MockConnection:
        def execute(self, sql, params=(), **kwargs):
            cur = MockCursor()
            return cur.execute(sql, params)

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("db.categories.get_connection", lambda: MockConnection())

    # Add "Custom Cat" to Vault 1
    assert add_category(vault_id=1, name="Custom Cat", emoji="🏷️", category_type="Expense") is True

    # Adding "Custom Cat" again to Vault 1 should raise ValueError
    try:
        add_category(vault_id=1, name="Custom Cat", emoji="🏷️", category_type="Expense")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Category already exists" in str(e)

    # Adding "Custom Cat" to Vault 2 MUST succeed independently
    assert add_category(vault_id=2, name="Custom Cat", emoji="🏷️", category_type="Expense") is True

    # Check store has 2 categories: one for Vault 1, one for Vault 2
    vault_1_cats = [c for c in store if c["vault_id"] == 1]
    vault_2_cats = [c for c in store if c["vault_id"] == 2]
    assert len(vault_1_cats) == 1
    assert len(vault_2_cats) == 1
    assert vault_1_cats[0]["name"] == "Custom Cat"
    assert vault_2_cats[0]["name"] == "Custom Cat"
