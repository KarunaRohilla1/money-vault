import sqlite3

import pytest


def clear_account_caches():
    import db.accounts as accounts

    for name in (
        "get_account_balance",
        "get_account_balances",
        "get_accounts",
        "get_accounts_with_balances",
        "get_account_by_id",
        "get_primary_account",
        "account_has_transactions"
    ):
        function = getattr(accounts, name)
        clear = getattr(function, "clear", None)
        if clear:
            clear()


class SqliteCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

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

    def cursor(self):
        return SqliteCursor(self.connection.cursor())

    def execute(self, sql, params=None, capture_lastrowid=True):
        return self.cursor().execute(sql, params, capture_lastrowid=capture_lastrowid)

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()


@pytest.fixture
def account_db(tmp_path, monkeypatch):
    db_path = tmp_path / "accounts.sqlite"
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
            vault_id INTEGER,
            account_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            transaction_type TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr("db.accounts.get_connection", lambda: SqliteConnection(db_path))
    monkeypatch.setattr("db.accounts.clear_data_cache", lambda *_args, **_kwargs: clear_account_caches())
    clear_account_caches()

    return db_path


def rows(db_path, sql, params=()):
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def insert_account(db_path, vault_id, name, account_type, opening_balance, is_primary=0, is_active=1):
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute(
            """
            INSERT INTO accounts (vault_id, name, type, opening_balance, is_primary, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (vault_id, name, account_type, opening_balance, is_primary, is_active)
        )
        connection.commit()
        account_id = cursor.lastrowid
        clear_account_caches()
        return account_id
    finally:
        connection.close()


def insert_transaction(db_path, account_id, transaction_type, amount, is_deleted=0):
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO transactions (account_id, transaction_type, amount, is_deleted)
            VALUES (?, ?, ?, ?)
            """,
            (account_id, transaction_type, amount, is_deleted)
        )
        connection.commit()
        clear_account_caches()
    finally:
        connection.close()


def test_first_account_becomes_primary_and_second_stays_non_primary(account_db):
    from db.accounts import add_account

    add_account(1, "Salary", "Salary Account", 1000, is_primary=False)
    add_account(1, "Savings", "Savings Account", 500, is_primary=False)

    assert rows(account_db, "SELECT name, is_primary FROM accounts ORDER BY id") == [
        ("Salary", 1),
        ("Savings", 0)
    ]


def test_requested_primary_clears_previous_primary(account_db):
    from db.accounts import add_account, set_primary_account

    add_account(1, "Salary", "Salary Account", 1000, is_primary=False)
    add_account(1, "Savings", "Savings Account", 500, is_primary=False)

    savings_id = rows(account_db, "SELECT id FROM accounts WHERE name = 'Savings'")[0][0]
    set_primary_account(savings_id)

    assert rows(account_db, "SELECT name, is_primary FROM accounts ORDER BY id") == [
        ("Salary", 0),
        ("Savings", 1)
    ]


def test_account_ordering_matches_legacy_primary_type_name(account_db):
    from db.accounts import get_accounts_with_balances

    insert_account(account_db, 1, "Zoo", "Savings Account", 0, is_primary=0)
    insert_account(account_db, 1, "Primary", "Other", 0, is_primary=1)
    insert_account(account_db, 1, "Alpha", "Savings Account", 0, is_primary=0)
    insert_account(account_db, 1, "Card", "Credit Card", 0, is_primary=0)
    insert_account(account_db, 1, "Archived", "Salary Account", 0, is_primary=0, is_active=0)
    insert_account(account_db, 2, "Other Vault", "Salary Account", 0, is_primary=1)

    assert [row[1] for row in get_accounts_with_balances(1)] == [
        "Primary",
        "Card",
        "Alpha",
        "Zoo"
    ]


def test_archive_non_primary_and_primary_promotes_legacy_next_active(account_db):
    from db.accounts import archive_account

    first_id = insert_account(account_db, 1, "First", "Salary Account", 0, is_primary=1)
    second_id = insert_account(account_db, 1, "Second", "Savings Account", 0, is_primary=0)
    third_id = insert_account(account_db, 1, "Third", "Credit Card", 0, is_primary=0)

    archive_account(third_id)
    assert rows(account_db, "SELECT id, is_active, is_primary FROM accounts WHERE id = ?", (third_id,)) == [(third_id, 0, 0)]

    archive_account(first_id)
    assert rows(account_db, "SELECT id, is_active, is_primary FROM accounts ORDER BY id") == [
        (first_id, 0, 0),
        (second_id, 1, 1),
        (third_id, 0, 0)
    ]


def test_balance_formula_uses_legacy_transaction_types(account_db):
    from db.accounts import get_account_balance

    account_id = insert_account(account_db, 1, "Salary", "Salary Account", 100)
    insert_transaction(account_db, account_id, "Income", 50)
    insert_transaction(account_db, account_id, "Expense", 20)
    insert_transaction(account_db, account_id, "Transfer In", 30)
    insert_transaction(account_db, account_id, "Transfer Out", 10)
    insert_transaction(account_db, account_id, "Income", 999, is_deleted=1)
    insert_transaction(account_db, account_id, "Ignored", 999)

    assert get_account_balance(account_id) == 150


def test_credit_card_negative_balance_contributes_to_due(account_db):
    from db.accounts import get_credit_card_due, get_total_credit_card_due

    card_id = insert_account(account_db, 1, "Card", "Credit Card", -100)
    paid_card_id = insert_account(account_db, 1, "Paid Card", "Credit Card", 50)
    savings_id = insert_account(account_db, 1, "Savings", "Savings Account", -999)
    insert_transaction(account_db, card_id, "Expense", 25)
    insert_transaction(account_db, paid_card_id, "Income", 25)
    insert_transaction(account_db, savings_id, "Expense", 1)

    assert get_credit_card_due(card_id) == 125
    assert get_total_credit_card_due(1) == 125
