import sqlite3
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from db.core import EXPENSE
from db.shared_expenses import (
    build_settlements_from_balances,
    get_personal_outstanding_settlements,
    get_settlement_summary,
    get_shared_balances_with_cursor,
)


@pytest.fixture
def two_shared_vaults_db(tmp_path):
    db_path = tmp_path / "two-shared-vaults.sqlite"
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
            is_admin INTEGER NOT NULL DEFAULT 0
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
            account_id INTEGER NOT NULL DEFAULT 1,
            category_id INTEGER NOT NULL DEFAULT 1,
            amount REAL NOT NULL,
            transaction_type TEXT NOT NULL,
            allocation_method TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            date TEXT NOT NULL,
            notes TEXT,
            transfer_group_id TEXT
        );

        CREATE TABLE transaction_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            participant_vault_id INTEGER NOT NULL,
            share_amount REAL NOT NULL,
            share_percentage REAL
        );

        CREATE TABLE profiles (
            id TEXT PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            pin_hash TEXT,
            active_vault_id INTEGER
        );

        CREATE TABLE vault_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner'
        );

        -- Vaults: Member A (1), Member B (2), Shared Vault A (10), Shared Vault B (20)
        INSERT INTO vaults (id, name, vault_type) VALUES
            (1, 'Member A Personal', 'Individual'),
            (2, 'Member B Personal', 'Individual'),
            (10, 'Regular Shared', 'Shared'),
            (20, 'Vacation Trip', 'Shared');

        -- Accounts
        INSERT INTO accounts (id, vault_id, name, type, opening_balance, is_primary) VALUES
            (1, 1, 'Checking A', 'Bank Account', 1000, 1),
            (2, 2, 'Checking B', 'Bank Account', 1000, 1);

        -- Shared Vault memberships
        INSERT INTO vault_shares (vault_id, shared_vault_id) VALUES
            (10, 1),
            (10, 2),
            (20, 1),
            (20, 2);

        INSERT INTO profiles (id, username, display_name, active_vault_id) VALUES
            ('00000000-0000-4000-8000-000000000001', 'user_a', 'Member A', 1),
            ('00000000-0000-4000-8000-000000000002', 'user_b', 'Member B', 2);

        INSERT INTO vault_members (vault_id, user_id, role) VALUES
            (1, '00000000-0000-4000-8000-000000000001', 'owner'),
            (2, '00000000-0000-4000-8000-000000000002', 'owner'),
            (10, '00000000-0000-4000-8000-000000000001', 'owner'),
            (10, '00000000-0000-4000-8000-000000000002', 'member'),
            (20, '00000000-0000-4000-8000-000000000001', 'owner'),
            (20, '00000000-0000-4000-8000-000000000002', 'member');
        """
    )
    connection.commit()
    connection.close()
    return db_path


def test_two_shared_vaults_remain_independent(two_shared_vaults_db, monkeypatch):
    monkeypatch.setattr("db.shared_expenses.get_connection", lambda: sqlite3.connect(two_shared_vaults_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: sqlite3.connect(two_shared_vaults_db))
    monkeypatch.setattr("db.core.get_connection", lambda: sqlite3.connect(two_shared_vaults_db))
    connection = sqlite3.connect(two_shared_vaults_db)

    # 1. Create ₹100 transaction in Shared Vault A (10), paid by Member B (2), split equally
    connection.execute(
        """
        INSERT INTO transactions (
            vault_id, beneficiary_vault_id, account_id, amount, transaction_type, date, notes
        ) VALUES (2, 10, 2, 100.0, ?, '2026-10-01', 'Groceries')
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
    connection.commit()

    # Verify Vault A balance
    balances_a = get_shared_balances_with_cursor(connection, 10, "2026-10-01", "2026-10-31")
    bal_a_dict = {b["vault_id"]: b["balance"] for b in balances_a}
    assert bal_a_dict[1] == -50.0  # Member A owes 50
    assert bal_a_dict[2] == 50.0   # Member B is owed 50

    settlements_a = build_settlements_from_balances(balances_a)
    assert len(settlements_a) == 1
    assert settlements_a[0]["from_vault_id"] == 1
    assert settlements_a[0]["to_vault_id"] == 2
    assert settlements_a[0]["amount"] == 50.0

    # Verify Vault B has zero balance at this point
    balances_b = get_shared_balances_with_cursor(connection, 20, "2026-10-01", "2026-10-31")
    bal_b_dict = {b["vault_id"]: b["balance"] for b in balances_b}
    assert bal_b_dict[1] == 0.0
    assert bal_b_dict[2] == 0.0

    # 2. Create ₹200 transaction in Shared Vault B (20), paid by Member A (1), split equally
    connection.execute(
        """
        INSERT INTO transactions (
            vault_id, beneficiary_vault_id, account_id, amount, transaction_type, date, notes
        ) VALUES (1, 20, 1, 200.0, ?, '2026-10-02', 'Flight tickets')
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

    # 3. Verify Vault A balance is UNCHANGED by Vault B transaction
    balances_a_after = get_shared_balances_with_cursor(connection, 10, "2026-10-01", "2026-10-31")
    bal_a_after_dict = {b["vault_id"]: b["balance"] for b in balances_a_after}
    assert bal_a_after_dict[1] == -50.0  # Member A still owes 50 in Vault A
    assert bal_a_after_dict[2] == 50.0   # Member B is still owed 50 in Vault A

    # 4. Verify Vault B balance reflects ONLY Vault B transaction
    balances_b_after = get_shared_balances_with_cursor(connection, 20, "2026-10-01", "2026-10-31")
    bal_b_after_dict = {b["vault_id"]: b["balance"] for b in balances_b_after}
    assert bal_b_after_dict[1] == 100.0  # Member A is owed 100 in Vault B
    assert bal_b_after_dict[2] == -100.0 # Member B owes 100 in Vault B

    # 5. Check per-vault settlements via get_personal_outstanding_settlements
    settlements_a_scoped = get_personal_outstanding_settlements(1, "2026-10-01", "2026-10-31", shared_vault_id=10)
    assert len(settlements_a_scoped) == 1
    assert settlements_a_scoped[0]["shared_vault_id"] == 10
    assert settlements_a_scoped[0]["direction"] == "payable"
    assert settlements_a_scoped[0]["amount"] == 50.0

    settlements_b_scoped = get_personal_outstanding_settlements(1, "2026-10-01", "2026-10-31", shared_vault_id=20)
    assert len(settlements_b_scoped) == 1
    assert settlements_b_scoped[0]["shared_vault_id"] == 20
    assert settlements_b_scoped[0]["direction"] == "receivable"
    assert settlements_b_scoped[0]["amount"] == 100.0

    # 6. Check per-vault summary via get_settlement_summary
    summary_a = get_settlement_summary(1, "2026-10-01", "2026-10-31", shared_vault_id=10)
    assert summary_a["direction"] == "payable"
    assert summary_a["amount"] == 50.0
    assert summary_a["payable"] == 50.0
    assert summary_a["receivable"] == 0.0

    summary_b = get_settlement_summary(1, "2026-10-01", "2026-10-31", shared_vault_id=20)
    assert summary_b["direction"] == "receivable"
    assert summary_b["amount"] == 100.0
    assert summary_b["payable"] == 0.0
    assert summary_b["receivable"] == 100.0

    connection.close()


def test_shared_settlements_api_respects_explicit_shared_vault_id(two_shared_vaults_db, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config
    get_config.cache_clear()
    monkeypatch.setattr("db.shared_expenses.get_connection", lambda: sqlite3.connect(two_shared_vaults_db))
    monkeypatch.setattr("db.identity.get_connection", lambda: sqlite3.connect(two_shared_vaults_db))
    monkeypatch.setattr("db.accounts.get_connection", lambda: sqlite3.connect(two_shared_vaults_db))
    monkeypatch.setattr("db.vaults.get_connection", lambda: sqlite3.connect(two_shared_vaults_db))
    monkeypatch.setattr("api.resources.get_connection", lambda: sqlite3.connect(two_shared_vaults_db))
    monkeypatch.setattr("db.core.get_connection", lambda: sqlite3.connect(two_shared_vaults_db))

    mock_cycle = SimpleNamespace(
        id=1,
        start_iso="2026-10-01",
        end_iso="2026-10-31",
        display_name="1 Oct 2026 - 31 Oct 2026",
        status="Current",
        days_completed=1,
        days_remaining=30,
        total_days=31,
        progress_percent=3
    )
    monkeypatch.setattr("api.shared.get_current_cycle", lambda vault_id: mock_cycle)

    connection = sqlite3.connect(two_shared_vaults_db)
    # Insert tx in Vault A (10)
    connection.execute(
        """
        INSERT INTO transactions (
            vault_id, beneficiary_vault_id, account_id, amount, transaction_type, date, notes
        ) VALUES (2, 10, 2, 100.0, ?, '2026-10-01', 'Groceries')
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
    # Insert tx in Vault B (20)
    connection.execute(
        """
        INSERT INTO transactions (
            vault_id, beneficiary_vault_id, account_id, amount, transaction_type, date, notes
        ) VALUES (1, 20, 1, 200.0, ?, '2026-10-02', 'Flight')
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
        SimpleNamespace(
            id="1",
            name="Member A",
            vault_type="Individual",
            is_admin=False
        ),
        user_id="00000000-0000-4000-8000-000000000001"
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Query Vault A settlement
    resp_a = client.get("/api/shared/settlements?sharedVaultId=10", headers=headers)
    assert resp_a.status_code == 200
    data_a = resp_a.json()["data"]
    assert data_a["direction"] == "payable"
    assert data_a["amount"] == 50.0
    assert len(data_a["items"]) == 1
    assert data_a["items"][0]["shared_vault_id"] == 10

    # Query Vault B settlement
    resp_b = client.get("/api/shared/settlements?sharedVaultId=20", headers=headers)
    assert resp_b.status_code == 200
    data_b = resp_b.json()["data"]
    assert data_b["direction"] == "receivable"
    assert data_b["amount"] == 100.0
    assert len(data_b["items"]) == 1
    assert data_b["items"][0]["shared_vault_id"] == 20
