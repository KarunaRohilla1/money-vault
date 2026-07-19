from types import SimpleNamespace
import sqlite3

from fastapi.testclient import TestClient
import pytest


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
            name="Karuna",
            vault_type="Individual",
            is_admin=False
        )
    )
    return {"Authorization": f"Bearer {token}"}


def transfer_payload(date="2026-07-17"):
    return {
        "amount": 100.50,
        "date": date,
        "fromAccountId": 1,
        "notes": "Savings",
        "toAccountId": 2
    }


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
    def __init__(self, path, fail_on_execute=None):
        self.connection = sqlite3.connect(path)
        self.execute_count = 0
        self.fail_on_execute = fail_on_execute
        self.rollback_count = 0

    def execute(self, sql, params=None, capture_lastrowid=True):
        self.execute_count += 1
        if self.fail_on_execute == self.execute_count:
            raise RuntimeError("forced database failure")
        return SqliteCursor(self.connection.cursor()).execute(sql, params, capture_lastrowid=capture_lastrowid)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.rollback_count += 1
        self.connection.rollback()

    def close(self):
        self.connection.close()


@pytest.fixture
def transfer_db(tmp_path, monkeypatch):
    db_path = tmp_path / "transfers.sqlite"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
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
    monkeypatch.setattr("db.transfers.clear_data_cache", lambda *_args, **_kwargs: None)
    return db_path


def transfer_rows(db_path, group_id):
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(
            """
            SELECT transaction_type, account_id, amount
            FROM transactions
            WHERE transfer_group_id = ?
            ORDER BY transaction_type, id
            """,
            (group_id,)
        ).fetchall()
    finally:
        connection.close()


def insert_transfer_row(db_path, group_id, transaction_type, vault_id=4, account_id=1, amount=100):
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO transactions (
                vault_id,
                beneficiary_vault_id,
                account_id,
                date,
                amount,
                transaction_type,
                notes,
                transfer_group_id,
                is_deleted
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (vault_id, vault_id, account_id, "2026-07-17", amount, transaction_type, "Note", group_id)
        )
        connection.commit()
    finally:
        connection.close()


def install_transfer_connection(monkeypatch, db_path, fail_on_execute=None):
    holders = []

    def factory():
        connection = SqliteConnection(db_path, fail_on_execute=fail_on_execute)
        holders.append(connection)
        return connection

    monkeypatch.setattr("db.transfers.get_connection", factory)
    return holders


def test_create_transfer_rejects_invalid_calendar_date(monkeypatch):
    client = build_client(monkeypatch)

    response = client.post(
        "/api/transfers",
        headers=auth_header(),
        json=transfer_payload(date="2026-02-31")
    )

    assert response.status_code == 422


def test_transfer_filters_reject_invalid_calendar_dates(monkeypatch):
    client = build_client(monkeypatch)

    response = client.get(
        "/api/transfers?dateFrom=2026-02-31",
        headers=auth_header()
    )

    assert response.status_code == 422


def test_create_transfer_passes_iso_date_to_legacy_helper(monkeypatch):
    client = build_client(monkeypatch)
    observed = {}

    monkeypatch.setattr("api.transfers.require_account", lambda account_id, vault_id: None)
    monkeypatch.setattr("api.transfers.add_transfer", lambda vault_id, from_id, to_id, transfer_date, amount, notes: observed.update({
        "amount": amount,
        "date": transfer_date,
        "from": from_id,
        "notes": notes,
        "to": to_id,
        "vault": vault_id
    }) or "group-1")
    monkeypatch.setattr("api.transfers.get_transfer_by_group", lambda transfer_group_id: ("group-1", 4, "2026-07-17", 1, 2, 100.50, "Savings"))

    response = client.post(
        "/api/transfers",
        headers=auth_header(),
        json=transfer_payload()
    )

    assert response.status_code == 200
    assert observed == {
        "amount": 100.50,
        "date": "2026-07-17",
        "from": 1,
        "notes": "Savings",
        "to": 2,
        "vault": 4
    }


def test_create_transfer_validates_destination_account_ownership(monkeypatch):
    from fastapi import HTTPException

    client = build_client(monkeypatch)
    checked_accounts = []

    def fake_require_account(account_id, vault_id):
        checked_accounts.append((account_id, vault_id))
        if account_id == 2:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})

    monkeypatch.setattr("api.transfers.require_account", fake_require_account)
    add_transfer = pytest.fail
    monkeypatch.setattr("api.transfers.add_transfer", lambda *_args, **_kwargs: add_transfer("add_transfer should not run"))

    response = client.post(
        "/api/transfers",
        headers=auth_header(),
        json=transfer_payload()
    )

    assert response.status_code == 404
    assert checked_accounts == [(1, 4), (2, 4)]


def test_create_transfer_rolls_back_if_second_insert_fails(monkeypatch, transfer_db):
    from db.transfers import add_transfer

    holders = install_transfer_connection(monkeypatch, transfer_db, fail_on_execute=2)

    with pytest.raises(RuntimeError):
        add_transfer(4, 1, 2, "2026-07-17", 100.50, "Savings")

    assert holders[0].rollback_count == 1
    connection = sqlite3.connect(transfer_db)
    try:
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    finally:
        connection.close()


def test_valid_pair_update_succeeds(monkeypatch, transfer_db):
    from db.core import TRANSFER_IN, TRANSFER_OUT
    from db.transfers import update_transfer

    install_transfer_connection(monkeypatch, transfer_db)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_OUT, account_id=1)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_IN, account_id=2)

    update_transfer("group-1", 3, 4, "2026-07-18", 200.25, "Updated")

    assert transfer_rows(transfer_db, "group-1") == [
        (TRANSFER_IN, 4, 200.25),
        (TRANSFER_OUT, 3, 200.25)
    ]


def test_valid_pair_delete_succeeds(monkeypatch, transfer_db):
    from db.core import TRANSFER_IN, TRANSFER_OUT
    from db.transfers import delete_transfer

    install_transfer_connection(monkeypatch, transfer_db)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_OUT, account_id=1)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_IN, account_id=2)

    delete_transfer("group-1")

    assert transfer_rows(transfer_db, "group-1") == []


def test_get_transfers_filters_by_source_and_destination(monkeypatch, transfer_db):
    from db.core import TRANSFER_IN, TRANSFER_OUT
    from db.transfers import get_transfers

    connection = sqlite3.connect(transfer_db)
    try:
        connection.executescript(
            """
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            INSERT INTO accounts (id, name) VALUES (1, 'Salary'), (2, 'Savings'), (3, 'Cash');
            """
        )
        connection.commit()
    finally:
        connection.close()

    install_transfer_connection(monkeypatch, transfer_db)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_OUT, account_id=1)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_IN, account_id=2)
    insert_transfer_row(transfer_db, "group-2", TRANSFER_OUT, account_id=3)
    insert_transfer_row(transfer_db, "group-2", TRANSFER_IN, account_id=2)

    transfers = get_transfers(4, source_account_id=1, destination_account_id=2)

    assert [row[0] for row in transfers] == ["group-1"]


@pytest.mark.parametrize(
    ("rows", "expected_message"),
    [
        (["Transfer In"], "Transfer pair is corrupted."),
        (["Transfer Out"], "Transfer pair is corrupted."),
        (["Transfer Out", "Transfer Out", "Transfer In"], "Transfer pair is corrupted."),
        (["Transfer Out", "Transfer In", "Transfer In"], "Transfer pair is corrupted."),
    ]
)
def test_corrupted_pair_is_rejected_before_update(monkeypatch, transfer_db, rows, expected_message):
    from db.transfers import TransferPairIntegrityError, update_transfer

    holders = install_transfer_connection(monkeypatch, transfer_db)
    for index, transaction_type in enumerate(rows, start=1):
        insert_transfer_row(transfer_db, "group-1", transaction_type, account_id=index)

    with pytest.raises(TransferPairIntegrityError, match=expected_message):
        update_transfer("group-1", 3, 4, "2026-07-18", 200.25, "Updated")

    assert holders[0].rollback_count == 1


def test_wrong_vault_pair_is_rejected(monkeypatch, transfer_db):
    from db.core import TRANSFER_IN, TRANSFER_OUT
    from db.transfers import TransferPairIntegrityError, require_valid_transfer_pair

    install_transfer_connection(monkeypatch, transfer_db)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_OUT, vault_id=99, account_id=1)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_IN, vault_id=99, account_id=2)

    with pytest.raises(TransferPairIntegrityError):
        require_valid_transfer_pair("group-1", vault_id=4)


def test_update_rolls_back_if_second_update_fails(monkeypatch, transfer_db):
    from db.core import TRANSFER_IN, TRANSFER_OUT
    from db.transfers import update_transfer

    holders = install_transfer_connection(monkeypatch, transfer_db, fail_on_execute=3)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_OUT, account_id=1)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_IN, account_id=2)

    with pytest.raises(RuntimeError):
        update_transfer("group-1", 3, 4, "2026-07-18", 200.25, "Updated")

    assert holders[0].rollback_count == 1
    assert transfer_rows(transfer_db, "group-1") == [
        (TRANSFER_IN, 2, 100.0),
        (TRANSFER_OUT, 1, 100.0)
    ]


def test_delete_rolls_back_if_integrity_validation_fails(monkeypatch, transfer_db):
    from db.core import TRANSFER_OUT
    from db.transfers import TransferPairIntegrityError, delete_transfer

    holders = install_transfer_connection(monkeypatch, transfer_db)
    insert_transfer_row(transfer_db, "group-1", TRANSFER_OUT, account_id=1)

    with pytest.raises(TransferPairIntegrityError):
        delete_transfer("group-1")

    assert holders[0].rollback_count == 1
    assert len(transfer_rows(transfer_db, "group-1")) == 1
