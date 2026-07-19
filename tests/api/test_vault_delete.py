class RecordingCursor:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append(
            (
                " ".join(sql.split()),
                params
            )
        )
        return self


class RecordingConnection:
    def __init__(self):
        self.cursor_instance = RecordingCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_delete_vault_cleans_current_schema_relationships(monkeypatch):
    connection = RecordingConnection()

    monkeypatch.setattr(
        "db.vaults.get_connection",
        lambda: connection
    )
    monkeypatch.setattr(
        "db.vaults.clear_data_cache",
        lambda _domains: None
    )

    from db.vaults import delete_vault

    delete_vault(42)

    sql_text = "\n".join(
        statement
        for statement, _params in connection.cursor_instance.statements
    )

    assert "DELETE FROM cycle_contributions" in sql_text
    assert "DELETE FROM financial_cycles" in sql_text
    assert "payer_vault_id = ?" in sql_text
    assert sql_text.index("DELETE FROM cycle_contributions") < sql_text.index("DELETE FROM financial_cycles")
    assert sql_text.index("DELETE FROM financial_cycles") < sql_text.index("DELETE FROM vaults")
    assert connection.committed is True
    assert connection.closed is True
