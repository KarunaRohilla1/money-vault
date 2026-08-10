import sqlite3

import pytest

from db.core import EXPENSE, TRANSFER_IN, TRANSFER_OUT
from db.shared_expenses import build_settlements_from_balances, get_shared_balances_with_cursor


@pytest.fixture
def shared_balance_db(tmp_path):
    db_path = tmp_path / "shared-balances.sqlite"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE vaults (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            vault_type TEXT NOT NULL
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
            amount REAL NOT NULL,
            transaction_type TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            date TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE transaction_shares (
            transaction_id INTEGER NOT NULL,
            participant_vault_id INTEGER NOT NULL,
            share_amount REAL NOT NULL
        );

        INSERT INTO vaults (id, name, vault_type) VALUES
            (40, 'Shared Home', 'Shared'),
            (4, 'Alex', 'Individual'),
            (5, 'Sam', 'Individual');

        INSERT INTO vault_shares (vault_id, shared_vault_id) VALUES
            (40, 4),
            (40, 5);
        """
    )
    connection.commit()
    connection.close()
    return db_path


def test_unsettled_balances_carry_into_a_new_cycle(shared_balance_db):
    connection = sqlite3.connect(shared_balance_db)
    connection.execute(
        """
        INSERT INTO transactions (
            vault_id,
            beneficiary_vault_id,
            amount,
            transaction_type,
            date
        )
        VALUES (4, 40, 460, ?, '2026-06-15')
        """,
        (EXPENSE,)
    )
    transaction_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.executemany(
        """
        INSERT INTO transaction_shares (transaction_id, participant_vault_id, share_amount)
        VALUES (?, ?, ?)
        """,
        [
            (transaction_id, 4, 230),
            (transaction_id, 5, 230)
        ]
    )
    connection.commit()

    balances = get_shared_balances_with_cursor(
        connection.cursor(),
        40,
        "2026-07-01",
        "2026-07-31"
    )
    connection.close()

    alex = next(item for item in balances if item["vault_id"] == 4)
    sam = next(item for item in balances if item["vault_id"] == 5)

    assert alex["paid"] == 0
    assert alex["share"] == 0
    assert alex["balance"] == 230
    assert sam["paid"] == 0
    assert sam["share"] == 0
    assert sam["balance"] == -230

    settlements = build_settlements_from_balances(balances)
    assert settlements == [
        {
            "from_vault_id": 5,
            "from": "Sam",
            "to_vault_id": 4,
            "to": "Alex",
            "amount": 230
        }
    ]


def test_prior_cycle_settlement_clears_carried_balance(shared_balance_db):
    connection = sqlite3.connect(shared_balance_db)
    connection.execute(
        """
        INSERT INTO transactions (
            vault_id,
            beneficiary_vault_id,
            amount,
            transaction_type,
            date
        )
        VALUES (4, 40, 460, ?, '2026-06-15')
        """,
        (EXPENSE,)
    )
    transaction_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.executemany(
        """
        INSERT INTO transaction_shares (transaction_id, participant_vault_id, share_amount)
        VALUES (?, ?, ?)
        """,
        [
            (transaction_id, 4, 230),
            (transaction_id, 5, 230)
        ]
    )
    connection.executemany(
        """
        INSERT INTO transactions (
            vault_id,
            beneficiary_vault_id,
            amount,
            transaction_type,
            date,
            notes
        )
        VALUES (?, 40, 230, ?, '2026-06-20', 'Shared settlement: Sam paid Alex')
        """,
        [
            (5, TRANSFER_OUT),
            (4, TRANSFER_IN)
        ]
    )
    connection.commit()

    balances = get_shared_balances_with_cursor(
        connection.cursor(),
        40,
        "2026-07-01",
        "2026-07-31"
    )
    connection.close()

    assert all(item["balance"] == 0 for item in balances)
    assert build_settlements_from_balances(balances) == []
