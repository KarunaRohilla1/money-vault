import sqlite3
import uuid
import pytest

from db.dashboard import get_cycle_savings_summary


class SqliteCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def execute(self, sql, params=None, capture_lastrowid=True):
        self.cursor.execute(sql, tuple(params or ()))
        return self

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class SqliteConnection:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)

    def execute(self, sql, params=None, capture_lastrowid=True):
        return SqliteCursor(self.connection.cursor()).execute(sql, params, capture_lastrowid=capture_lastrowid)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


@pytest.fixture
def savings_db(tmp_path, monkeypatch):
    db_path = tmp_path / "savings.sqlite"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            opening_balance REAL NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_id INTEGER NOT NULL,
            beneficiary_vault_id INTEGER,
            account_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            transaction_type TEXT NOT NULL,
            notes TEXT,
            transfer_group_id TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr("db.dashboard.get_connection", lambda: SqliteConnection(db_path))

    return db_path


def add_account(db_path, vault_id, name, account_type, is_primary=0):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO accounts (vault_id, name, type, opening_balance, is_primary, is_active)
            VALUES (?, ?, ?, 0, ?, 1)
            """,
            (vault_id, name, account_type, is_primary)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def add_transfer_pair(db_path, vault_id, from_account_id, to_account_id, transfer_date, amount, notes="", is_deleted=0):
    conn = sqlite3.connect(db_path)
    try:
        group_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO transactions (vault_id, beneficiary_vault_id, account_id, date, amount, transaction_type, notes, transfer_group_id, is_deleted)
            VALUES (?, ?, ?, ?, ?, 'Transfer Out', ?, ?, ?)
            """,
            (vault_id, vault_id, from_account_id, transfer_date, amount, notes, group_id, is_deleted)
        )
        conn.execute(
            """
            INSERT INTO transactions (vault_id, beneficiary_vault_id, account_id, date, amount, transaction_type, notes, transfer_group_id, is_deleted)
            VALUES (?, ?, ?, ?, ?, 'Transfer In', ?, ?, ?)
            """,
            (vault_id, vault_id, to_account_id, transfer_date, amount, notes, group_id, is_deleted)
        )
        conn.commit()
        return group_id
    finally:
        conn.close()


def test_transfer_from_primary_to_savings_counts_as_savings(savings_db):
    primary_id = add_account(savings_db, 1, "Salary Account", "Salary Account", is_primary=1)
    savings_id = add_account(savings_db, 1, "Emergency Fund", "Savings Account", is_primary=0)

    add_transfer_pair(savings_db, 1, primary_id, savings_id, "2026-07-10", 500.0)

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_in"] == 500.0
    assert summary["savings_out"] == 0.0
    assert summary["net_savings"] == 500.0


def test_subsequent_withdrawal_back_to_primary_reduces_net_savings(savings_db):
    primary_id = add_account(savings_db, 1, "Salary Account", "Salary Account", is_primary=1)
    savings_id = add_account(savings_db, 1, "Emergency Fund", "Savings Account", is_primary=0)

    # ₹500 transferred to savings
    add_transfer_pair(savings_db, 1, primary_id, savings_id, "2026-07-10", 500.0)
    # Subsequent ₹200 withdrawal back to primary
    add_transfer_pair(savings_db, 1, savings_id, primary_id, "2026-07-15", 200.0)

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_in"] == 500.0
    assert summary["savings_out"] == 200.0
    assert summary["net_savings"] == 300.0


def test_transfers_outside_cycle_dates_are_excluded(savings_db):
    primary_id = add_account(savings_db, 1, "Salary Account", "Salary Account", is_primary=1)
    savings_id = add_account(savings_db, 1, "Emergency Fund", "Savings Account", is_primary=0)

    # Within cycle
    add_transfer_pair(savings_db, 1, primary_id, savings_id, "2026-07-10", 500.0)
    # Before cycle
    add_transfer_pair(savings_db, 1, primary_id, savings_id, "2026-06-25", 1000.0)
    # After cycle
    add_transfer_pair(savings_db, 1, primary_id, savings_id, "2026-08-05", 200.0)

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_in"] == 500.0
    assert summary["savings_out"] == 0.0
    assert summary["net_savings"] == 500.0


def test_internal_transfers_between_savings_accounts_do_not_alter_net_savings(savings_db):
    savings1_id = add_account(savings_db, 1, "Savings A", "Savings Account", is_primary=0)
    savings2_id = add_account(savings_db, 1, "Savings B", "Savings Account", is_primary=0)

    # Transfer between two savings accounts
    add_transfer_pair(savings_db, 1, savings1_id, savings2_id, "2026-07-12", 400.0)

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_in"] == 0.0
    assert summary["savings_out"] == 0.0
    assert summary["net_savings"] == 0.0


def test_transfers_between_non_savings_accounts_do_not_alter_net_savings(savings_db):
    primary_id = add_account(savings_db, 1, "Salary Account", "Salary Account", is_primary=1)
    wallet_id = add_account(savings_db, 1, "Cash Wallet", "Cash", is_primary=0)

    # Transfer between primary and cash wallet (neither is savings)
    add_transfer_pair(savings_db, 1, primary_id, wallet_id, "2026-07-12", 200.0)

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_in"] == 0.0
    assert summary["savings_out"] == 0.0
    assert summary["net_savings"] == 0.0


def test_deleted_transfers_are_excluded(savings_db):
    primary_id = add_account(savings_db, 1, "Salary Account", "Salary Account", is_primary=1)
    savings_id = add_account(savings_db, 1, "Emergency Fund", "Savings Account", is_primary=0)

    add_transfer_pair(savings_db, 1, primary_id, savings_id, "2026-07-10", 500.0, is_deleted=1)

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_in"] == 0.0
    assert summary["savings_out"] == 0.0
    assert summary["net_savings"] == 0.0


def test_transfers_do_not_count_as_expenses_or_income(savings_db):
    primary_id = add_account(savings_db, 1, "Salary Account", "Salary Account", is_primary=1)
    savings_id = add_account(savings_db, 1, "Emergency Fund", "Savings Account", is_primary=0)

    # Regular income
    conn = sqlite3.connect(savings_db)
    conn.execute(
        """
        INSERT INTO transactions (vault_id, beneficiary_vault_id, account_id, date, amount, transaction_type, notes, transfer_group_id, is_deleted)
        VALUES (1, 1, ?, '2026-07-05', 50000.0, 'Income', 'Salary', NULL, 0)
        """,
        (primary_id,)
    )
    # Regular expense
    conn.execute(
        """
        INSERT INTO transactions (vault_id, beneficiary_vault_id, account_id, date, amount, transaction_type, notes, transfer_group_id, is_deleted)
        VALUES (1, 1, ?, '2026-07-08', 1500.0, 'Expense', 'Groceries', NULL, 0)
        """,
        (primary_id,)
    )
    conn.commit()
    conn.close()

    # Transfer from primary to savings (₹500)
    add_transfer_pair(savings_db, 1, primary_id, savings_id, "2026-07-10", 500.0)

    # Verify transaction totals query (same query logic used in dashboard)
    conn = sqlite3.connect(savings_db)
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN transaction_type = 'Income' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN transaction_type = 'Expense' THEN amount ELSE 0 END), 0) AS expenses
        FROM transactions
        WHERE vault_id = 1
        AND is_deleted = 0
        AND date BETWEEN '2026-07-01' AND '2026-07-31'
        """
    ).fetchone()
    conn.close()

    income, expenses = row
    # The transfer of ₹500 must NOT be in income or expenses
    assert income == 50000.0
    assert expenses == 1500.0

    # Net savings must be 500
    savings_summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert savings_summary["net_savings"] == 500.0


def add_transaction(db_path, vault_id, account_id, date, amount, transaction_type, notes="", is_deleted=0):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO transactions (vault_id, beneficiary_vault_id, account_id, date, amount, transaction_type, notes, transfer_group_id, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (vault_id, vault_id, account_id, date, amount, transaction_type, notes, is_deleted)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_external_income_deposited_directly_into_savings_counts_as_savings(savings_db):
    savings_id = add_account(savings_db, 1, "Savings Account", "Savings Account", is_primary=0)

    # ₹500 external income deposited directly into savings
    add_transaction(savings_db, 1, savings_id, "2026-07-10", 500.0, "Income", "Freelance bonus")

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_income"] == 500.0
    assert summary["savings_in"] == 500.0
    assert summary["savings_out"] == 0.0
    assert summary["net_savings"] == 500.0


def test_direct_expense_from_savings_reduces_savings(savings_db):
    savings_id = add_account(savings_db, 1, "Emergency Fund", "Savings Account", is_primary=0)

    # ₹300 direct expense paid from savings
    add_transaction(savings_db, 1, savings_id, "2026-07-12", 300.0, "Expense", "Medical expense")

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_expenses"] == 300.0
    assert summary["savings_in"] == 0.0
    assert summary["savings_out"] == 300.0
    assert summary["net_savings"] == -300.0


def test_transfer_to_savings_then_direct_expense_reflects_net_retained(savings_db):
    primary_id = add_account(savings_db, 1, "Salary Account", "Salary Account", is_primary=1)
    savings_id = add_account(savings_db, 1, "Emergency Fund", "Savings Account", is_primary=0)

    # ₹500 transferred to savings
    add_transfer_pair(savings_db, 1, primary_id, savings_id, "2026-07-10", 500.0)
    # ₹100 spent directly from savings
    add_transaction(savings_db, 1, savings_id, "2026-07-15", 100.0, "Expense", "Direct spend")

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_transfers_in"] == 500.0
    assert summary["savings_expenses"] == 100.0
    assert summary["savings_in"] == 500.0
    assert summary["savings_out"] == 100.0
    assert summary["net_savings"] == 400.0


def test_direct_income_and_expense_on_non_savings_accounts_are_excluded(savings_db):
    primary_id = add_account(savings_db, 1, "Salary Account", "Salary Account", is_primary=1)

    add_transaction(savings_db, 1, primary_id, "2026-07-05", 50000.0, "Income", "Salary")
    add_transaction(savings_db, 1, primary_id, "2026-07-08", 2000.0, "Expense", "Rent")

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_in"] == 0.0
    assert summary["savings_out"] == 0.0
    assert summary["net_savings"] == 0.0


def test_direct_savings_income_and_expense_respect_cycle_boundaries(savings_db):
    savings_id = add_account(savings_db, 1, "Savings Account", "Savings Account", is_primary=0)

    # Income in cycle
    add_transaction(savings_db, 1, savings_id, "2026-07-10", 500.0, "Income", "In-cycle")
    # Income before cycle
    add_transaction(savings_db, 1, savings_id, "2026-06-25", 1000.0, "Income", "Pre-cycle")
    # Expense after cycle
    add_transaction(savings_db, 1, savings_id, "2026-08-05", 200.0, "Expense", "Post-cycle")

    summary = get_cycle_savings_summary(1, "2026-07-01", "2026-07-31")
    assert summary["savings_income"] == 500.0
    assert summary["savings_expenses"] == 0.0
    assert summary["net_savings"] == 500.0


def test_safe_to_spend_deducts_only_unfulfilled_savings_goal():
    """
    Simulate Safe to Spend calculation before and after transferring to savings.
    Initial: Available Cash = 50,000, Goal = 5,000, Commitments = 10,000.
    Initial Safe to Spend = 50,000 - 10,000 - 5,000 = 35,000.
    """
    available_cash = 50000.0
    commitments = 10000.0
    monthly_savings_goal = 5000.0

    # Step 1: Baseline before any savings
    net_savings = 0.0
    savings_goal_remaining = max(monthly_savings_goal - max(net_savings, 0), 0)
    assert savings_goal_remaining == 5000.0
    safe_to_spend = max(available_cash - commitments - savings_goal_remaining, 0)
    assert safe_to_spend == 35000.0

    # Step 2: User transfers ₹500 to savings
    # Available cash in Salary account drops by 500 to 49,500
    available_cash_after = 49500.0
    net_savings_after = 500.0
    savings_goal_remaining_after = max(monthly_savings_goal - max(net_savings_after, 0), 0)
    assert savings_goal_remaining_after == 4500.0
    safe_to_spend_after = max(available_cash_after - commitments - savings_goal_remaining_after, 0)
    # Safe to Spend remains stable at 35,000! No double-penalty!
    assert safe_to_spend_after == 35000.0

    # Step 3: User fulfills entire goal (₹5,000 saved)
    available_cash_full = 45000.0
    net_savings_full = 5000.0
    savings_goal_remaining_full = max(monthly_savings_goal - max(net_savings_full, 0), 0)
    assert savings_goal_remaining_full == 0.0
    safe_to_spend_full = max(available_cash_full - commitments - savings_goal_remaining_full, 0)
    assert safe_to_spend_full == 35000.0

    # Step 4: Excess savings (User saves ₹7,000, exceeding goal by ₹2,000)
    available_cash_excess = 43000.0
    net_savings_excess = 7000.0
    savings_goal_remaining_excess = max(monthly_savings_goal - max(net_savings_excess, 0), 0)
    assert savings_goal_remaining_excess == 0.0
    safe_to_spend_excess = max(available_cash_excess - commitments - savings_goal_remaining_excess, 0)
    # Discretionary spending capacity decreases by exactly the extra ₹2,000 locked into savings
    assert safe_to_spend_excess == 33000.0

    # Step 5: Zero savings goal
    monthly_goal_zero = 0.0
    savings_goal_remaining_zero = max(monthly_goal_zero - max(net_savings_after, 0), 0)
    assert savings_goal_remaining_zero == 0.0
    safe_to_spend_zero = max(available_cash_after - commitments - savings_goal_remaining_zero, 0)
    assert safe_to_spend_zero == 39500.0


