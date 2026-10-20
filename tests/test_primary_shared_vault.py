import sqlite3
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from db.core import EXPENSE
from db.vaults import delete_vault
from db.identity import (
    get_primary_shared_vault_for_personal,
    set_primary_shared_vault_for_personal,
    clear_primary_shared_vault_for_personal,
    leave_shared_vault_for_user,
)


class SqliteCursorWrapper:
    def __init__(self, raw_cursor):
        self._raw = raw_cursor
        self._custom_rows = None

    def execute(self, sql, params=(), **kwargs):
        if "WITH cycle AS" in sql:
            self._custom_rows = [(
                1, 1, 1, 1, 1, 1, 10, 2026, "HDFC Salary", 50000.0,
                0.0, 0.0, 0.0, 50000.0, 0.0, 50000.0, 0.0, 0.0, []
            )]
            return self

        self._custom_rows = None
        clean_sql = sql.replace("?::date", "?").replace("?::int", "?")
        self._raw.execute(clean_sql, params)
        return self

    def fetchone(self):
        if self._custom_rows is not None:
            return self._custom_rows[0]
        return self._raw.fetchone()

    def fetchall(self):
        if self._custom_rows is not None:
            return self._custom_rows
        return self._raw.fetchall()

    @property
    def lastrowid(self):
        return self._raw.lastrowid

    def close(self):
        self._raw.close()


class SqliteConnectionWrapper:
    def __init__(self, raw_conn):
        self._raw = raw_conn

    def cursor(self):
        return SqliteCursorWrapper(self._raw.cursor())

    def execute(self, sql, params=(), **kwargs):
        cursor = self.cursor()
        cursor.execute(sql, params, **kwargs)
        return cursor

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


def get_test_conn(db_path):
    return SqliteConnectionWrapper(sqlite3.connect(db_path))


@pytest.fixture
def primary_vault_test_db(tmp_path):
    db_path = tmp_path / "primary-shared-vault.sqlite"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE vaults (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            month_start_day INTEGER NOT NULL DEFAULT 1,
            financial_cycle_start_day INTEGER NOT NULL DEFAULT 1,
            monthly_savings_goal REAL NOT NULL DEFAULT 0,
            vault_type TEXT NOT NULL,
            primary_shared_vault_id INTEGER REFERENCES vaults(id),
            show_shared_balances_on_dashboard INTEGER NOT NULL DEFAULT 1,
            is_admin INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE personal_shared_vault_preferences (
            personal_vault_id INTEGER NOT NULL,
            shared_vault_id INTEGER NOT NULL,
            include_in_safe_to_spend INTEGER NOT NULL DEFAULT 1,
            show_on_dashboard INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (personal_vault_id, shared_vault_id)
        );

        CREATE TABLE profiles (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            display_name TEXT,
            pin_hash TEXT,
            active_vault_id INTEGER REFERENCES vaults(id),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE vault_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL REFERENCES vaults(id),
            user_id TEXT NOT NULL REFERENCES profiles(id),
            role TEXT NOT NULL DEFAULT 'member'
        );

        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            opening_balance REAL NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_primary INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER,
            name TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '🏷️',
            parent_category TEXT,
            category_type TEXT NOT NULL DEFAULT 'Expense',
            is_system INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE vault_shares (
            vault_id INTEGER NOT NULL,
            shared_vault_id INTEGER NOT NULL
        );

        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            beneficiary_vault_id INTEGER NOT NULL,
            account_id INTEGER,
            category_id INTEGER,
            amount REAL NOT NULL,
            transaction_type TEXT NOT NULL,
            date TEXT NOT NULL,
            notes TEXT,
            transfer_group_id TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE transaction_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            participant_vault_id INTEGER NOT NULL,
            share_amount REAL NOT NULL,
            share_percentage REAL
        );

        CREATE TABLE commitments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            due_day INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE obligation_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commitment_id INTEGER NOT NULL,
            month INTEGER NOT NULL,
            year INTEGER NOT NULL,
            actual_amount REAL,
            status TEXT DEFAULT 'PENDING',
            notes TEXT,
            transaction_id INTEGER
        );

        CREATE TABLE income_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            due_day INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE income_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            income_template_id INTEGER NOT NULL,
            month INTEGER NOT NULL,
            year INTEGER NOT NULL,
            actual_amount REAL,
            status TEXT DEFAULT 'PENDING',
            notes TEXT,
            transaction_id INTEGER
        );

        CREATE TABLE shared_bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shared_vault_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            due_day INTEGER NOT NULL,
            category_id INTEGER,
            frequency TEXT NOT NULL DEFAULT 'Monthly',
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE shared_bill_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shared_vault_id INTEGER NOT NULL,
            month INTEGER NOT NULL,
            year INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active',
            total_amount REAL NOT NULL DEFAULT 0,
            paid_amount REAL NOT NULL DEFAULT 0,
            remaining_amount REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE shared_bill_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id INTEGER NOT NULL,
            bill_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            due_date TEXT NOT NULL,
            frequency TEXT NOT NULL,
            category_id INTEGER,
            status TEXT NOT NULL DEFAULT 'Pending',
            payer_vault_id INTEGER,
            payment_date TEXT,
            payment_notes TEXT,
            transaction_id INTEGER
        );

        CREATE TABLE shared_bill_instance_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_instance_id INTEGER NOT NULL,
            participant_vault_id INTEGER NOT NULL,
            expected_amount REAL NOT NULL,
            expected_percentage REAL NOT NULL
        );

        CREATE TABLE financial_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE cycle_contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id INTEGER NOT NULL,
            participant_vault_id INTEGER NOT NULL,
            income REAL NOT NULL DEFAULT 0,
            income_ratio REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE monthly_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            month INTEGER NOT NULL,
            year INTEGER NOT NULL,
            status TEXT NOT NULL
        );

        CREATE TABLE wishlist_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            name TEXT NOT NULL
        );

        CREATE TABLE wishlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            name TEXT NOT NULL
        );

        -- Users
        INSERT INTO profiles (id, username, display_name, pin_hash, active_vault_id)
        VALUES ('00000000-0000-4000-8000-000000000001', 'usera', 'User A', 'hash', 1);

        INSERT INTO profiles (id, username, display_name, pin_hash, active_vault_id)
        VALUES ('00000000-0000-4000-8000-000000000002', 'userb', 'User B', 'hash', 2);

        INSERT INTO profiles (id, username, display_name, pin_hash, active_vault_id)
        VALUES ('00000000-0000-4000-8000-000000000003', 'userc', 'User C', 'hash', 3);

        -- Vaults:
        -- Vault 1: User A's Personal Vault
        -- Vault 2: User B's Personal Vault
        -- Vault 3: User C's Personal Vault
        -- Vault 10: Shared Vault A (members: User A, User B)
        -- Vault 20: Shared Vault B (members: User A, User B)
        -- Vault 30: Unrelated Shared Vault C (members: User C only)
        INSERT INTO vaults (id, name, vault_type, is_admin, primary_shared_vault_id)
        VALUES
            (1, 'Personal A', 'Individual', 1, NULL),
            (2, 'Personal B', 'Individual', 1, NULL),
            (3, 'Personal C', 'Individual', 1, NULL),
            (10, 'Regular Shared', 'Shared', 0, NULL),
            (20, 'Vacation', 'Shared', 0, NULL),
            (30, 'Unrelated Shared', 'Shared', 0, NULL);

        -- Vault memberships
        INSERT INTO vault_members (vault_id, user_id, role)
        VALUES
            (1, '00000000-0000-4000-8000-000000000001', 'owner'),
            (2, '00000000-0000-4000-8000-000000000002', 'owner'),
            (3, '00000000-0000-4000-8000-000000000003', 'owner'),
            (10, '00000000-0000-4000-8000-000000000001', 'owner'),
            (10, '00000000-0000-4000-8000-000000000002', 'member'),
            (20, '00000000-0000-4000-8000-000000000001', 'owner'),
            (20, '00000000-0000-4000-8000-000000000002', 'member'),
            (30, '00000000-0000-4000-8000-000000000003', 'owner');

        -- Vault shares (vault_id = Shared, shared_vault_id = Personal)
        INSERT INTO vault_shares (vault_id, shared_vault_id)
        VALUES
            (10, 1),
            (10, 2),
            (20, 1),
            (20, 2),
            (30, 3);

        -- Accounts
        INSERT INTO accounts (id, vault_id, name, type, opening_balance, is_active, is_primary)
        VALUES
            (1, 1, 'HDFC Salary', 'Salary Account', 50000.0, 1, 1),
            (2, 2, 'ICICI Savings', 'Savings Account', 30000.0, 1, 1),
            (3, 3, 'Axis Bank', 'Salary Account', 20000.0, 1, 1);
        """
    )
    connection.commit()
    connection.close()
    return db_path


def test_1_user_has_no_primary_shared_vault_returns_null(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    token, _ = create_access_token(
        SimpleNamespace(id="1", name="Personal A", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"configured": False, "sharedVault": None}


def test_2_user_selects_shared_vault_a_succeeds(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    token, _ = create_access_token(
        SimpleNamespace(id="1", name="Personal A", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put(
        "/api/vaults/personal/primary-shared-vault",
        headers=headers,
        json={"sharedVaultId": 10}
    )
    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "sharedVault": {"id": 10, "name": "Regular Shared"}
    }

    # Verify subsequent GET returns Vault 10
    get_resp = client.get("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json() == {
        "configured": True,
        "sharedVault": {"id": 10, "name": "Regular Shared"}
    }


def test_3_user_selects_shared_vault_b_changes_primary(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    token, _ = create_access_token(
        SimpleNamespace(id="1", name="Personal A", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Set to Vault A first
    client.put("/api/vaults/personal/primary-shared-vault", headers=headers, json={"sharedVaultId": 10})

    # Switch to Vault B
    response = client.put(
        "/api/vaults/personal/primary-shared-vault",
        headers=headers,
        json={"sharedVaultId": 20}
    )
    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "sharedVault": {"id": 20, "name": "Vacation"}
    }

    get_resp = client.get("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert get_resp.json()["sharedVault"]["id"] == 20
    assert get_resp.json()["sharedVault"]["name"] == "Vacation"


def test_4_user_clears_primary_succeeds(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    token, _ = create_access_token(
        SimpleNamespace(id="1", name="Personal A", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Set to Vault A
    client.put("/api/vaults/personal/primary-shared-vault", headers=headers, json={"sharedVaultId": 10})

    # Clear primary
    response = client.delete("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"configured": False, "sharedVault": None}

    # Subsequent GET returns null
    get_resp = client.get("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert get_resp.json() == {"configured": False, "sharedVault": None}


def test_5_user_cannot_select_shared_vault_they_are_not_member_of(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    token, _ = create_access_token(
        SimpleNamespace(id="1", name="Personal A", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Vault 30 is owned by User C only
    response = client.put(
        "/api/vaults/personal/primary-shared-vault",
        headers=headers,
        json={"sharedVaultId": 30}
    )
    assert response.status_code == 400
    assert "not a member" in response.text or "not connected" in response.text


def test_6_user_cannot_select_individual_personal_vault(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    token, _ = create_access_token(
        SimpleNamespace(id="1", name="Personal A", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Try setting another personal vault (Vault 2)
    response = client.put(
        "/api/vaults/personal/primary-shared-vault",
        headers=headers,
        json={"sharedVaultId": 2}
    )
    assert response.status_code == 400
    assert "Only shared vaults" in response.text


def test_7_and_8_personal_dashboard_settlement_uses_only_primary_and_no_cancellation(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.dashboard.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.shared_expenses.get_connection", lambda: get_test_conn(primary_vault_test_db))

    mock_cycle = SimpleNamespace(
        id=1,
        start_iso="2026-10-01",
        end_iso="2026-10-31",
        start_month=10,
        start_year=2026,
        display_name="1 Oct 2026 - 31 Oct 2026",
        status="Current",
        days_completed=1,
        days_remaining=30,
        total_days=31,
        progress_percent=3
    )
    monkeypatch.setattr("db.dashboard.get_current_cycle", lambda vault_id: mock_cycle)
    monkeypatch.setattr("api.dashboard.get_current_cycle", lambda vault_id: mock_cycle)

    connection = sqlite3.connect(primary_vault_test_db)
    # Vault A (10): User B paid 100, split 50/50 -> User A owes 50
    connection.execute(
        """
        INSERT INTO transactions (
            vault_id, beneficiary_vault_id, account_id, amount, transaction_type, date, notes
        ) VALUES (2, 10, 2, 100.0, ?, '2026-10-05', 'Groceries Vault A')
        """,
        (EXPENSE,)
    )
    tx1_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.executemany(
        """
        INSERT INTO transaction_shares (transaction_id, participant_vault_id, share_amount, share_percentage)
        VALUES (?, ?, ?, ?)
        """,
        [
            (tx1_id, 1, 50.0, 50.0),
            (tx1_id, 2, 50.0, 50.0),
        ]
    )

    # Vault B (20): User A paid 200, split 50/50 -> User A is owed 100
    connection.execute(
        """
        INSERT INTO transactions (
            vault_id, beneficiary_vault_id, account_id, amount, transaction_type, date, notes
        ) VALUES (1, 20, 1, 200.0, ?, '2026-10-06', 'Hotel Vault B')
        """,
        (EXPENSE,)
    )
    tx2_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.executemany(
        """
        INSERT INTO transaction_shares (transaction_id, participant_vault_id, share_amount, share_percentage)
        VALUES (?, ?, ?, ?)
        """,
        [
            (tx2_id, 1, 100.0, 50.0),
            (tx2_id, 2, 100.0, 50.0),
        ]
    )
    connection.commit()
    connection.close()

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    token, _ = create_access_token(
        SimpleNamespace(id="1", name="Personal A", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers = {"Authorization": f"Bearer {token}"}

    dash_resp = client.get("/api/dashboard", headers=headers)
    assert dash_resp.status_code == 200
    data = dash_resp.json()["data"]
    settlement = data["settlement"]
    # Default inclusion includes both vaults independently: payable 50 + receivable 100
    assert settlement["payable"] == 50.0
    assert settlement["receivable"] == 100.0
    assert {item["shared_vault_id"] for item in settlement["items"]} == {10, 20}
    breakdown = {item["key"]: item for item in data["safeToSpendBreakdown"]["items"]}
    assert breakdown["you_owe"]["amount"] == 50.0
    assert breakdown["you_are_owed"]["amount"] == 100.0
    assert data["safeToSpend"] == 50050.0
    cards = data["sharedVaultBalances"]
    assert [card["id"] for card in cards] == [10, 20]
    assert next(card for card in cards if card["id"] == 10)["payable"] == 50.0
    assert next(card for card in cards if card["id"] == 20)["receivable"] == 100.0
    assert data["showSharedBalancesOnDashboard"] is True

    # Primary selection does not change Safe to Spend inclusion
    client.put("/api/vaults/personal/primary-shared-vault", headers=headers, json={"sharedVaultId": 10})
    after_primary = client.get("/api/dashboard", headers=headers).json()["data"]
    assert after_primary["safeToSpend"] == 50050.0
    assert after_primary["settlement"]["payable"] == 50.0
    assert after_primary["settlement"]["receivable"] == 100.0
    assert [card["id"] for card in after_primary["sharedVaultBalances"]] == [10, 20]

    # Exclude Vacation from Safe to Spend: only Regular Shared payable remains
    exclude = client.put(
        "/api/vaults/personal/shared-vaults/20/safe-to-spend",
        headers=headers,
        json={"includeInSafeToSpend": False}
    )
    assert exclude.status_code == 200
    assert exclude.json()["includeInSafeToSpend"] is False
    after_exclude = client.get("/api/dashboard", headers=headers).json()["data"]
    assert after_exclude["settlement"]["payable"] == 50.0
    assert after_exclude["settlement"]["receivable"] == 0.0
    assert after_exclude["safeToSpend"] == 49950.0
    assert [card["id"] for card in after_exclude["sharedVaultBalances"]] == [10, 20]
    assert next(card for card in after_exclude["sharedVaultBalances"] if card["id"] == 20)["receivable"] == 100.0

    # Exclude both: Safe to Spend ignores shared balances, carousel still shows both
    client.put("/api/vaults/personal/shared-vaults/10/safe-to-spend", headers=headers, json={"includeInSafeToSpend": False})
    after_none = client.get("/api/dashboard", headers=headers).json()["data"]
    assert after_none["settlement"]["payable"] == 0.0
    assert after_none["settlement"]["receivable"] == 0.0
    assert after_none["safeToSpend"] == 50000.0
    assert [card["id"] for card in after_none["sharedVaultBalances"]] == [10, 20]

    # Re-include Regular Shared for Safe to Spend, then hide Vacation on the dashboard only
    client.put("/api/vaults/personal/shared-vaults/10/safe-to-spend", headers=headers, json={"includeInSafeToSpend": True})
    hide_vacation = client.put(
        "/api/vaults/personal/shared-vaults/20/dashboard",
        headers=headers,
        json={"showOnDashboard": False}
    )
    assert hide_vacation.status_code == 200
    assert hide_vacation.json()["showOnDashboard"] is False
    assert hide_vacation.json()["includeInSafeToSpend"] is False
    hidden = client.get("/api/dashboard", headers=headers).json()["data"]
    assert [card["id"] for card in hidden["sharedVaultBalances"] if card.get("showOnDashboard", True)] == [10]
    assert hidden["safeToSpend"] == 49950.0
    assert hidden["settlement"]["payable"] == 50.0
    assert hidden["settlement"]["receivable"] == 0.0

    show_vacation = client.put(
        "/api/vaults/personal/shared-vaults/20/dashboard",
        headers=headers,
        json={"showOnDashboard": True}
    )
    assert show_vacation.status_code == 200
    restored = client.get("/api/dashboard", headers=headers).json()["data"]
    assert [card["id"] for card in restored["sharedVaultBalances"] if card.get("showOnDashboard", True)] == [10, 20]
    assert restored["safeToSpend"] == 49950.0
    assert next(card for card in restored["sharedVaultBalances"] if card["id"] == 20)["receivable"] == 100.0

    primary_after_hide = client.get("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert primary_after_hide.json()["configured"] is True
    assert primary_after_hide.json()["sharedVault"]["id"] == 10


def test_9_leaving_or_deleting_primary_shared_vault_clears_invalid_reference(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    token_b, _ = create_access_token(
        SimpleNamespace(id="2", name="Personal B", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000002"
    )
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B sets Vault 10 as primary
    client.put("/api/vaults/personal/primary-shared-vault", headers=headers_b, json={"sharedVaultId": 10})
    resp = client.get("/api/vaults/personal/primary-shared-vault", headers=headers_b)
    assert resp.json()["configured"] is True

    # User B leaves Vault 10
    leave_shared_vault_for_user("00000000-0000-4000-8000-000000000002", 10)

    # Primary reference should now be cleared
    resp_after = client.get("/api/vaults/personal/primary-shared-vault", headers=headers_b)
    assert resp_after.json() == {"configured": False, "sharedVault": None}

    # Now test deleting a shared vault clears any personal vaults referencing it
    token_a, _ = create_access_token(
        SimpleNamespace(id="1", name="Personal A", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers_a = {"Authorization": f"Bearer {token_a}"}
    client.put("/api/vaults/personal/primary-shared-vault", headers=headers_a, json={"sharedVaultId": 20})
    assert client.get("/api/vaults/personal/primary-shared-vault", headers=headers_a).json()["configured"] is True

    # Vault 20 is deleted
    delete_vault(20)

    # Primary reference for User A should now be cleared
    resp_a_after = client.get("/api/vaults/personal/primary-shared-vault", headers=headers_a)
    assert resp_a_after.json() == {"configured": False, "sharedVault": None}


def test_10_existing_users_with_no_configured_primary_shared_vault_continue_to_work(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.dashboard.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.shared_expenses.get_connection", lambda: get_test_conn(primary_vault_test_db))

    mock_cycle = SimpleNamespace(
        id=1,
        start_iso="2026-10-01",
        end_iso="2026-10-31",
        start_month=10,
        start_year=2026,
        display_name="1 Oct 2026 - 31 Oct 2026",
        status="Current",
        days_completed=1,
        days_remaining=30,
        total_days=31,
        progress_percent=3
    )
    monkeypatch.setattr("db.dashboard.get_current_cycle", lambda vault_id: mock_cycle)
    monkeypatch.setattr("api.dashboard.get_current_cycle", lambda vault_id: mock_cycle)

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    # User C has no primary shared vault configured
    token, _ = create_access_token(
        SimpleNamespace(id="3", name="Personal C", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000003"
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Primary endpoint works
    prim_resp = client.get("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert prim_resp.status_code == 200
    assert prim_resp.json() == {"configured": False, "sharedVault": None}

    # Dashboard works
    dash_resp = client.get("/api/dashboard", headers=headers)
    assert dash_resp.status_code == 200
    assert dash_resp.json()["data"]["settlement"]["amount"] == 0.0


def test_11_user_in_shared_vault_session_can_get_and_set_primary_shared_vault(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.core.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))

    from api.main import create_app
    from api.security import create_access_token

    client = TestClient(create_app())
    # User A is in active Shared Vault session (active = Vault 10, authenticated = Vault 1)
    token, _ = create_access_token(
        SimpleNamespace(id="10", name="Regular Shared", vault_type="Shared", is_admin=False),
        authenticated_vault=SimpleNamespace(id="1", name="Personal A", vault_type="Individual", is_admin=True),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Should be able to GET primary shared vault for their personal vault
    get_resp = client.get("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json() == {"configured": False, "sharedVault": None}

    # Should be able to SET primary shared vault to Vault 20
    put_resp = client.put("/api/vaults/personal/primary-shared-vault", headers=headers, json={"sharedVaultId": 20})
    assert put_resp.status_code == 200
    assert put_resp.json() == {
        "configured": True,
        "sharedVault": {"id": 20, "name": "Vacation"}
    }

    # Verify GET returns Vault 20
    get_resp2 = client.get("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert get_resp2.status_code == 200
    assert get_resp2.json()["sharedVault"]["id"] == 20

    # Should be able to CLEAR
    del_resp = client.delete("/api/vaults/personal/primary-shared-vault", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json() == {"configured": False, "sharedVault": None}
