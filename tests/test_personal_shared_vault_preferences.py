import inspect
import sqlite3

import pytest

from db import postgres
from db.identity import (
    ensure_identity_schema,
    is_shared_vault_included_in_safe_to_spend,
    is_shared_vault_shown_on_dashboard,
    reset_identity_schema_guard,
    set_shared_vault_included_in_safe_to_spend,
    set_shared_vault_shown_on_dashboard,
)
from tests.test_primary_shared_vault import get_test_conn, primary_vault_test_db  # noqa: F401


PREFERENCE_INSERT_SQL = """
            INSERT INTO personal_shared_vault_preferences (
                personal_vault_id,
                shared_vault_id,
                include_in_safe_to_spend,
                show_on_dashboard
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT (personal_vault_id, shared_vault_id) DO UPDATE SET
                include_in_safe_to_spend = EXCLUDED.include_in_safe_to_spend
            """

MIGRATION_TABLE_SQL = """
CREATE TABLE personal_shared_vault_preferences (
  personal_vault_id integer not null,
  shared_vault_id integer not null,
  include_in_safe_to_spend integer not null default 1,
  show_on_dashboard integer not null default 1,
  primary key (personal_vault_id, shared_vault_id)
);
"""


def table_columns(connection, table_name):
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def test_preference_table_matches_migration_without_id_column(tmp_path):
    connection = sqlite3.connect(tmp_path / "prefs.sqlite")
    connection.executescript(MIGRATION_TABLE_SQL)

    columns = table_columns(connection, "personal_shared_vault_preferences")
    connection.close()

    assert "id" not in columns
    assert columns == {"personal_vault_id", "shared_vault_id", "include_in_safe_to_spend", "show_on_dashboard"}


def test_upsert_toggles_include_off_against_composite_primary_key(primary_vault_test_db, monkeypatch):
    monkeypatch.setattr("db.identity.get_connection", lambda: get_test_conn(primary_vault_test_db))
    monkeypatch.setattr("db.identity.ensure_identity_schema", lambda: None)

    schema = sqlite3.connect(primary_vault_test_db)
    columns = table_columns(schema, "personal_shared_vault_preferences")
    schema.close()
    assert "id" not in columns

    assert set_shared_vault_included_in_safe_to_spend(1, 10, False, user_id="00000000-0000-4000-8000-000000000001") is False
    assert is_shared_vault_included_in_safe_to_spend(1, 10) is False

    assert set_shared_vault_included_in_safe_to_spend(1, 10, True, user_id="00000000-0000-4000-8000-000000000001") is True
    assert is_shared_vault_included_in_safe_to_spend(1, 10) is True

    stored = sqlite3.connect(primary_vault_test_db)
    row = stored.execute(
        """
        SELECT personal_vault_id, shared_vault_id, include_in_safe_to_spend, show_on_dashboard
        FROM personal_shared_vault_preferences
        WHERE personal_vault_id = 1 AND shared_vault_id = 10
        """
    ).fetchone()
    stored.close()
    assert row == (1, 10, 1, 1)

    assert set_shared_vault_shown_on_dashboard(1, 10, False, user_id="00000000-0000-4000-8000-000000000001") is False
    assert is_shared_vault_included_in_safe_to_spend(1, 10) is True
    assert is_shared_vault_shown_on_dashboard(1, 10) is False
    assert set_shared_vault_shown_on_dashboard(1, 10, True, user_id="00000000-0000-4000-8000-000000000001") is True
    assert is_shared_vault_included_in_safe_to_spend(1, 10) is True


def test_ensure_identity_schema_does_not_rerun_exclusive_ddl(monkeypatch):
    calls = []

    class Connection:
        def cursor(self):
            return "cursor"

        def commit(self):
            calls.append("commit")

        def close(self):
            calls.append("close")

    monkeypatch.setattr("db.identity.get_connection", lambda: Connection())
    monkeypatch.setattr(
        "db.identity.ensure_identity_schema_with_cursor",
        lambda cursor: calls.append(cursor)
    )
    reset_identity_schema_guard()

    ensure_identity_schema()
    ensure_identity_schema()

    assert calls == ["cursor", "commit", "close"]
    reset_identity_schema_guard()


@pytest.mark.skipif(postgres.psycopg2 is None, reason="psycopg2 is required")
def test_deadlock_retry_reruns_idempotent_operation_then_stops():
    attempts = {"count": 0}

    def succeed_on_second():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise postgres.errors.DeadlockDetected("deadlock detected")
        return "ok"

    assert postgres.run_with_deadlock_retry(succeed_on_second, attempts=3) == "ok"
    assert attempts["count"] == 2

    attempts["count"] = 0

    def always_deadlock():
        attempts["count"] += 1
        raise postgres.errors.DeadlockDetected("deadlock detected")

    with pytest.raises(postgres.errors.DeadlockDetected):
        postgres.run_with_deadlock_retry(always_deadlock, attempts=3)
    assert attempts["count"] == 3


@pytest.mark.skipif(postgres.psycopg2 is None, reason="psycopg2 is required")
def test_deadlock_retry_does_not_retry_other_errors():
    def raise_undefined():
        raise postgres.errors.UndefinedColumn('column "id" does not exist')

    with pytest.raises(postgres.errors.UndefinedColumn):
        postgres.run_with_deadlock_retry(raise_undefined, attempts=3)


def test_identity_upsert_does_not_request_lastrowid():
    source = inspect.getsource(set_shared_vault_included_in_safe_to_spend)
    assert "capture_lastrowid=False" in source
    assert "personal_shared_vault_preferences" in source


class PreferenceSchemaCursor:
    def __init__(self, raw_connection):
        self.connection = raw_connection
        self._fetch = None

    def __enter__(self):
        return self

    def __exit__(self, _error_type, _error, _traceback):
        return False

    def execute(self, sql, params=None):
        self.connection.operations.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "pg_get_serial_sequence" in normalized:
            table_name = params[0] if params else None
            if table_name == "personal_shared_vault_preferences":
                raise postgres.errors.UndefinedColumn(
                    'column "id" of relation "personal_shared_vault_preferences" does not exist'
                )
            self._fetch = (None,)
            return
        if normalized.startswith("insert into personal_shared_vault_preferences"):
            self.connection.inserted.append(params)
            self._fetch = None
            return
        if normalized.startswith("select include_in_safe_to_spend"):
            self._fetch = (0,)
            return
        self._fetch = None

    def fetchone(self):
        return self._fetch

    def close(self):
        return None


class PreferenceSchemaConnection:
    def __init__(self):
        self.operations = []
        self.inserted = []
        self.closed = 0

    def cursor(self):
        return PreferenceSchemaCursor(self)


@pytest.mark.skipif(postgres.psycopg2 is None, reason="psycopg2 is required")
def test_postgres_insert_without_id_column_does_not_fail_lastrowid():
    raw_connection = PreferenceSchemaConnection()
    cursor = postgres.PostgresCursor.from_raw_cursor(PreferenceSchemaCursor(raw_connection))

    result = cursor.execute(PREFERENCE_INSERT_SQL, (1, 7, False, True), capture_lastrowid=True)

    assert result is cursor
    assert cursor.lastrowid is None
    assert raw_connection.inserted == [(1, 7, False, True)]
    serial_lookups = [
        operation for operation in raw_connection.operations
        if operation[0] == "SELECT pg_get_serial_sequence(%s, 'id')"
    ]
    assert serial_lookups == [("SELECT pg_get_serial_sequence(%s, 'id')", ("personal_shared_vault_preferences",))]
    savepoint_ops = [operation[0] for operation in raw_connection.operations]
    assert "ROLLBACK TO SAVEPOINT money_vault_lastrowid" in savepoint_ops
    assert savepoint_ops.count("RELEASE SAVEPOINT money_vault_lastrowid") == 1
