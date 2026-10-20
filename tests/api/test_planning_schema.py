import threading
import pytest
from db import postgres
from db.planning import (
    ensure_planning_schema,
    ensure_planning_schema_with_cursor,
    reset_planning_schema_guard,
    get_obligation_status,
    save_obligation_status,
    get_planning_activity_statuses,
    get_monthly_planning_totals,
    get_cycle_planning_summary,
    finalize_month,
)


class MockCursor:
    def __init__(self, failure_on=None):
        self.operations = []
        self.failure_on = failure_on or {}
        self.lastrowid = 1
        self.rowcount = 1

    def execute(self, sql, params=None, capture_lastrowid=True):
        if sql in self.failure_on:
            raise self.failure_on[sql]
        self.operations.append((sql, params))
        return self

    def fetchone(self):
        # Default mock row suitable for planning items
        return (1, 1, "Rent", 15000.0, 10, "Account", 1)

    def fetchall(self):
        return []

    def close(self):
        pass


class MockConnection:
    def __init__(self, cursor=None, fail_on_commit=False):
        self._cursor = cursor or MockCursor()
        self.commit_count = 0
        self.close_count = 0
        self.rollback_count = 0
        self.fail_on_commit = fail_on_commit

    def cursor(self):
        return self._cursor

    def execute(self, sql, params=None, capture_lastrowid=True):
        return self._cursor.execute(sql, params, capture_lastrowid=capture_lastrowid)

    def commit(self):
        if self.fail_on_commit:
            raise RuntimeError("Database commit error")
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.close_count += 1


def test_ensure_planning_schema_idempotency_guard(monkeypatch):
    """Calling ensure_planning_schema repeatedly executes only once per process."""
    conn = MockConnection()
    monkeypatch.setattr("db.planning.get_connection", lambda: conn)
    reset_planning_schema_guard()

    ensure_planning_schema()
    ensure_planning_schema()
    ensure_planning_schema()

    assert conn.commit_count == 1
    assert conn.close_count == 1
    assert len(conn._cursor.operations) == 2

    # Resetting guard allows it to run again
    reset_planning_schema_guard()
    ensure_planning_schema()
    assert conn.commit_count == 2
    assert conn.close_count == 2

    reset_planning_schema_guard()


def test_ensure_planning_schema_statements():
    """Verify exact PostgreSQL-native DDL statements executed for paid_date."""
    cursor = MockCursor()
    ensure_planning_schema_with_cursor(cursor)

    executed_sqls = [op[0] for op in cursor.operations]
    assert executed_sqls == [
        "ALTER TABLE obligation_status ADD COLUMN IF NOT EXISTS paid_date TEXT",
        "ALTER TABLE income_status ADD COLUMN IF NOT EXISTS paid_date TEXT",
    ]


def test_ensure_planning_schema_repeated_cursor_execution():
    """Running ensure_planning_schema_with_cursor repeatedly executes native IF NOT EXISTS idempotently."""
    cursor = MockCursor()
    ensure_planning_schema_with_cursor(cursor)
    ensure_planning_schema_with_cursor(cursor)

    assert len(cursor.operations) == 4
    for sql, _ in cursor.operations:
        assert "ADD COLUMN IF NOT EXISTS paid_date TEXT" in sql


def test_migration_failure_does_not_mark_schema_ready_and_propagates(monkeypatch):
    """When DDL fails (e.g. lock timeout or connection drop), error propagates and schema is NOT ready."""
    failing_cursor = MockCursor(failure_on={
        "ALTER TABLE obligation_status ADD COLUMN IF NOT EXISTS paid_date TEXT": RuntimeError("Lock timeout acquiring AccessExclusiveLock")
    })
    failing_conn = MockConnection(cursor=failing_cursor)
    monkeypatch.setattr("db.planning.get_connection", lambda: failing_conn)
    reset_planning_schema_guard()

    with pytest.raises(RuntimeError, match="Lock timeout"):
        ensure_planning_schema()

    # The schema guard must NOT be marked ready
    from db.planning import _planning_schema_ready
    assert _planning_schema_ready is False

    # A subsequent healthy call retries and succeeds
    healthy_conn = MockConnection()
    monkeypatch.setattr("db.planning.get_connection", lambda: healthy_conn)
    ensure_planning_schema()

    import db.planning
    assert db.planning._planning_schema_ready is True
    reset_planning_schema_guard()


def test_migration_commit_failure_does_not_mark_schema_ready(monkeypatch):
    """If conn.commit() fails, error propagates and schema is NOT marked ready."""
    failing_conn = MockConnection(fail_on_commit=True)
    monkeypatch.setattr("db.planning.get_connection", lambda: failing_conn)
    reset_planning_schema_guard()

    with pytest.raises(RuntimeError, match="Database commit error"):
        ensure_planning_schema()

    import db.planning
    assert db.planning._planning_schema_ready is False
    reset_planning_schema_guard()


def test_finalize_month_does_not_execute_ddl_inside_transaction(monkeypatch):
    """Inner transaction in finalize_month must NEVER run ALTER TABLE DDL on its cursor."""
    reset_planning_schema_guard()

    schema_conn = MockConnection()
    biz_cursor = MockCursor()
    biz_conn = MockConnection(cursor=biz_cursor)

    connections = [schema_conn, biz_conn]
    monkeypatch.setattr("db.planning.get_connection", lambda: connections.pop(0) if connections else biz_conn)

    # 3 items to process
    updated_items = [
        {"id": 101, "type": "commitment", "action": "Paid", "amount": 5000.0},
        {"id": 102, "type": "commitment", "action": "Carry Forward", "amount": 3000.0},
        {"id": 201, "type": "income", "action": "Paid", "amount": 80000.0},
    ]

    finalize_month(vault_id=1, month=10, year=2026, updated_items=updated_items)

    # All operations on the business transaction cursor must be DML, NEVER DDL
    biz_sqls = [op[0] for op in biz_cursor.operations]
    for sql in biz_sqls:
        assert "ALTER TABLE" not in sql, f"Found unexpected DDL in finalize_month transaction: {sql}"

    # Verify that DDL was only executed on the outer schema connection
    schema_sqls = [op[0] for op in schema_conn._cursor.operations]
    assert any("ALTER TABLE obligation_status" in s for s in schema_sqls)
    reset_planning_schema_guard()


def test_concurrent_ensure_planning_schema_threads(monkeypatch):
    """Simulate concurrent threads calling ensure_planning_schema simultaneously."""
    reset_planning_schema_guard()
    real_calls = []

    class CountingConnection(MockConnection):
        def commit(self):
            real_calls.append("commit")
            super().commit()

    monkeypatch.setattr("db.planning.get_connection", lambda: CountingConnection())

    threads = []
    for _ in range(10):
        t = threading.Thread(target=ensure_planning_schema)
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Even with 10 concurrent threads, the migration only executes and commits once
    assert len(real_calls) == 1
    reset_planning_schema_guard()


@pytest.mark.skipif(postgres.psycopg2 is None, reason="psycopg2 required for Postgres tests")
def test_ensure_planning_schema_postgres_compatibility():
    """Verify that statements pass through PostgresConnection translation cleanly."""
    class FakeRawConn:
        def __init__(self):
            self.operations = []
            self.closed = 0
            self.commit_count = 0
            self.rollback_count = 0

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=None):
            self.operations.append((sql, params))

        def commit(self):
            self.commit_count += 1

        def rollback(self):
            self.rollback_count += 1

        def close(self):
            self.closed = 1

    fake_raw = FakeRawConn()
    pg_conn = postgres.PostgresConnection(fake_raw)
    pg_cursor = pg_conn.cursor()

    ensure_planning_schema_with_cursor(pg_cursor)

    executed = [op[0] for op in fake_raw.operations]
    assert "ALTER TABLE obligation_status ADD COLUMN IF NOT EXISTS paid_date TEXT" in executed
    assert "ALTER TABLE income_status ADD COLUMN IF NOT EXISTS paid_date TEXT" in executed


def test_planning_functions_trigger_schema_migration(monkeypatch):
    """Verify planning entry points trigger ensure_planning_schema before querying."""
    migration_calls = []

    def tracking_migration():
        migration_calls.append("migrated")

    monkeypatch.setattr("db.planning.ensure_planning_schema", tracking_migration)

    class DummyConn:
        def execute(self, sql, params=None, capture_lastrowid=True):
            return self

        def fetchone(self):
            return (1, 1, 1, 1, 1, 1, 1)

        def fetchall(self):
            return []

        def close(self):
            pass

    monkeypatch.setattr("db.planning.get_connection", lambda: DummyConn())

    # Call get_obligation_status
    migration_calls.clear()
    get_obligation_status(1, 10, 2026)
    assert "migrated" in migration_calls

    # Call get_planning_activity_statuses
    migration_calls.clear()
    get_planning_activity_statuses(1, 10, 2026)
    assert "migrated" in migration_calls

    # Call get_monthly_planning_totals
    migration_calls.clear()
    get_monthly_planning_totals(1, 10, 2026)
    assert "migrated" in migration_calls

    # Call get_cycle_planning_summary
    migration_calls.clear()
    get_cycle_planning_summary(1, 10, 2026, "2026-10-01", "2026-10-31")
    assert "migrated" in migration_calls


def test_migrate_database_includes_planning_schema(monkeypatch):
    """Verify that db/core.py migrate_database includes ensure_planning_schema_with_cursor."""
    from db.core import migrate_database

    planning_called = []
    monkeypatch.setattr(
        "db.planning.ensure_planning_schema_with_cursor",
        lambda cursor: planning_called.append("called")
    )

    class FakeCoreConn:
        def cursor(self):
            return MockCursor()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("db.core.get_connection", lambda: FakeCoreConn())

    migrate_database()
    assert "called" in planning_called
