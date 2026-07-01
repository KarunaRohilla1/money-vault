from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1])
)

from db.postgres import PostgresCursor, convert_placeholders, translate_sql


class FakeRawCursor:
    def __init__(self):
        self.executed = []
        self.rowcount = 0
        self.fetchone_value = ("one",)
        self.fetchall_value = [("one",), ("two",)]

    def execute(self, sql, params=None):
        self.executed.append(
            (
                sql,
                params
            )
        )
        self.rowcount = 1

    def fetchone(self):
        return self.fetchone_value

    def fetchall(self):
        return self.fetchall_value

    def close(self):
        pass


def run():
    cases = [
        (
            "SELECT * FROM vaults WHERE id = ?",
            "SELECT * FROM vaults WHERE id = %s"
        ),
        (
            "UPDATE transactions SET category_id = ? WHERE vault_id = ? AND notes LIKE 'Planning%'",
            "UPDATE transactions SET category_id = %s WHERE vault_id = %s AND notes LIKE 'Planning%%'"
        ),
        (
            "INSERT INTO accounts (name, opening_balance) VALUES (?, ?)",
            "INSERT INTO accounts (name, opening_balance) VALUES (%s, %s)"
        ),
        (
            "DELETE FROM transactions WHERE id = ?",
            "DELETE FROM transactions WHERE id = %s"
        ),
        (
            "SELECT * FROM wishlist_items WHERE name LIKE ?",
            "SELECT * FROM wishlist_items WHERE name LIKE %s"
        ),
        (
            "SELECT to_char(date::date, 'YYYY-MM') FROM transactions WHERE id = ?",
            "SELECT to_char(date::date, 'YYYY-MM') FROM transactions WHERE id = %s"
        ),
        (
            "SELECT pg_get_serial_sequence(%s, 'id')",
            "SELECT pg_get_serial_sequence(%s, 'id')"
        ),
        (
            "SELECT 'literal %s text' WHERE id = ?",
            "SELECT 'literal %%s text' WHERE id = %s"
        )
    ]

    for original, expected in cases:
        actual = convert_placeholders(
            original
        )
        assert actual == expected, (
            original,
            actual,
            expected
        )

    assert translate_sql(
        "SELECT '100%' WHERE id = ?"
    ) == "SELECT '100%%' WHERE id = %s"

    raw_cursor = FakeRawCursor()
    cursor = PostgresCursor(
        raw_cursor
    )
    cursor.capture_lastrowid = lambda _sql: None

    assert cursor.execute(
        "SELECT * FROM vaults WHERE id = ?",
        (1,)
    ) is cursor
    assert raw_cursor.executed[-1] == (
        "SELECT * FROM vaults WHERE id = %s",
        (1,)
    )

    cursor.execute(
        "UPDATE transactions SET notes = ? WHERE notes LIKE 'Planning%'",
        ("done",)
    )
    assert raw_cursor.executed[-1] == (
        "UPDATE transactions SET notes = %s WHERE notes LIKE 'Planning%%'",
        ("done",)
    )

    cursor.execute(
        "INSERT INTO vaults (name, pin_hash) VALUES (?, ?)",
        ("Vault", "hash")
    )
    assert raw_cursor.executed[-1] == (
        "INSERT INTO vaults (name, pin_hash) VALUES (%s, %s)",
        ("Vault", "hash")
    )

    cursor.execute(
        "DELETE FROM vaults WHERE id = ?",
        (1,)
    )
    assert raw_cursor.executed[-1] == (
        "DELETE FROM vaults WHERE id = %s",
        (1,)
    )

    assert cursor.fetchone() == ("one",)
    assert cursor.fetchall() == [("one",), ("two",)]
    assert cursor.rowcount == 1


if __name__ == "__main__":
    run()
    print("postgres wrapper checks passed")
