import pytest

from db import postgres


pytestmark = pytest.mark.skipif(
    postgres.psycopg2 is None,
    reason="psycopg2 is required for PostgreSQL reconnect tests"
)


class FakeCursor:
    def __init__(self, raw_connection):
        self.connection = raw_connection
        self.rowcount = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, _error_type, _error, _traceback):
        self.close()
        return False

    def execute(self, sql, params=None):
        if sql == "SELECT 1":
            self.connection.health_checks += 1
            if not self.connection.health_usable:
                raise postgres.OperationalError("health check failed")
        else:
            self.connection.operations.append(
                (
                    sql,
                    params
                )
            )
            if self.connection.operation_failures:
                error_class = self.connection.operation_failures.pop(0)
                raise error_class("stale connection")

        self.rowcount = 1

    def fetchone(self):
        return (1,)

    def fetchall(self):
        return [(1,)]

    def close(self):
        self.closed = True


class FakeRawConnection:
    def __init__(self, *, closed=0, health_usable=True, operation_failures=None):
        self.closed = closed
        self.health_usable = health_usable
        self.operation_failures = list(operation_failures or [])
        self.operations = []
        self.health_checks = 0
        self.rollback_count = 0
        self.commit_count = 0

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rollback_count += 1

    def commit(self):
        self.commit_count += 1

    def close(self):
        self.closed = 1


class FakePool:
    def __init__(self, *connections):
        self.connections = list(connections)
        self.returned = []
        self.discarded = []
        self.get_count = 0

    def getconn(self):
        self.get_count += 1
        return self.connections.pop(0)

    def putconn(self, connection, close=False):
        if close:
            connection.close()
            self.discarded.append(connection)
            return

        self.returned.append(connection)


def test_closed_cached_connection_is_discarded_before_use():
    closed_connection = FakeRawConnection(closed=1)
    healthy_connection = FakeRawConnection()
    pool = FakePool(
        closed_connection,
        healthy_connection
    )

    selected = postgres.get_healthy_pool_connection(pool)

    assert selected is healthy_connection
    assert closed_connection in pool.discarded
    assert closed_connection.closed == 1
    assert healthy_connection.health_checks == 1


def test_operational_error_on_read_reconnects_and_retries_once():
    stale_connection = FakeRawConnection(
        operation_failures=[postgres.OperationalError]
    )
    healthy_connection = FakeRawConnection()
    pool = FakePool(healthy_connection)
    connection = postgres.PostgresConnection(
        stale_connection,
        pool
    )

    cursor = connection.cursor()
    cursor.execute(
        "SELECT * FROM vaults WHERE id = ?",
        (7,)
    )

    assert stale_connection in pool.discarded
    assert stale_connection.operations == [
        (
            "SELECT * FROM vaults WHERE id = %s",
            (7,)
        )
    ]
    assert healthy_connection.operations == [
        (
            "SELECT * FROM vaults WHERE id = %s",
            (7,)
        )
    ]


def test_interface_error_on_read_reconnects_and_retries_once():
    stale_connection = FakeRawConnection(
        operation_failures=[postgres.InterfaceError]
    )
    healthy_connection = FakeRawConnection()
    pool = FakePool(healthy_connection)
    connection = postgres.PostgresConnection(
        stale_connection,
        pool
    )

    cursor = connection.cursor()
    cursor.execute("SELECT * FROM accounts")

    assert stale_connection in pool.discarded
    assert len(stale_connection.operations) == 1
    assert len(healthy_connection.operations) == 1


def test_stale_read_retry_occurs_at_most_once():
    first_connection = FakeRawConnection(
        operation_failures=[postgres.OperationalError]
    )
    second_connection = FakeRawConnection(
        operation_failures=[postgres.OperationalError]
    )
    pool = FakePool(second_connection)
    connection = postgres.PostgresConnection(
        first_connection,
        pool
    )

    cursor = connection.cursor()

    with pytest.raises(postgres.OperationalError):
        cursor.execute("SELECT * FROM transactions")

    assert len(first_connection.operations) == 1
    assert len(second_connection.operations) == 1


def test_write_operation_is_not_retried_after_stale_connection_error():
    stale_connection = FakeRawConnection(
        operation_failures=[postgres.OperationalError]
    )
    replacement_connection = FakeRawConnection()
    pool = FakePool(replacement_connection)
    connection = postgres.PostgresConnection(
        stale_connection,
        pool
    )

    cursor = connection.cursor()

    with pytest.raises(postgres.OperationalError):
        cursor.execute(
            "UPDATE vaults SET name = ? WHERE id = ?",
            (
                "Renamed",
                7
            )
        )

    assert len(stale_connection.operations) == 1
    assert replacement_connection.operations == []
    assert pool.get_count == 0


def test_healthy_connection_is_returned_to_pool_on_close():
    healthy_connection = FakeRawConnection()
    pool = FakePool()
    connection = postgres.PostgresConnection(
        healthy_connection,
        pool
    )

    connection.close()

    assert connection.closed is True
    assert healthy_connection.rollback_count == 1
    assert pool.returned == [healthy_connection]
    assert pool.discarded == []
